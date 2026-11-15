#!/usr/bin/env python3
"""
solver.py - solve programming tasks with the RAG pipeline (Tasks 2-4).

For every task:
  1. take the textual task (what to implement)
  2. retrieve the top 5 chunks from the vector store (matcher.py)
  3. send a prompt with the task + the chunks to an LLM (OpenAI API)
  4. write the returned method into the target source file
     (the stub is located with `ast` and replaced; the file must still parse)

Then the repository's unit tests are run and a report is written.

Usage:
  python solver.py --tasks path/to/missing_code.json [--model gpt-5-mini]
  python solver.py --task "Implement Customer.can_afford ..." --file playground/models.py \
                   --cls Customer --method can_afford
  python solver.py --restore          # put back the original files (.orig backups)
  python solver.py --tests-only       # just run the unit tests

Needs:  pip install openai   and the OPENAI_API_KEY environment variable
        (or a .env file next to this script / in the current directory).
        OPENAI_BASE_URL is respected if your course uses a proxy endpoint.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from matcher import Matcher  # noqa: E402

DEFAULT_REPO = os.path.normpath(os.path.join(HERE, "..", "AI4SE_Playground", "playground"))
ALLOWED_MODELS = ["gpt-6-luna", "gpt-5.6-luna", "gpt-5.4-nano", "gpt-5-nano",
                  "gpt-5-mini", "gpt-4.1-nano", "gpt-4o-mini"]
DEFAULT_MODEL = "gpt-5-mini"
TOP_K = 5
RESULTS_DIR = os.path.join(HERE, "results")


# ---------------------------------------------------------------------------
# Task definition
# ---------------------------------------------------------------------------

@dataclass
class Task:
    file: str            # path relative to the repo root, e.g. playground/models.py
    cls: Optional[str]   # class name (None for a module-level function)
    method: str          # method / function name
    description: str     # what the method must do

    @property
    def target(self) -> str:
        return f"{self.cls}.{self.method}" if self.cls else self.method


def _pick(d: Dict, *names: str) -> Optional[str]:
    low = {k.lower(): v for k, v in d.items()}
    for n in names:
        if n in low and low[n] not in (None, ""):
            return str(low[n])
    return None


def load_tasks(path: str) -> List[Task]:
    """Read missing_code.json. Accepts a list of objects, or an object with a
    list under some key ('tasks', 'missing', ...), with common field names."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        data = lists[0] if lists else [data]
    tasks = []
    for i, d in enumerate(data):
        file = _pick(d, "file", "path", "file_path", "filepath", "source_file", "module")
        cls = _pick(d, "class", "class_name", "classname", "cls")
        method = _pick(d, "method", "method_name", "function", "function_name", "name")
        desc = _pick(d, "description", "summary", "task", "prompt", "spec",
                     "docstring", "what", "details")
        if method and "." in method and not cls:
            cls, method = method.rsplit(".", 1)
        if not (file and method and desc):
            raise ValueError(f"task #{i} in {path}: can't find file/method/description "
                             f"in keys {list(d.keys())}")
        tasks.append(Task(file.replace("\\", "/"), cls, method, desc))
    return tasks


# ---------------------------------------------------------------------------
# Locating and replacing the target method
# ---------------------------------------------------------------------------

def resolve_file(repo: str, rel: str) -> str:
    """Find the file even if the JSON path has a different prefix."""
    rel = rel.lstrip("./")
    cands = [os.path.join(repo, rel), os.path.join(os.path.dirname(repo), rel)]
    for c in cands:
        if os.path.isfile(c):
            return c
    base = os.path.basename(rel)
    hits = [os.path.join(dp, base) for dp, _, fs in os.walk(repo) if base in fs
            and "tests" not in dp.replace("\\", "/").split("/")]
    if len(hits) == 1:
        return hits[0]
    raise FileNotFoundError(f"target file not found: {rel}")


