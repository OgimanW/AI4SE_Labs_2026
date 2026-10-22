"""Consolidator (LLM): glossary/scope, then incremental batches that merge duplicates,
resolve conflicts and fill the blacklist; on rework also applies reviewer repairs."""
import re

from .. import config
from ..llm import structured_call
from ..prompts import (BATCH_SYSTEM, BATCH_USER, GLOSSARY_SYSTEM, GLOSSARY_USER, REPAIR_SYSTEM,
                       REPAIR_USER)
from ..schemas import (BatchResult, Candidate, Discard, GlossaryResult, GlossaryTerm, RepairResult,
                       Req)
from .common import event, fmt_glossary, norm


def _number_candidates(state) -> dict[str, Candidate]:
    """Assign stable C-IDs in document/chunk order (deterministic)."""
    order = {c.chunk_id: i for i, c in enumerate(state.get("chunks", []))}
    raw = sorted(state.get("raw_candidates", []),
                 key=lambda c: (order.get(c.cid.split("/")[0], 0), c.cid))
    width = max(3, len(str(len(raw))))
    return {f"C-{i:0{width}d}": c.model_copy(update={"cid": f"C-{i:0{width}d}"})
            for i, c in enumerate(raw, 1)}


def _true_synonyms(term: str, synonyms: list[str]) -> list[str]:
    """Drop synonyms that are inflections of the term, contain it, or are part of it
    (e.g. "system" for "billing system" would flag every "The system shall")."""
    def stem(t: str) -> str:
        return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in norm(t).split())
    t = stem(term)
    return [s for s in dict.fromkeys(synonyms) if stem(s) and stem(s) != t and t not in stem(s) and stem(s) not in t]


class _Set:
    """Mutable requirement set with deterministic ref numbering."""

    def __init__(self, reqs: list[Req], discarded: list[Discard], cands: dict[str, Candidate],
                 areas: list[str]):
        self.areas = areas
        self.reqs = {r.ref: r.model_copy(deep=True) for r in reqs}
        self.discarded = list(discarded)
        self.cands = cands
        self.next = max((int(r[1:]) for r in self.reqs), default=0) + 1

    def new(self, c: Candidate, statement: str | None, area: str | None) -> str:
        known = {a.lower(): a for a in self.areas}
        area = known.get((area or "").strip().lower(), area)
        ref = f"R{self.next:03d}"
        self.next += 1
        self.reqs[ref] = Req(ref=ref, area=(area or "General").strip(), kind=c.kind,
                             statement=statement or c.statement, merged_from=[c.cid],
                             doc_ids=[c.doc_id])
        return ref

    def add_member(self, ref: str, cids: list[str]) -> None:
        r = self.reqs[ref]
        r.merged_from = list(dict.fromkeys(r.merged_from + cids))
        r.doc_ids = sorted({self.cands[m].doc_id for m in r.merged_from})

    def original(self, cids: list[str]) -> str:
        """The source candidates' own wording (not the consolidated rewording)."""
        return " / ".join(dict.fromkeys(self.cands[c].statement for c in cids))

    def drop(self, ref: str, category: str, explanation: str, conflicts_with: str | None) -> None:
        r = self.reqs.pop(ref)
        self.discarded.append(Discard(statement=self.original(r.merged_from),
                                      candidate_ids=r.merged_from,
                                      doc_ids=r.doc_ids, category=category,
                                      explanation=explanation, conflicts_with=conflicts_with))

    def lines(self, refs=None) -> str:
        return "\n".join(f"{r.ref} [{r.area}] {r.statement} ({', '.join(r.doc_ids)})"
                         for r in self.reqs.values() if refs is None or r.ref in refs)


def _apply_batch(rs: _Set, batch: list[Candidate], result: BatchResult) -> None:
    by_cid = {c.cid: c for c in batch}
    decisions = {}
    for d in result.decisions:
        if d.cid in by_cid:
            decisions.setdefault(d.cid, d)
    created: dict[str, str] = {}
    for cid, d in decisions.items():                 # pass 1: new requirements
        if d.action == "new":
            created[cid] = rs.new(by_cid[cid], d.statement, d.area)
    for cid, d in decisions.items():                 # pass 2: everything referring to targets
        if d.action == "new":
            continue
        c = by_cid[cid]
        target = created.get(d.target or "", d.target)
        target = target if target in rs.reqs else None
        if d.action == "merge" and target:
            rs.add_member(target, [cid])
            if d.statement:
                rs.reqs[target].statement = d.statement
        elif d.action == "supersede" and target:
            old = rs.reqs[target]
            rs.discarded.append(Discard(
                statement=rs.original(old.merged_from), candidate_ids=old.merged_from,
                doc_ids=old.doc_ids,
                category="conflict", conflicts_with=target,
                explanation=d.explanation or "Replaced by a better-supported conflicting need."))
            old.statement, old.merged_from, old.doc_ids = d.statement or c.statement, [cid], [c.doc_id]
        elif d.action == "discard":
            rs.discarded.append(Discard(statement=c.statement, candidate_ids=[cid],
                                        doc_ids=[c.doc_id], category=d.category or "other",
                                        explanation=d.explanation or "", conflicts_with=target))
        else:                                        # merge/supersede without a valid target
            rs.new(c, d.statement, d.area)


