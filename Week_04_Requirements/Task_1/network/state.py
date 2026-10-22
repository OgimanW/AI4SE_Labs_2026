"""LangGraph state and reducers."""
import operator
from typing import Annotated, Any, TypedDict

from .schemas import Candidate, Chunk, Discard, Document, GlossaryTerm, Issue, Req


def merge_dict(left: dict | None, right: dict | None) -> dict:
    """Merge dict updates; a value of None deletes the key."""
    out = dict(left or {})
    for key, value in (right or {}).items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


class State(TypedDict, total=False):
    input_dir: str
    output_dir: str
    max_iterations: int
    documents: list[Document]
    chunks: list[Chunk]
    raw_candidates: Annotated[list[Candidate], operator.add]   # fan-in from extractors
    candidates: dict[str, Candidate]                           # C-ID -> candidate
    scope_summary: str
    glossary: list[GlossaryTerm]
    areas: list[str]
    reqs: list[Req]                                            # consolidated requirements
    discarded: list[Discard]                                   # blacklist
    written: Annotated[dict[str, Req], merge_dict]             # signature -> written req
    writer_feedback: dict[str, str]                            # signature -> reviewer note
    consolidator_feedback: list[str]
    issues: list[Issue]                                        # deterministic findings
    loops: int
    rounds: list[dict[str, Any]]
    next: str
    unresolved: list[Issue]
    log: Annotated[list[dict[str, Any]], operator.add]
