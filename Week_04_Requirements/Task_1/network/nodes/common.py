"""Shared helpers."""
import re
import time
from typing import Any

from .. import config
from ..schemas import GlossaryTerm, Req


def event(node: str, **info: Any) -> dict[str, Any]:
    """Run-log entry for one node execution."""
    return {"type": "node", "node": node, "time": round(time.time(), 2), **info}


def fmt_glossary(glossary: list[GlossaryTerm]) -> str:
    return "\n".join(f"- {g.term}: {', '.join(g.synonyms) or '-'}" for g in glossary) or "(none)"


def fmt_scale() -> str:
    return "\n".join(f"  - {k}: {v}" for k, v in config.PRIORITY_SCALE.items())


def current_reqs(state) -> list[Req]:
    """Consolidated requirements merged with their written form (if any)."""
    written = state.get("written", {})
    return [written.get(r.signature, r).model_copy(update={"ref": r.ref, "area": r.area})
            for r in state.get("reqs", [])]


def norm(text: str) -> str:
    text = re.sub(r"[^\w%$]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()
