# Task 2 – Chunking the repository for RAG

**Repository:** `AI4SE_Playground` (Python package `playground` + `unittest` tests)
**Files:** `chunker.py` (script), `chunks.json` (output), this report.
**Run:** `python chunker.py [path/to/repo] [-o chunks.json] [--target 384] [--max 512]`

## 1. What the repository looks like

| | |
|---|---|
| Python files | 28 (13 source, 15 test) |
| Total size | ~4 600 lines, ~40 k tokens |
| Functions / methods | 698, median ≈ 42 tokens, 95th percentile ≈ 114, max ≈ 470 |
| Classes | 103, median ≈ 300 tokens, max ≈ 1 500; 79 of 103 fit into 512 tokens |

The code is small, well structured and heavily object-oriented. Almost all of the
logic lives in classes and short methods with docstrings, and every source module
has a matching `test_<module>.py`.

## 2. Splitting method: AST-aware chunks

Fixed-size splitting (every *N* characters or lines) would cut methods in half and
separate a method from the class it belongs to. A coding agent needs complete
code units it can read and edit, so the chunker splits along Python's syntax tree
(`ast` module):

1. **Top level.** Every top-level function and class is a unit. Consecutive
   non-definition statements (module docstring, imports, constants, `__all__`)
   are grouped into one `module` unit.
2. **Classes.** If a whole class fits into the budget, it stays as **one chunk**.
   This is the most common case and gives the best context. If it doesn't fit,
   the class is split into **groups of consecutive whole methods**. The class
   signature, docstring and class attributes go into the first group.
3. **Packing.** Small sibling units (tiny helpers, 3-line test methods) are
   packed greedily into one chunk until it reaches `TARGET_TOKENS`. Without
   this, the test files would produce hundreds of near-useless micro-chunks.
   Imports/module code is never mixed with definitions.
4. **Fallback.** A single unit that still exceeds `MAX_TOKENS` (here only
   `Simulation.step`) is split into evenly sized line windows with a 5-line
   overlap. Other text files (README, configs) use the same line-window splitter.
5. **Context header.** Every chunk has a `context` string that is prepended
   before embedding. It holds the file path, the module docstring and, for
   method groups, the enclosing class signature and its docstring, e.g.
   `# File: playground/playground/models.py` / `# Class: class Money:`.
   This way a chunk like `__sub__` still "knows" it is `Money.__sub__`.

`.gitignore`, empty files and build, cache or VCS directories are skipped.

## 3. Chunk size: target 384, hard max 512 tokens

* **Embedding models.** Many common embedding models accept 512 input
  tokens at most (e.g. BERT/MiniLM-family sentence-transformers). Anything longer is
  silently truncated, so 512 is a natural hard ceiling.
* **Fits the code's natural units.** 95 % of methods are under ~115 tokens,
  and the median class is ~300 tokens. With 512, about 77 % of classes stay whole,
  and only one function in the whole repo needs to be cut.
* **Retrieval precision vs. context.** Much larger chunks (e.g. a whole file,
  ~1–2 k tokens) would mix unrelated classes and weaken the similarity signal.
  Much smaller ones (one method each) lose the surrounding class and make the agent
  retrieve many fragments. A packing target of 384 leaves room for the context
  header while keeping each chunk "about one thing".
* **Prompt budget.** With ~250 tokens per chunk on average, top-k = 8–10
  retrieved chunks fit in ~2.5 k tokens of the agent's prompt. That leaves
  plenty of room for the task and the model's answer.

Tokens are counted with `tiktoken` (`cl100k_base`) when it is available. Otherwise
the script estimates them as characters / 4. The JSON records which one was used.

## 4. Result

`chunks.json` has 175 chunks from 26 non-empty files. Sizes: min 32, median 287,
mean 256, max 502 tokens. By kind: 53 whole classes, 69 method groups, 39 module
blocks, 12 function groups, 2 windows. 123 chunks come from tests and 52 from source.
A check confirmed that **every non-blank line of the repository is in at
least one chunk**.

## 5. Data structure

`chunks.json` = `{ "meta": {...}, "chunks": [ ... ] }`. Each chunk record:

| field | meaning |
|---|---|
| `id` | stable id `file::symbol::start-end` |
| `file`, `start_line`, `end_line` | exact location, so the agent can open or patch the original file |
| `kind` | `module`, `class`, `methods`, `functions`, `window`, `text` |
| `symbols`, `parent` | qualified names inside the chunk (`Money.__add__`; a whole-class chunk also lists all its methods) and the enclosing class |
| `is_test` | lets the agent filter or boost test code (e.g. "find the tests for X") |
| `file_imports` | the file's imports, to help follow dependencies between modules |
| `context`, `content`, `embed_text` | header, raw code, and header + code (the text to embed) |
| `n_tokens` | size of `embed_text` |

`load_chunks()` in `chunker.py` reads the file back into `Chunk` objects for the
next step (embedding + retrieval).