def find_def(tree: ast.Module, cls: Optional[str], name: str):
    scope = tree.body
    if cls:
        node = next((n for n in ast.walk(tree)
                     if isinstance(n, ast.ClassDef) and n.name == cls), None)
        if node is None:
            raise LookupError(f"class {cls} not found")
        scope = node.body
    for n in scope:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise LookupError(f"{cls + '.' if cls else ''}{name} not found")


def def_span(node) -> tuple[int, int]:
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    return start, node.end_lineno


def current_source(path: str, task: Task) -> str:
    src = open(path, encoding="utf-8").read()
    node = find_def(ast.parse(src), task.cls, task.method)
    s, e = def_span(node)
    return "".join(src.splitlines(keepends=True)[s - 1:e])


def extract_code(reply: str) -> str:
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", reply, re.S)
    return (max(blocks, key=len) if blocks else reply).strip("\n")


def replace_method(path: str, task: Task, new_code: str) -> None:
    """Replace the method in the file with new_code (re-indented to the
    method's indentation). Raises if the result is not valid Python or the
    code does not define the expected method."""
    new_code = textwrap.dedent(new_code).strip("\n")
    parsed = ast.parse(new_code)               # SyntaxError -> caller retries
    defs = [n for n in parsed.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not defs or defs[0].name != task.method:
        raise ValueError(f"reply does not define `{task.method}`")
    src = open(path, encoding="utf-8").read()
    lines = src.splitlines(keepends=True)
    node = find_def(ast.parse(src), task.cls, task.method)
    s, e = def_span(node)
    indent = re.match(r"\s*", lines[s - 1]).group(0)
    body = "".join(indent + l if l.strip() else l
                   for l in new_code.splitlines(keepends=True))
    if not body.endswith("\n"):
        body += "\n"
    new_src = "".join(lines[:s - 1]) + body + "".join(lines[e:])
    ast.parse(new_src)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(new_src)


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert Python developer working inside an existing repository.
You implement exactly one method whose body is currently missing (`pass`).
Rules:
- Return ONLY the complete method definition (decorators, the `def` line with the
  unchanged signature, a short docstring, the body) in a single ```python block.
- Do not change the signature. Do not return the whole class or other methods.
- Use only names already imported in the target file, or import inside the method.
- Follow the conventions visible in the context: same validation style, exception
  types and exact error messages, private attribute names (e.g. self._balance).
- Unit tests shown in the context describe the expected behaviour - satisfy them."""


def build_prompt(task: Task, stub: str, file_imports: List[str], chunks) -> str:
    ctx = "\n\n".join(c.as_prompt() for c in chunks)
    imports = ", ".join(file_imports) if file_imports else "(see context)"
    where = f"class `{task.cls}` in `{task.file}`" if task.cls else f"`{task.file}`"
    return (f"## Task\nImplement `{task.target}` in {where}.\n\n{task.description}\n\n"
            f"## Current definition (to be replaced)\n```python\n{stub.rstrip()}\n```\n\n"
            f"Imports available in this file: {imports}\n\n"
            f"## Relevant code from the repository (retrieved, top {len(chunks)})\n{ctx}\n\n"
            f"Return only the implemented method `{task.method}` in one ```python block.")


def load_env() -> None:
    for p in (os.path.join(HERE, ".env"), os.path.join(os.getcwd(), ".env"),
              os.path.join(HERE, "..", ".env")):
        if os.path.isfile(p):
            for line in open(p, encoding="utf-8"):
                m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$", line)
                if m and m.group(1) not in os.environ:
                    os.environ[m.group(1)] = m.group(2).strip().strip('"').strip("'")


class LLM:
    def __init__(self, model: str) -> None:
        if model not in ALLOWED_MODELS:
            raise ValueError(f"model {model!r} not allowed; choose from {ALLOWED_MODELS}")
        load_env()
        from openai import OpenAI
        self.client = OpenAI()   # reads OPENAI_API_KEY (and OPENAI_BASE_URL)
        self.model = model
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def ask(self, messages: List[Dict[str, str]]) -> str:
        for attempt in range(3):
            try:
                r = self.client.chat.completions.create(model=self.model, messages=messages)
                if r.usage:
                    self.usage["prompt_tokens"] += r.usage.prompt_tokens or 0
                    self.usage["completion_tokens"] += r.usage.completion_tokens or 0
                return r.choices[0].message.content or ""
            except Exception as exc:  # rate limit / network: back off and retry
                if type(exc).__name__ in ("AuthenticationError", "PermissionDeniedError",
                                          "NotFoundError") or attempt == 2:
                    raise
                print(f"    API error ({type(exc).__name__}), retrying...")
                time.sleep(2 * (attempt + 1))
        return ""


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------

@dataclass
class TaskResult:
    target: str
    file: str
    status: str = "pending"          # written | failed
    retrieved: List[str] = field(default_factory=list)
    attempts: int = 0
    error: Optional[str] = None
    code: Optional[str] = None


def solve_task(task: Task, repo: str, matcher: Matcher, llm: LLM, k: int = TOP_K,
               max_attempts: int = 2) -> TaskResult:
    """task text -> top-k chunks -> LLM -> code written into the target file."""
    res = TaskResult(task.target, task.file)
    path = resolve_file(repo, task.file)
    backup = path + ".orig"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)

    query = f"{task.target}: {task.description}"
    chunks = matcher.match_text(query, n=k)
    res.retrieved = [c.id for c in chunks]
    stub = current_source(path, task)
    imports = matcher.store.chunk(chunks[0].id).get("file_imports", []) if chunks else []
    same_file = [c for c in chunks if path.replace("\\", "/").endswith(c.file)]
    if same_file:
        imports = matcher.store.chunk(same_file[0].id).get("file_imports", [])

    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(task, stub, imports, chunks)}]
    for attempt in range(1, max_attempts + 1):
        res.attempts = attempt
        reply = llm.ask(messages)
        code = extract_code(reply)
        try:
            replace_method(path, task, code)
            res.status, res.code, res.error = "written", code, None
            return res
        except (SyntaxError, ValueError, LookupError) as exc:
            res.error = f"{type(exc).__name__}: {exc}"
            messages += [{"role": "assistant", "content": reply},
                         {"role": "user", "content": f"That could not be used ({res.error}). "
                          f"Return only the method `{task.method}` as valid Python "
                          f"in one ```python block."}]
    res.status = "failed"
    return res


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

