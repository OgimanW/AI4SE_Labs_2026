#!/usr/bin/env python3
"""
matcher.py - match an input-task embedding against the stored chunk
embeddings (Task 3) and return the n most relevant chunks.

Core:   Matcher.match(query_vec, n)          -> list of Match
Helper: Matcher.match_text(task_text, n)     -> embeds the task first

Steps of one match (see REPORT_matching.md):
  1. normalise the query vector (stored vectors are already L2-normalised)
  2. cosine similarity with every chunk = one matrix-vector product
  3. optional filters: drop tests, restrict to a path prefix, min score
  4. select candidates with argpartition (O(N)), sort only those
  5. optional MMR re-ranking to avoid returning near-duplicate chunks
  6. drop chunks whose line range overlaps an already chosen chunk of the
     same file (window chunks overlap by design)

Usage:
  python matcher.py "Customers must not exceed their credit limit" -n 5
  python matcher.py "..." -n 5 --no-tests --mmr 0.7 --min-score 0.2 --show
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from embedder import DEFAULT_STORE, VectorStore  # noqa: E402


@dataclass
class Match:
    rank: int
    score: float          # cosine similarity to the query (-1 .. 1)
    id: str
    file: str
    start_line: int
    end_line: int
    symbols: List[str]
    is_test: bool
    content: str          # source code of the chunk
    context: str          # header (file / class) of the chunk

    def as_prompt(self) -> str:
        """Ready-to-paste block for the agent's prompt."""
        return (f"### {self.file} (lines {self.start_line}-{self.end_line})\n"
                f"```python\n{self.content}\n```")


class Matcher:
    def __init__(self, store: Optional[VectorStore] = None,
                 store_path: str = DEFAULT_STORE) -> None:
        self.store = store or VectorStore.load(store_path)
        self.vectors = self.store.vectors            # N x d, L2-normalised
        self.rows = self.store.rows
        self._is_test = np.array([r["is_test"] for r in self.rows], dtype=bool)
        self._files = np.array([r["file"] for r in self.rows])

    @property
    def dim(self) -> int:
        return int(self.vectors.shape[1])

    # ------------------------------------------------------------------
    def embed_task(self, task_text: str) -> np.ndarray:
        """Embed a task description with the same backend as the store."""
        return self.store.backend.embed_query(task_text)

    def match_text(self, task_text: str, n: int = 5, **kw) -> List[Match]:
        return self.match(self.embed_task(task_text), n, **kw)

    def match(self, query_vec: np.ndarray, n: int = 5, *,
              include_tests: bool = True, file_prefix: Optional[str] = None,
              min_score: Optional[float] = None, mmr_lambda: Optional[float] = None,
              candidates: int = 4) -> List[Match]:
        """Return the n chunks most similar to ``query_vec``.

        include_tests  False -> only source chunks
        file_prefix    only chunks whose file starts with this prefix
        min_score      drop chunks with cosine below this value
        mmr_lambda     None = pure similarity ranking; 0..1 = MMR trade-off
                       (1.0 = relevance only, lower = more diversity)
        candidates     size of the candidate pool = candidates * n
        """
        q = np.asarray(query_vec, dtype=np.float32).ravel()
        if q.shape[0] != self.dim:
            raise ValueError(f"query has dim {q.shape[0]}, store has dim {self.dim} "
                             f"(was it embedded with the same backend?)")
        norm = np.linalg.norm(q)
        if norm == 0:
            return []
        q = q / norm

        scores = self.vectors @ q                        # cosine similarity

        mask = np.ones(len(scores), dtype=bool)
        if not include_tests:
            mask &= ~self._is_test
        if file_prefix:
            mask &= np.char.startswith(self._files, file_prefix)
        if min_score is not None:
            mask &= scores >= min_score
        valid = np.flatnonzero(mask)
        if valid.size == 0 or n <= 0:
            return []

        # candidate pool: top (candidates * n) by similarity, O(N) selection
        pool = min(valid.size, max(n, candidates * n))
        part = np.argpartition(-scores[valid], pool - 1)[:pool]
        pool_idx = valid[part][np.argsort(-scores[valid][part])]

        order = (self._mmr(pool_idx, scores, mmr_lambda)
                 if mmr_lambda is not None else list(pool_idx))

        chosen: List[int] = []
        for i in order:
            if self._overlaps(i, chosen):
                continue
            chosen.append(i)
            if len(chosen) == n:
                break
        return [self._to_match(rank + 1, i, float(scores[i]))
                for rank, i in enumerate(chosen)]

    # ------------------------------------------------------------------
    def _mmr(self, pool: np.ndarray, scores: np.ndarray, lam: float) -> List[int]:
        """Maximal Marginal Relevance: pick items that are relevant to the
        query but not too similar to the items already picked."""
        sims = self.vectors[pool] @ self.vectors[pool].T
        picked: List[int] = []
        left = list(range(len(pool)))
        while left:
            if picked:
                redundancy = sims[np.ix_(left, picked)].max(axis=1)
            else:
                redundancy = np.zeros(len(left))
            mmr = lam * scores[pool[left]] - (1 - lam) * redundancy
            best = left[int(np.argmax(mmr))]
            picked.append(best)
            left.remove(best)
        return [int(pool[i]) for i in picked]

    def _overlaps(self, i: int, chosen: List[int]) -> bool:
        r = self.rows[i]
        for j in chosen:
            o = self.rows[j]
            if (o["file"] == r["file"] and r["start_line"] <= o["end_line"]
                    and o["start_line"] <= r["end_line"]):
                return True
        return False

    def _to_match(self, rank: int, i: int, score: float) -> Match:
        r = self.rows[i]
        c = self.store.chunk(r["id"])
        return Match(rank=rank, score=score, id=r["id"], file=r["file"],
                     start_line=r["start_line"], end_line=r["end_line"],
                     symbols=r["symbols"], is_test=r["is_test"],
                     content=c["content"], context=c["context"])


# ----------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Retrieve the n most relevant chunks for a task.")
    ap.add_argument("task", help="task description (it is embedded, then matched)")
    ap.add_argument("-n", type=int, default=5)
    ap.add_argument("--store", default=DEFAULT_STORE)
    ap.add_argument("--no-tests", action="store_true")
    ap.add_argument("--path", default=None, help="only files starting with this prefix")
    ap.add_argument("--min-score", type=float, default=None)
    ap.add_argument("--mmr", type=float, default=None, metavar="LAMBDA",
                    help="MMR re-ranking, e.g. 0.7")
    ap.add_argument("--show", action="store_true", help="print the code of each match")
    args = ap.parse_args(argv)

    m = Matcher(store_path=args.store)
    print(f"store: {m.store.backend.name} [{m.store.backend.model_name}], "
          f"{len(m.rows)} chunks, dim={m.dim}")
    res = m.match_text(args.task, args.n, include_tests=not args.no_tests,
                       file_prefix=args.path, min_score=args.min_score,
                       mmr_lambda=args.mmr)
    for r in res:
        syms = ", ".join(r.symbols[:4]) + (" ..." if len(r.symbols) > 4 else "")
        print(f"{r.rank}. {r.score:.3f}  {r.file}:{r.start_line}-{r.end_line}  {syms}")
        if args.show:
            print(r.as_prompt() + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
