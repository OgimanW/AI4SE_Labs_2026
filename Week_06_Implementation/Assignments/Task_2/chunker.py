#!/usr/bin/env python3
"""
chunker.py - split a code repository into retrieval chunks for a RAG agent.

Strategy (see REPORT.md for the reasoning):
  * Python files are split along their syntax tree (``ast``), so a chunk is
    always a whole function, a whole class, a group of whole methods, or a
    block of module-level code (imports, constants, ``__all__``...).
  * A class that fits into the token budget stays in one chunk. A bigger
    class is split into groups of consecutive methods; every such chunk gets
    the class signature + docstring as a context header, so it is still clear
    which class the methods belong to.
  * Small sibling units (tiny functions, short test methods) are greedily
    packed together up to TARGET_TOKENS so we don't end up with hundreds of
    3-line chunks.
  * A single unit larger than MAX_TOKENS (rare: a huge function) falls back
    to a line window with overlap.
  * Non-Python text files (README, configs...) use the line-window splitter.

Output: a JSON file with a list of chunk records (see ``Chunk``).

Usage:
    python chunker.py [REPO_PATH] [-o chunks.json] [--target 384] [--max 512]
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Callable, List, Optional, Sequence

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

TARGET_TOKENS = 384      # packing stops once a chunk would exceed this
MAX_TOKENS = 512         # hard limit for one chunk (embedding-model friendly)
WINDOW_OVERLAP_LINES = 5 # overlap for the line-window fallback

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "env", "node_modules",
             ".mypy_cache", ".pytest_cache", ".idea", ".vscode", "build",
             "dist", ".dist", ".tox", ".eggs"}
SKIP_FILES = {".gitignore", ".gitattributes"}
CODE_EXT = {".py"}
TEXT_EXT = {".md", ".rst", ".txt", ".toml", ".cfg", ".ini", ".yml", ".yaml",
            ".json"}


# --------------------------------------------------------------------------
# Token counting (tiktoken if available, otherwise a chars/4 estimate)
# --------------------------------------------------------------------------

def _make_counter() -> tuple[Callable[[str], int], str]:
    try:
        import tiktoken  # type: ignore
        enc = tiktoken.get_encoding("cl100k_base")
        return (lambda s: len(enc.encode(s))), "tiktoken/cl100k_base"
    except Exception:
        return (lambda s: max(1, round(len(s) / 4))), "estimate(chars/4)"


count_tokens, TOKENIZER_NAME = _make_counter()


# --------------------------------------------------------------------------
# Data structure
# --------------------------------------------------------------------------

@dataclass
class Chunk:
    id: str                 # stable id: <file>::<symbol>::<start>-<end>
    file: str               # path relative to repo root (posix style)
    start_line: int         # 1-based, inclusive
    end_line: int           # 1-based, inclusive
    kind: str               # module | function | class | methods | window | text
    symbols: List[str]      # qualified names contained, e.g. ["Money.__add__"]
    parent: Optional[str]   # enclosing class for "methods" chunks
    is_test: bool           # chunk comes from a test file
    context: str            # short header (file, class signature, docstring)
    content: str            # the raw source lines of the chunk
    n_tokens: int           # tokens of context + content
    file_imports: List[str] = field(default_factory=list)

    @property
    def embed_text(self) -> str:
        """Text to embed / show to the LLM: header + code."""
        return f"{self.context}\n{self.content}"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

@dataclass
class Unit:
    """An indivisible piece of source (before packing)."""
    start: int              # 1-based inclusive
    end: int                # 1-based inclusive
    kind: str
    symbols: List[str]
    node: Optional[ast.AST] = None


def _node_start(node: ast.AST) -> int:
    """First line of a node including its decorators."""
    decos = getattr(node, "decorator_list", None) or []
    return min([node.lineno] + [d.lineno for d in decos])  # type: ignore[attr-defined]


def _slice(lines: Sequence[str], start: int, end: int) -> str:
    return "".join(lines[start - 1:end]).rstrip("\n")


def _tok(ctx: str, lines: Sequence[str], start: int, end: int) -> int:
    """Tokens of the final embed text (context header + code)."""
    return count_tokens(f"{ctx}\n{_slice(lines, start, end)}")


def _make_id(rel: str, symbols: List[str], start: int, end: int) -> str:
    sym = symbols[0] if len(symbols) == 1 else (
        f"{symbols[0]}..{symbols[-1]}" if symbols else "_")
    return f"{rel}::{sym}::{start}-{end}"


def _is_test_file(rel: str) -> bool:
    base = os.path.basename(rel)
    return (base.startswith("test_") or base.endswith("_test.py")
            or "/tests/" in f"/{rel}")


def _file_imports(tree: ast.Module) -> List[str]:
    out = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            out += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mod = "." * node.level + (node.module or "")
            out += [f"{mod}.{a.name}" if mod else a.name for a in node.names]
    return out


def _header(rel: str, extra: str = "") -> str:
    h = f"# File: {rel}"
    return h + (f"\n{extra}" if extra else "")


# --------------------------------------------------------------------------
# Python chunking
# --------------------------------------------------------------------------

def _top_level_units(tree: ast.Module) -> List[Unit]:
    """Turn module body into units: defs stay alone, other statements are
    grouped into consecutive 'module' blocks."""
    units: List[Unit] = []
    pending: List[ast.stmt] = []

    def flush() -> None:
        if pending:
            units.append(Unit(pending[0].lineno, pending[-1].end_lineno,  # type: ignore[arg-type]
                              "module", ["<module>"]))
            pending.clear()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            flush()
            units.append(Unit(_node_start(node), node.end_lineno,  # type: ignore[arg-type]
                              "function", [node.name], node))
        elif isinstance(node, ast.ClassDef):
            flush()
            units.append(Unit(_node_start(node), node.end_lineno,  # type: ignore[arg-type]
                              "class", [node.name], node))
        else:
            pending.append(node)
    flush()
    return units


def _class_header_end(cls: ast.ClassDef) -> int:
    """Last line of the class 'header': signature, docstring and class-level
    attributes before the first method."""
    end = cls.lineno
    for stmt in cls.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            break
        end = stmt.end_lineno  # type: ignore[assignment]
    return end


def _class_member_units(cls: ast.ClassDef, header_end: int) -> List[Unit]:
    units: List[Unit] = []
    for stmt in cls.body:
        if stmt.end_lineno <= header_end:  # type: ignore[operator]
            continue
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            units.append(Unit(_node_start(stmt), stmt.end_lineno,  # type: ignore[arg-type]
                              "method", [f"{cls.name}.{stmt.name}"], stmt))
        else:  # stray class-level statement between methods
            units.append(Unit(stmt.lineno, stmt.end_lineno,  # type: ignore[arg-type]
                              "method", [f"{cls.name}.<attr>"], stmt))
    return units


def _window_split(lines: Sequence[str], start: int, end: int, ctx: str,
                  budget: int) -> List[tuple[int, int]]:
    """Split [start, end] into n roughly equal line windows (n = smallest
    number that fits the budget), consecutive windows overlap a few lines."""
    total = end - start + 1
    for n in range(1, total + 1):
        size = -(-(total + (n - 1) * WINDOW_OVERLAP_LINES) // n)  # ceil
        spans, s = [], start
        while True:
            e = min(end, s + size - 1)
            spans.append((s, e))
            if e >= end:
                break
            s = e + 1 - WINDOW_OVERLAP_LINES
        if all(_tok(ctx, lines, a, b) <= budget for a, b in spans):
            return spans
    return [(i, i) for i in range(start, end + 1)]  # pathological lines


def _pack(units: List[Unit], lines: Sequence[str], ctx: str,
          target: int) -> List[List[Unit]]:
    """Greedy packing of consecutive units into groups whose text stays
    within ``target`` tokens (a single unit may exceed it - handled later)."""
    groups: List[List[Unit]] = []
    cur: List[Unit] = []
    for u in units:
        if cur:
            cand = _tok(ctx, lines, cur[0].start, u.end)
            # module-level blocks are not mixed with defs (keeps imports apart)
            mixing = (u.kind == "module") != (cur[-1].kind == "module")
            if cand <= target and not mixing:
                cur.append(u)
                continue
            groups.append(cur)
        cur = [u]
    if cur:
        groups.append(cur)
    return groups


def chunk_python(rel: str, source: str, target: int, max_tokens: int) -> List[Chunk]:
    lines = source.splitlines(keepends=True)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return chunk_text(rel, source, max_tokens, kind="window")

    is_test = _is_test_file(rel)
    imports = _file_imports(tree)
    mod_doc = ast.get_docstring(tree)
    file_ctx = _header(rel, f"# Module: {mod_doc.splitlines()[0]}" if mod_doc else "")
    chunks: List[Chunk] = []

    def emit(start: int, end: int, kind: str, symbols: List[str],
             ctx: str, parent: Optional[str] = None) -> None:
        content = _slice(lines, start, end)
        if not content.strip():
            return
        chunks.append(Chunk(
            id=_make_id(rel, symbols, start, end), file=rel,
            start_line=start, end_line=end, kind=kind, symbols=symbols,
            parent=parent, is_test=is_test, context=ctx, content=content,
            n_tokens=count_tokens(f"{ctx}\n{content}"),
            file_imports=imports))

    def emit_group(group: List[Unit], ctx: str, parent: Optional[str]) -> None:
        start, end = group[0].start, group[-1].end
        syms = []
        for u in group:
            syms += u.symbols
            if u.kind == "class" and isinstance(u.node, ast.ClassDef):
                # a whole class chunk also lists its methods
                syms += [f"{u.node.name}.{m.name}" for m in u.node.body
                         if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if _tok(ctx, lines, start, end) <= max_tokens:
            kind = ("methods" if parent else
                    group[0].kind if len(group) == 1 else
                    "module" if group[0].kind == "module" else "functions")
            emit(start, end, kind, syms, ctx, parent)
            return
        # single oversized unit
        u = group[0]
        if u.kind == "class" and isinstance(u.node, ast.ClassDef):
            split_class(u.node, ctx)
            return
        part_ctx = ctx + f"\n# (part of {syms[0]}, lines {start}-{end})"
        for s, e in _window_split(lines, start, end, part_ctx, max_tokens):
            emit(s, e, "window", syms, part_ctx, parent)

    def split_class(cls: ast.ClassDef, outer_ctx: str) -> None:
        hdr_end = _class_header_end(cls)
        start = _node_start(cls)
        sig = lines[cls.lineno - 1].strip()
        doc = ast.get_docstring(cls)
        ctx = outer_ctx + f"\n# Class: {sig}" + (
            f"  # {doc.splitlines()[0]}" if doc else "")
        # the header (signature + docstring + class attributes) is packed as
        # the first unit, so it lands in the same chunk as the first methods
        members = [Unit(start, hdr_end, "method", [cls.name])]
        members += _class_member_units(cls, hdr_end)
        for group in _pack(members, lines, ctx, target):
            emit_group(group, ctx, cls.name)

    for group in _pack(_top_level_units(tree), lines, file_ctx, target):
        emit_group(group, file_ctx, None)
    return chunks


# --------------------------------------------------------------------------
# Plain-text chunking
# --------------------------------------------------------------------------

def chunk_text(rel: str, source: str, max_tokens: int, kind: str = "text") -> List[Chunk]:
    lines = source.splitlines(keepends=True)
    if not lines:
        return []
    ctx = _header(rel)
    out = []
    for s, e in _window_split(lines, 1, len(lines), ctx, max_tokens):
        content = _slice(lines, s, e)
        if content.strip():
            out.append(Chunk(
                id=_make_id(rel, [], s, e), file=rel, start_line=s, end_line=e,
                kind=kind, symbols=[], parent=None, is_test=_is_test_file(rel),
                context=ctx, content=content,
                n_tokens=count_tokens(f"{ctx}\n{content}")))
    return out


# --------------------------------------------------------------------------
# Repository walk
# --------------------------------------------------------------------------

def iter_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if name in SKIP_FILES:
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in CODE_EXT or ext in TEXT_EXT:
                yield os.path.join(dirpath, name)


def chunk_repository(root: str, target: int = TARGET_TOKENS,
                     max_tokens: int = MAX_TOKENS) -> List[Chunk]:
    chunks: List[Chunk] = []
    for path in iter_files(root):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        with open(path, encoding="utf-8", errors="replace") as fh:
            source = fh.read()
        if not source.strip():
            continue
        if path.endswith(".py"):
            chunks.extend(chunk_python(rel, source, target, max_tokens))
        else:
            chunks.extend(chunk_text(rel, source, max_tokens))
    return chunks


def save_chunks(chunks: List[Chunk], out_path: str, root: str,
                target: int, max_tokens: int) -> None:
    digest = hashlib.sha1("".join(c.content for c in chunks).encode()).hexdigest()
    payload = {
        "meta": {
            "repo": os.path.basename(os.path.abspath(root)),
            "n_chunks": len(chunks),
            "n_files": len({c.file for c in chunks}),
            "tokenizer": TOKENIZER_NAME,
            "target_tokens": target,
            "max_tokens": max_tokens,
            "content_sha1": digest,
        },
        "chunks": [dict(asdict(c), embed_text=c.embed_text) for c in chunks],
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)


def load_chunks(path: str) -> List[Chunk]:
    """Load chunks back (for the retrieval step of the agent)."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return [Chunk(**{k: v for k, v in d.items() if k != "embed_text"})
            for d in data["chunks"]]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("repo", nargs="?",
                    default=os.path.join(here, "..", "AI4SE_Playground"),
                    help="path to the repository (default: ../AI4SE_Playground)")
    ap.add_argument("-o", "--out", default=os.path.join(here, "chunks.json"))
    ap.add_argument("--target", type=int, default=TARGET_TOKENS)
    ap.add_argument("--max", type=int, default=MAX_TOKENS, dest="max_tokens")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.repo):
        print(f"repository not found: {args.repo}", file=sys.stderr)
        return 1
    chunks = chunk_repository(args.repo, args.target, args.max_tokens)
    save_chunks(chunks, args.out, args.repo, args.target, args.max_tokens)

    sizes = sorted(c.n_tokens for c in chunks)
    kinds: dict[str, int] = {}
    for c in chunks:
        kinds[c.kind] = kinds.get(c.kind, 0) + 1
    print(f"{len(chunks)} chunks from {len({c.file for c in chunks})} files "
          f"-> {args.out}")
    print(f"tokens ({TOKENIZER_NAME}): min {sizes[0]}, median "
          f"{sizes[len(sizes)//2]}, mean {sum(sizes)//len(sizes)}, max {sizes[-1]}")
    print("kinds:", ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