_LINE = re.compile(r"^(\w+) \(([\w.]+)\)(?:\s*\n?.*?)? \.\.\. (ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)\s*$")


def run_tests(repo: str) -> Dict:
    """Run `python -m unittest discover` in the repo; parse per-test results."""
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests",
                           "-t", ".", "-v"], cwd=repo, capture_output=True, text=True,
                          timeout=600)
    out = proc.stderr + proc.stdout
    per_class: Dict[str, Dict[str, int]] = {}
    failed: List[str] = []
    for line in out.splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        name, where, verdict = m.groups()
        cls = where[:-(len(name) + 1)] if where.endswith("." + name) else where
        cls = cls.replace("tests.", "", 1)
        d = per_class.setdefault(cls, {"passed": 0, "failed": 0})
        if verdict == "ok" or verdict.startswith("skipped") or verdict == "expected failure":
            d["passed"] += 1
        else:
            d["failed"] += 1
            failed.append(f"{cls}.{name}")
    ran = re.search(r"Ran (\d+) tests?", out)
    summary = re.search(r"^(OK.*|FAILED \(.*\))$", out, re.M)
    total = int(ran.group(1)) if ran else 0
    return {"total": total, "failed": len(set(failed)),
            "passed": total - len(set(failed)) if total else 0,
            "summary": summary.group(1) if summary else "?",
            "failed_tests": sorted(set(failed)), "per_class": per_class,
            "returncode": proc.returncode, "output": out}


