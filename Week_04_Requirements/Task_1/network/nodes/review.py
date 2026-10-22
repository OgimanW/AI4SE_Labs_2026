"""Feedback loop: deterministic checks + LLM critic + routing decision."""
import re

from langgraph.types import Send

from .. import config
from ..llm import structured_call
from ..prompts import CRITIC_SYSTEM, CRITIC_USER
from ..schemas import CriticResult, Issue
from .common import current_reqs, event, fmt_glossary, fmt_scale
from .writer import dispatch_writers

CRITIC_TARGET = {"duplicate": "consolidator", "conflict": "consolidator",
                 "out_of_scope": "consolidator", "nonsensical": "consolidator",
                 "inconsistent_vocabulary": "writer", "unclear": "writer",
                 "wrong_priority": "writer"}


def _synonym_hits(text: str, glossary) -> list[str]:
    hits = []
    for g in glossary:
        cleaned = re.sub(rf"\b{re.escape(g.term)}\b", " ", text, flags=re.IGNORECASE)
        hits += [f"'{s}' instead of '{g.term}'" for s in g.synonyms
                 if re.search(rf"\b{re.escape(s)}(s|es)?\b", cleaned, flags=re.IGNORECASE)]
    return hits


def checks_node(state) -> dict:
    """Deterministic validation: IDs, fields, priority, tracing, coverage, vocabulary."""
    issues: list[Issue] = []
    reqs = current_reqs(state)
    refs = [r.ref for r in reqs]
    if len(refs) != len(set(refs)):
        issues.append(Issue(target="consolidator", kind="duplicate_id", refs=[], source="checks",
                            text="Requirement references are not unique."))
    for r in reqs:
        problems = []
        if not r.name.strip() or not r.description.strip():
            problems.append("has no written name/description")
        elif len(r.description.split()) < config.DESCRIPTION_MIN_WORDS:
            problems.append("description is shorter than a paragraph")
        if r.priority not in config.PRIORITY_SCALE or not r.priority_rationale.strip():
            problems.append("priority or its rationale is missing")
        if not r.doc_ids:
            problems.append("has no source document")
        problems += [f"uses {h}" for h in _synonym_hits(f"{r.name} {r.description}",
                                                         state.get("glossary", []))]
        if problems:
            issues.append(Issue(target="writer", kind="field_check", refs=[r.ref],
                                source="checks", text=f"{r.ref} " + "; ".join(problems) + "."))
    accounted = {c for r in reqs for c in r.merged_from} | \
                {c for d in state.get("discarded", []) for c in d.candidate_ids}
    lost = [cid for cid in state.get("candidates", {}) if cid not in accounted]
    if lost:
        issues.append(Issue(target="consolidator", kind="unaccounted", refs=[], source="checks",
                            text=f"Candidates {', '.join(lost)} are neither in a requirement nor "
                                 f"in the discarded list; include each of them."))
    return {"issues": issues, "log": [event("checks", requirements=len(reqs), issues=len(issues))]}


def critic_node(state) -> dict:
    """LLM review, then decide: finish, rework consolidation, or rewrite flagged items."""
    reqs = current_reqs(state)
    by_ref = {r.ref: r for r in reqs}
    lines = "\n".join(f"{r.ref} ({r.priority}: {r.priority_rationale}; {r.type}) "
                      f"[{', '.join(r.doc_ids)}] {r.name}: {r.description}" for r in reqs)
    user = CRITIC_USER.format(scope=state.get("scope_summary", ""), scale=fmt_scale(),
                              glossary=fmt_glossary(state.get("glossary", [])), requirements=lines)
    result, rec = structured_call("critic", CriticResult, CRITIC_SYSTEM, user)
    issues = list(state.get("issues", []))
    notes = []
    for ci in (result.issues if result else []):
        refs = [x for x in ci.refs if x in by_ref]
        text = f"[{ci.issue_type}/{ci.severity}] {', '.join(refs)}: {ci.description}"
        if refs and ci.severity in config.CRITIC_ACTIONABLE:
            issues.append(Issue(target=CRITIC_TARGET[ci.issue_type], kind=ci.issue_type,
                                refs=refs, text=text, source="critic"))
        else:
            notes.append(text)
    loops = state.get("loops", 0)
    rounds = state.get("rounds", []) + [{
        "round": len(state.get("rounds", [])) + 1, "issues": [i.model_dump() for i in issues],
        "minor_notes": notes, "critic_ok": result is not None}]
    out = {"rounds": rounds, "log": [rec, event("critic", issues=len(issues), notes=len(notes))]}
    if not issues or loops >= state.get("max_iterations", config.MAX_ITERATIONS):
        return {**out, "next": "done", "unresolved": issues}
    # writer-level issues: drop the written form of flagged items and attach the note
    feedback, stale = {}, {}
    for i in issues:
        if i.target == "writer":
            for ref in i.refs:
                sig = by_ref[ref].signature
                feedback[sig] = (feedback.get(sig, "") + " " + i.text).strip()
                stale[sig] = None
    to_consolidator = any(i.target == "consolidator" for i in issues)
    cons = [i.text for i in issues if i.target == "consolidator" and i.source == "critic"]
    return {**out, "next": "consolidator" if to_consolidator else "writer", "loops": loops + 1,
            "consolidator_feedback": cons, "writer_feedback": feedback, "written": stale}


def route_after_critic(state) -> list[Send] | str:
    nxt = state.get("next")
    if nxt == "consolidator":
        return "consolidator"
    if nxt == "writer":
        return dispatch_writers(state)
    return "assembler"
