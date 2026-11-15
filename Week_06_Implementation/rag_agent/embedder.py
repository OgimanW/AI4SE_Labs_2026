#!/usr/bin/env python3
"""
embedder.py - turn repository chunks (chunks.json from Task 2) into embedding
vectors, store them, and retrieve the most relevant chunks for a query.

Two embedding backends (see REPORT_embeddings.md for the reasoning):

  bge  (default)  BAAI/bge-small-en-v1.5 via `fastembed` (ONNX runtime, no
                  PyTorch). 384-dim dense vectors, 512-token input window,
                  which matches the chunk limit from Task 2.
                  pip install fastembed   (downloads ~130 MB model once)

  lsa  (offline)  TF-IDF over code-aware tokens + truncated SVD (Latent
                  Semantic Analysis). Needs only numpy + scikit-learn and no
                  download. Used automatically if the bge model cannot be
                  loaded, or explicitly with --backend lsa.

What is embedded: the chunk's `embed_text` (context header with file path,
module/class docstring + the code itself) prefixed by the qualified symbol
names it contains.

Storage (directory, default ./vector_store):
  vectors.npy   float32 matrix N x d, rows L2-normalised (cosine = dot)
  index.json    backend/model info + per-row chunk metadata (id, file,
                lines, symbols, is_test) - full text stays in chunks.json
  lsa.pkl       fitted TF-IDF + SVD (only for the lsa backend; needed to
                embed queries into the same space)

Retrieval: exact cosine similarity (one matrix-vector product) + top-k.

Usage:
  python embedder.py build  [--chunks chunks.json] [--out vector_store] [--backend bge|lsa]
  python embedder.py search "add a discount for VIP customers" [-k 5] [--no-tests]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import re
import sys
from typing import Dict, List, Optional, Sequence

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CHUNKS = os.path.join(HERE, "chunks.json")
DEFAULT_STORE = os.path.join(HERE, "vector_store")

BGE_MODEL = "BAAI/bge-small-en-v1.5"
# bge models are trained with this instruction on the *query* side only
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
LSA_DIM = 128


# --------------------------------------------------------------------------
# What text represents a chunk
# --------------------------------------------------------------------------

def chunk_to_text(chunk: Dict) -> str:
    """Text that is embedded for one chunk."""
    symbols = ", ".join(chunk.get("symbols") or [])
    head = f"# Symbols: {symbols}\n" if symbols else ""
    return head + chunk["embed_text"]


# --------------------------------------------------------------------------
# Code-aware tokenizer (for the LSA backend)
# --------------------------------------------------------------------------

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_STOP = {"self", "the", "a", "an", "of", "to", "is", "and", "or", "in", "for",
         "def", "return", "if", "else", "none", "true", "false", "import",
         "from", "with", "as", "not", "be", "it", "on", "by", "this", "that",
         "class", "str", "int", "type", "ignore", "annotations", "future"}


def code_tokens(text: str) -> List[str]:
    """Split identifiers: `OrderBuilder.add_item` -> orderbuilder, order,
    builder, add_item, add, item. Keeps the full identifier and its parts so
    both exact names and natural-language words match."""
    out: List[str] = []
    for ident in _IDENT.findall(text):
        low = ident.lower().strip("_")
        if not low:
            continue
        parts = [p.lower() for piece in ident.split("_") for p in _CAMEL.findall(piece)]
        if low not in _STOP and len(low) > 1:
            out.append(low)
        if len(parts) > 1:
            out.extend(p for p in parts if p not in _STOP and len(p) > 1)
    return out


# --------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------

def _normalise(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.maximum(norms, 1e-12)


class BgeBackend:
    name = "bge"

    def __init__(self, model_name: str = BGE_MODEL) -> None:
        from fastembed import TextEmbedding  # raises ImportError if missing
        self.model_name = model_name
        self.model = TextEmbedding(model_name)  # raises if not downloadable

    def fit(self, texts: Sequence[str]) -> None:  # pre-trained, nothing to fit
        pass

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return _normalise(np.stack(list(self.model.embed(list(texts), batch_size=16))))

    def embed_query(self, text: str) -> np.ndarray:
        return _normalise(np.stack(list(self.model.embed([BGE_QUERY_PREFIX + text]))))[0]

    def save(self, store: str) -> None:
        pass

    @classmethod
    def load(cls, store: str, info: Dict) -> "BgeBackend":
        return cls(info.get("model", BGE_MODEL))


class LsaBackend:
    name = "lsa"

    def __init__(self, dim: int = LSA_DIM) -> None:
        self.dim = dim
        self.model_name = f"tfidf+svd({dim})"
        self.vectorizer = None
        self.svd = None

    def fit(self, texts: Sequence[str]) -> None:
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vectorizer = TfidfVectorizer(tokenizer=code_tokens, lowercase=False,
                                          token_pattern=None, sublinear_tf=True,
                                          min_df=1, max_df=0.6)
        x = self.vectorizer.fit_transform(texts)
        dim = min(self.dim, x.shape[0] - 1, x.shape[1] - 1)
        self.svd = TruncatedSVD(n_components=dim, random_state=0)
        self.svd.fit(x)
        self.dim = dim
        self.model_name = f"tfidf+svd({dim})"

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return _normalise(self.svd.transform(self.vectorizer.transform(texts)))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]

    def save(self, store: str) -> None:
        # the tokenizer function is not pickled (it would be bound to
        # __main__ when run as a script); it is re-attached on load
        self.vectorizer.tokenizer = None
        try:
            with open(os.path.join(store, "lsa.pkl"), "wb") as fh:
                pickle.dump({"vectorizer": self.vectorizer, "svd": self.svd,
                             "dim": self.dim}, fh)
        finally:
            self.vectorizer.tokenizer = code_tokens

    @classmethod
    def load(cls, store: str, info: Dict) -> "LsaBackend":
        with open(os.path.join(store, "lsa.pkl"), "rb") as fh:
            d = pickle.load(fh)
        b = cls(d["dim"])
        b.vectorizer, b.svd = d["vectorizer"], d["svd"]
        b.vectorizer.tokenizer = code_tokens
        b.model_name = info.get("model", b.model_name)
        return b


BACKENDS = {"bge": BgeBackend, "lsa": LsaBackend}


def make_backend(name: str):
    if name == "lsa":
        return LsaBackend()
    try:
        return BgeBackend()
    except Exception as exc:  # no fastembed or model not downloadable
        print(f"[embedder] bge backend unavailable ({type(exc).__name__}: "
              f"{str(exc)[:120]}) -> falling back to lsa", file=sys.stderr)
        return LsaBackend()


# --------------------------------------------------------------------------
# Vector store
# --------------------------------------------------------------------------

class VectorStore:
    """Chunk-embedding pairs + exact cosine retrieval."""

    def __init__(self, backend, vectors: np.ndarray, rows: List[Dict],
                 chunks_path: Optional[str] = None) -> None:
        self.backend = backend
        self.vectors = vectors          # N x d, L2-normalised
        self.rows = rows                # metadata per row
        self.chunks_path = chunks_path
        self._chunks: Optional[Dict[str, Dict]] = None

    # ---- build / persist ------------------------------------------------
    @classmethod
    def build(cls, chunks_path: str, backend_name: str = "bge") -> "VectorStore":
        with open(chunks_path, encoding="utf-8") as fh:
            chunks = json.load(fh)["chunks"]
        texts = [chunk_to_text(c) for c in chunks]
        backend = make_backend(backend_name)
        backend.fit(texts)
        vectors = backend.embed_documents(texts)
        rows = [{"id": c["id"], "file": c["file"], "start_line": c["start_line"],
                 "end_line": c["end_line"], "kind": c["kind"],
                 "symbols": c["symbols"], "is_test": c["is_test"],
                 "n_tokens": c["n_tokens"]} for c in chunks]
        return cls(backend, vectors, rows, chunks_path)

    def save(self, store: str) -> None:
        os.makedirs(store, exist_ok=True)
        np.save(os.path.join(store, "vectors.npy"), self.vectors)
        self.backend.save(store)
        with open(self.chunks_path, "rb") as fh:
            sha = hashlib.sha1(fh.read()).hexdigest()
        info = {"backend": self.backend.name, "model": self.backend.model_name,
                "dim": int(self.vectors.shape[1]), "n": int(self.vectors.shape[0]),
                "normalised": True, "similarity": "cosine",
                "chunks_file": os.path.basename(self.chunks_path),
                "chunks_sha1": sha, "rows": self.rows}
        with open(os.path.join(store, "index.json"), "w", encoding="utf-8") as fh:
            json.dump(info, fh, indent=1, ensure_ascii=False)

    @classmethod
    def load(cls, store: str = DEFAULT_STORE,
             chunks_path: Optional[str] = None) -> "VectorStore":
        with open(os.path.join(store, "index.json"), encoding="utf-8") as fh:
            info = json.load(fh)
        backend = BACKENDS[info["backend"]].load(store, info)
        vectors = np.load(os.path.join(store, "vectors.npy"))
        chunks_path = chunks_path or os.path.join(os.path.dirname(
            os.path.abspath(store)), info["chunks_file"])
        return cls(backend, vectors, info["rows"], chunks_path)

    # ---- retrieval -------------------------------------------------------
    def chunk(self, chunk_id: str) -> Dict:
        """Full chunk record (with code) from chunks.json."""
        if self._chunks is None:
            with open(self.chunks_path, encoding="utf-8") as fh:
                self._chunks = {c["id"]: c for c in json.load(fh)["chunks"]}
        return self._chunks[chunk_id]

    def search(self, query: str, k: int = 5, include_tests: bool = True,
               file_prefix: Optional[str] = None) -> List[Dict]:
        """Top-k chunks by cosine similarity. Returns row metadata + score."""
        q = self.backend.embed_query(query)
        scores = self.vectors @ q
        mask = np.ones(len(self.rows), dtype=bool)
        if not include_tests:
            mask &= ~np.array([r["is_test"] for r in self.rows])
        if file_prefix:
            mask &= np.array([r["file"].startswith(file_prefix) for r in self.rows])
        scores = np.where(mask, scores, -np.inf)
        k = min(k, int(mask.sum()))
        top = np.argpartition(-scores, k - 1)[:k] if k else []
        top = sorted(top, key=lambda i: -scores[i])
        return [dict(self.rows[i], score=float(scores[i])) for i in top]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Embed chunks and search them.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="embed chunks.json and save the store")
    b.add_argument("--chunks", default=DEFAULT_CHUNKS)
    b.add_argument("--out", default=DEFAULT_STORE)
    b.add_argument("--backend", choices=["bge", "lsa"], default="bge")
    s = sub.add_parser("search", help="retrieve chunks for a query")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=5)
    s.add_argument("--store", default=DEFAULT_STORE)
    s.add_argument("--no-tests", action="store_true")
    s.add_argument("--show", action="store_true", help="print the code too")
    args = ap.parse_args(argv)

    if args.cmd == "build":
        store = VectorStore.build(args.chunks, args.backend)
        store.save(args.out)
        print(f"{store.vectors.shape[0]} chunks embedded with "
              f"{store.backend.name} [{store.backend.model_name}], "
              f"dim={store.vectors.shape[1]} -> {args.out}")
    else:
        store = VectorStore.load(args.store)
        for r in store.search(args.query, args.k, include_tests=not args.no_tests):
            print(f"{r['score']:.3f}  {r['file']}:{r['start_line']}-{r['end_line']}"
                  f"  {', '.join(r['symbols'][:4])}{' ...' if len(r['symbols']) > 4 else ''}")
            if args.show:
                print(store.chunk(r["id"])["content"], "\n" + "-" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