def _apply_repairs(rs: _Set, result: RepairResult) -> None:
    for op in result.ops:
        refs = [r for r in dict.fromkeys(op.refs) if r in rs.reqs]
        if not refs:
            continue
        if op.op == "merge" and len(refs) > 1:
            for other in refs[1:]:
                rs.add_member(refs[0], rs.reqs.pop(other).merged_from)
            if op.statement:
                rs.reqs[refs[0]].statement = op.statement
        elif op.op == "discard":
            keep = op.conflicts_with if op.conflicts_with in rs.reqs else None
            rs.drop(refs[0], op.category or "other", op.explanation or "", keep)
        elif op.op == "edit" and op.statement:
            rs.reqs[refs[0]].statement = op.statement


def consolidator_node(state) -> dict:
    cands = state.get("candidates") or _number_candidates(state)
    grounded = {cid: c for cid, c in cands.items() if c.grounded}
    logs: list[dict] = []
    scope, glossary = state.get("scope_summary", ""), state.get("glossary", [])
    areas = state.get("areas", [])
    discarded = list(state.get("discarded", []))
    if not state.get("reqs") and not discarded:      # first pass
        discarded = [Discard(statement=c.statement, candidate_ids=[c.cid], doc_ids=[c.doc_id],
                             category="ungrounded", conflicts_with=None,
                             explanation="The extractor's supporting quote was not found in the "
                                         "source document, so the item may be invented.")
                     for c in cands.values() if not c.grounded]
        res, rec = structured_call("consolidator", GlossaryResult, GLOSSARY_SYSTEM,
                                   GLOSSARY_USER.format(count=len(grounded), candidates="\n".join(
                                       f"{c.cid} {c.statement}" for c in grounded.values())))
        logs.append(rec)
        if res:
            scope, areas = res.scope_summary, res.areas
            glossary = [GlossaryTerm(term=g.term, definition=g.definition,
                                     synonyms=_true_synonyms(g.term, g.synonyms))
                        for g in res.glossary]
    rs = _Set(state.get("reqs", []), discarded, cands, areas)

    feedback = state.get("consolidator_feedback", [])
    if feedback and rs.reqs:                          # reviewer repairs
        refs = set(re.findall(r"\bR\d{3}\b", " ".join(feedback)))
        lines = []
        for r in rs.reqs.values():
            if r.ref in refs:
                ev = " || ".join(cands[m].quote[:200] for m in r.merged_from[:3])
                dates = ", ".join(sorted({cands[m].date or "undated" for m in r.merged_from}))
                lines.append(f"{r.ref} [{r.area}] {r.statement} ({', '.join(r.doc_ids)}; {dates}) | {ev}")
        res, rec = structured_call("consolidator", RepairResult, REPAIR_SYSTEM,
                                   REPAIR_USER.format(issues="\n".join(f"- {f}" for f in feedback),
                                                      requirements="\n".join(lines)))
        logs.append(rec)
        if res:
            _apply_repairs(rs, res)

    accounted = {m for r in rs.reqs.values() for m in r.merged_from} | \
                {m for d in rs.discarded for m in d.candidate_ids}
    todo = [c for c in grounded.values() if c.cid not in accounted]
    size = config.CONSOLIDATION_BATCH
    for i in range(0, len(todo), size):              # incremental batches (sequential)
        batch = todo[i:i + size]
        user = BATCH_USER.format(
            scope=scope, areas="; ".join(areas), glossary=fmt_glossary(glossary),
            requirements=rs.lines() or "(none yet)",
            candidates="\n".join(f"{c.cid} [{c.doc_id}, {c.date or 'undated'}] ({c.kind}) "
                                 f"{c.statement} | {', '.join(c.priority_cues) or '-'} | "
                                 f"\"{c.quote[:200]}\"" for c in batch))
        res, rec = structured_call("consolidator", BatchResult, BATCH_SYSTEM, user)
        logs.append(rec)
        print(f"         consolidator batch {i // size + 1}/{-(-len(todo) // size)}: "
              f"{len(rs.reqs)} requirements so far", flush=True)
        if res:
            _apply_batch(rs, batch, res)
    return {"candidates": cands, "reqs": list(rs.reqs.values()), "discarded": rs.discarded,
            "glossary": glossary, "scope_summary": scope, "areas": areas,
            "log": logs + [event("consolidator", candidates=len(cands), grounded=len(grounded),
                                 processed=len(todo), requirements=len(rs.reqs),
                                 discarded=len(rs.discarded))]}
