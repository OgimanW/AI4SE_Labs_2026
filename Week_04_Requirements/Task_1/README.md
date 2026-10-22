# Agentic requirements-refinement network (Task 1)

A LangGraph network that reads a directory of heterogeneous documents about a software
product (specs, emails, interviews, meeting minutes, surveys, ...) and produces one
structured requirements document. Design: see [DESIGN_REPORT.md](DESIGN_REPORT.md).

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env              # then put your key into .env: OPENAI_API_KEY=...
```

The API key is read only from the `OPENAI_API_KEY` environment variable (`.env` is git-ignored).

## Run

```powershell
python check_models.py                                          # optional: 1 test call per model
python main.py --input-dir data/corpus --output-dir output      # example corpus
python main.py --input-dir tests/synthetic_corpus/docs --output-dir tests/synthetic_corpus/output
```

Options: `--max-iterations N` (rework loops, default 2). Every node prints a progress line.
All supported files (`.txt .md .eml .pdf .docx .html`) below the input directory are processed.

## Outputs

| File | Content |
|---|---|
| `requirements.md` | the requirements document |
| `requirements.json` | the same content as data |
| `run_log.json` | nodes executed, models, LLM calls, token usage, findings per round |

## Layout

```
main.py                 CLI entry point
check_models.py         model availability / structured-output check
network/config.py       model per node, limits, priority scale
network/prompts.py      all prompts (domain-agnostic)
network/schemas.py      Pydantic models (LLM structured outputs)
network/state.py        graph state
network/graph.py        LangGraph assembly
network/llm.py          OpenAI client, retries, usage logging
network/loaders.py      file loaders and chunking
network/nodes/          loader, extractor, consolidator, writer, review (checks + critic), assembler
data/corpus/            example input corpus
output/                 network output for the example corpus
tests/synthetic_corpus/ generalization smoke test (docs/ + EXPECTED.md)
```
