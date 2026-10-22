"""Extractor (LLM, one call per chunk): atomic candidates + deterministic quote check."""
from difflib import SequenceMatcher

from langgraph.types import Send

from .. import config
from ..llm import structured_call
from ..prompts import EXTRACTOR_SYSTEM, EXTRACTOR_USER
from ..schemas import Candidate, Chunk, ExtractionResult
from .common import event, norm


def quote_found(quote: str, source: str) -> bool:
    """True if the quote occurs in the source (tolerating small transcription slips)."""
    q, s = norm(quote), norm(source)
    if not q:
        return False
    if q in s:
        return True
    blocks = SequenceMatcher(None, s, q, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks if b.size >= 4) / len(q) >= config.GROUNDING_THRESHOLD


def dispatch_extractors(state) -> list[Send]:
    return [Send("extractor", {"chunk": c}) for c in state.get("chunks", [])]


def extractor_node(payload: dict) -> dict:
    chunk: Chunk = payload["chunk"]
    user = EXTRACTOR_USER.format(doc_id=chunk.doc_id, index=chunk.index, total=chunk.total,
                                 date_note=f", dated {chunk.date}" if chunk.date else "",
                                 text=chunk.text)
    result, rec = structured_call("extractor", ExtractionResult, EXTRACTOR_SYSTEM, user)
    items = result.items if result else []
    date = chunk.date or (result.document_date if result else None)
    cands = [Candidate(cid=f"{chunk.chunk_id}/{n:03d}", statement=i.statement, kind=i.kind,
                       quote=i.quote, priority_cues=i.priority_cues, doc_id=chunk.doc_id,
                       date=date, grounded=quote_found(i.quote, chunk.text))
             for n, i in enumerate(items)]
    return {"raw_candidates": cands,
            "log": [rec, event("extractor", chunk=chunk.chunk_id, candidates=len(cands))]}
