"""Writer / Prioritizer (LLM, one call per batch): name, description, priority."""
from langgraph.types import Send

from .. import config
from ..llm import structured_call
from ..prompts import WRITER_SYSTEM, WRITER_USER
from ..schemas import Req, WriterResult
from .common import event, fmt_glossary, fmt_scale


def dispatch_writers(state) -> list[Send] | str:
    """Write every requirement whose content has no written form yet."""
    written = state.get("written", {})
    todo = [r for r in state.get("reqs", []) if r.signature not in written]
    size = config.WRITER_BATCH_SIZE
    return [Send("writer", {"items": todo[i:i + size], "candidates": state["candidates"],
                            "scope": state.get("scope_summary", ""),
                            "glossary": state.get("glossary", []),
                            "feedback": state.get("writer_feedback", {})})
            for i in range(0, len(todo), size)] or "checks"


def writer_node(payload: dict) -> dict:
    items: list[Req] = payload["items"]
    cands, feedback = payload["candidates"], payload["feedback"]
    lines = []
    for r in items:
        cues = sorted({cue for m in r.merged_from for cue in cands[m].priority_cues})
        evidence = " || ".join(cands[m].quote[:250] for m in r.merged_from[:4])
        note = f" | REVIEWER: {feedback[r.signature]}" if r.signature in feedback else ""
        lines.append(f"{r.ref} ({r.kind}) {r.statement} | {', '.join(cues) or '-'} | "
                     f"{evidence} | sources: {len(r.doc_ids)}{note}")
    user = WRITER_USER.format(scope=payload["scope"], glossary=fmt_glossary(payload["glossary"]),
                              items="\n".join(lines))
    result, rec = structured_call("writer", WriterResult,
                                  WRITER_SYSTEM.format(scale=fmt_scale()), user)
    by_ref = {r.ref: r for r in items}
    written = {}
    for w in (result.requirements if result else []):
        if (r := by_ref.get(w.ref)) is not None:
            written[r.signature] = r.model_copy(update=w.model_dump(exclude={"ref"}))
    return {"written": written,
            "log": [rec, event("writer", items=len(items), written=len(written))]}