def restore(repo: str) -> int:
    n = 0
    for dp, _, fs in os.walk(repo):
        for f in fs:
            if f.endswith(".py.orig"):
                shutil.move(os.path.join(dp, f), os.path.join(dp, f[:-5]))
                n += 1
    return n


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(model: str, before: Dict, after: Dict, results: List[TaskResult],
                 usage: Dict, path: str) -> None:
    def pct(d):
        return f"{100 * d['passed'] / d['total']:.1f} %" if d["total"] else "-"
    lines = [f"# RAG solver – unit test results\n",
             f"Model: **{model}**, retrieval: top {TOP_K} chunks, "
             f"tokens: {usage['prompt_tokens']} in / {usage['completion_tokens']} out\n",
             "| | tests | passed | failed | pass rate |", "|---|---|---|---|---|",
             f"| before (stubs) | {before['total']} | {before['passed']} | {before['failed']} | {pct(before)} |",
             f"| after RAG solver | {after['total']} | {after['passed']} | {after['failed']} | {pct(after)} |",
             "", "## Tasks", "", "| target | file | written | attempts |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| `{r.target}` | {r.file} | {'yes' if r.status == 'written' else 'NO – ' + (r.error or '')} | {r.attempts} |")
    lines += ["", "## Tests still failing", ""]
    lines += [f"- `{t}`" for t in after["failed_tests"]] or ["- none"]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Solve coding tasks with the RAG pipeline.")
    ap.add_argument("--tasks", help="missing_code.json")
    ap.add_argument("--task", help="a single textual task")
    ap.add_argument("--file"), ap.add_argument("--cls"), ap.add_argument("--method")
    ap.add_argument("--repo", default=DEFAULT_REPO, help="folder that contains tests/")
    ap.add_argument("--model", default=DEFAULT_MODEL, choices=ALLOWED_MODELS)
    ap.add_argument("-k", type=int, default=TOP_K)
    ap.add_argument("--restore", action="store_true", help="restore the original files")
    ap.add_argument("--tests-only", action="store_true")
    args = ap.parse_args(argv)

    if args.restore:
        print(f"restored {restore(args.repo)} file(s)")
        return 0
    if args.tests_only:
        t = run_tests(args.repo)
        print(f"{t['total']} tests: {t['passed']} passed, {t['failed']} failed  [{t['summary']}]")
        return 0

    if args.tasks:
        tasks = load_tasks(args.tasks)
    elif args.task and args.file and args.method:
        tasks = [Task(args.file, args.cls, args.method, args.task)]
    else:
        ap.error("give --tasks FILE, or --task TEXT --file F [--cls C] --method M")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    print(f"{len(tasks)} task(s), model {args.model}, repo {args.repo}")
    before = run_tests(args.repo)
    print(f"tests before: {before['passed']}/{before['total']} passed")

    matcher = Matcher()
    llm = LLM(args.model)
    results = []
    for i, task in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] {task.target} ({task.file})")
        try:
            r = solve_task(task, args.repo, matcher, llm, args.k)
        except Exception as exc:
            if type(exc).__name__ in ("AuthenticationError", "PermissionDeniedError"):
                print(f"    API rejected the credentials: {str(exc)[:160]}\n"
                      f"    -> check OPENAI_API_KEY / OPENAI_BASE_URL; stopping.")
                return 1
            r = TaskResult(task.target, task.file, "failed", error=f"{type(exc).__name__}: {exc}")
        print(f"    -> {r.status}" + (f" ({r.error})" if r.error and r.status != "written" else ""))
        results.append(r)

    after = run_tests(args.repo)
    print(f"tests after:  {after['passed']}/{after['total']} passed  [{after['summary']}]")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    with open(os.path.join(RESULTS_DIR, f"run_{stamp}.json"), "w", encoding="utf-8") as fh:
        json.dump({"model": args.model, "k": args.k, "usage": llm.usage,
                   "tasks": [asdict(r) for r in results],
                   "before": {k: v for k, v in before.items() if k != "output"},
                   "after": {k: v for k, v in after.items() if k != "output"}},
                  fh, indent=2, ensure_ascii=False)
    with open(os.path.join(RESULTS_DIR, f"tests_{stamp}.log"), "w", encoding="utf-8") as fh:
        fh.write(after["output"])
    report = os.path.join(RESULTS_DIR, "TEST_REPORT.md")
    write_report(args.model, before, after, results, llm.usage, report)
    print(f"report -> {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
