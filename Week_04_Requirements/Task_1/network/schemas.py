"""Pydantic models: internal objects and LLM structured-output schemas
(LLM schemas have no defaults so they are valid in strict JSON-schema mode)."""
from typing import Literal

from pydantic import BaseModel

Kind = Literal["functional", "non_functional", "constraint"]
Priority = Literal["Must", "Should", "Could", "Won't"]
Category = Literal["conflict", "nonsensical", "out_of_scope", "other"]


# ---------------- internal ----------------
class Document(BaseModel):
    doc_id: str
    path: str
    text: str
    date: str | None


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    index: int
    total: int
    text: str
    date: str | None


class Candidate(BaseModel):
    cid: str
    statement: str
    kind: Kind
    quote: str
    priority_cues: list[str]
    doc_id: str
    date: str | None
    grounded: bool


class Req(BaseModel):
    """A consolidated requirement (before/after writing)."""
    ref: str
    area: str
    statement: str
    kind: Kind
    merged_from: list[str]
    doc_ids: list[str]
    name: str = ""
    description: str = ""
    type: Literal["functional", "non_functional"] = "functional"
    priority: Priority = "Should"
    priority_rationale: str = ""

    @property
    def signature(self) -> str:
        """Identity of the content; unchanged content keeps its written form."""
        return self.statement + "|" + ",".join(sorted(self.merged_from))


class Discard(BaseModel):
    statement: str
    candidate_ids: list[str]
    doc_ids: list[str]
    category: Literal["conflict", "nonsensical", "out_of_scope", "ungrounded", "other"]
    explanation: str
    conflicts_with: str | None


class Issue(BaseModel):
    target: Literal["consolidator", "writer"]
    kind: str
    refs: list[str]
    text: str
    source: Literal["checks", "critic"]


# ---------------- LLM outputs ----------------
class ExtractedItem(BaseModel):
    statement: str
    kind: Kind
    quote: str
    priority_cues: list[str]


class ExtractionResult(BaseModel):
    document_date: str | None
    items: list[ExtractedItem]


class GlossaryTerm(BaseModel):
    term: str
    definition: str
    synonyms: list[str]


class GlossaryResult(BaseModel):
    scope_summary: str
    glossary: list[GlossaryTerm]
    areas: list[str]


class CandidateDecision(BaseModel):
    cid: str
    action: Literal["new", "merge", "supersede", "discard"]
    target: str | None          # existing ref or a "new" candidate id of this batch
    statement: str | None       # wording for new / revised merged / superseding requirement
    area: str | None
    category: Category | None
    explanation: str | None


class BatchResult(BaseModel):
    decisions: list[CandidateDecision]


class RepairOp(BaseModel):
    op: Literal["merge", "discard", "edit"]
    refs: list[str]
    statement: str | None
    category: Category | None
    explanation: str | None
    conflicts_with: str | None


class RepairResult(BaseModel):
    ops: list[RepairOp]


class WrittenReq(BaseModel):
    ref: str
    name: str
    description: str
    type: Literal["functional", "non_functional"]
    priority: Priority
    priority_rationale: str


class WriterResult(BaseModel):
    requirements: list[WrittenReq]


class CriticIssue(BaseModel):
    issue_type: Literal["duplicate", "conflict", "out_of_scope", "nonsensical",
                        "inconsistent_vocabulary", "unclear", "wrong_priority"]
    severity: Literal["high", "medium", "low"]
    refs: list[str]
    description: str


class CriticResult(BaseModel):
    issues: list[CriticIssue]
