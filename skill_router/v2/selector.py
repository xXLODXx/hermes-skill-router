"""Evidence-based candidate selector."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import replace

from .evidence import document_frequencies, evidence_for
from .models import (
    CandidateDecision,
    DecisionKind,
    Evidence,
    RoutingDecision,
    SkillRecord,
)

MAX_CANDIDATES = 3

# Specificity: a matched catalog word carried by <= SPECIFICITY_CAP skills keeps
# its full weight; more frequent words scale down (min(1, cap/df)) so a generic
# tag/description word cannot pass the gate on its own or crowd the budget.
# Name matches are explicit signals and stay unscaled.
SPECIFICITY_CAP = 6.0
_SUBWORD_FIELD = re.compile(r"passt zu (name|tag|description) '(.+)'")


def _canonical_set(values: Iterable[str]) -> set[str]:
    return {value.strip().casefold() for value in values if value and value.strip()}


def _specificity(field: str, word: str, dfs: Mapping[str, Mapping[str, int]]) -> float:
    df = int(dfs.get(field, {}).get(word, 1))
    if df <= 1:
        return 1.0
    return min(1.0, SPECIFICITY_CAP / df)


def _matched_field(item: Evidence) -> tuple[str, str]:
    """Catalog field/word an evidence item matched ("" for kinds without one)."""
    if item.kind in {"tag", "description"}:
        return item.kind, item.value
    if item.kind == "subword":
        match = _SUBWORD_FIELD.search(item.detail or "")
        if match:
            return match.group(1), match.group(2)
    return "", ""


def _scaled(item: Evidence, dfs: Mapping[str, Mapping[str, int]]) -> Evidence:
    field, word = _matched_field(item)
    if not field or field == "name":
        return item
    specificity = _specificity(field, word, dfs)
    if specificity >= 1.0:
        return item
    return replace(item, weight=item.weight * specificity)


def _has_specific_signal(evidence: Iterable[Evidence], dfs: Mapping[str, Mapping[str, int]]) -> bool:
    for item in evidence:
        if item.kind in {"name", "learned", "matrix"}:
            return True
        field, word = _matched_field(item)
        if field == "name" or (field and _specificity(field, word, dfs) >= 1.0):
            return True
    return False


def _confidence(score: float, distinct_kind_count: int = 0) -> float:
    """Map the calibrated evidence score into a strictly monotonic (0, 1) range."""
    calibrated_score = score + (1.2 if distinct_kind_count > 1 else 0.0)
    return calibrated_score / (calibrated_score + 6.0) if calibrated_score > 0 else 0.0


def _learned_evidence(message: str, skill_name: str, learned: Mapping[str, Mapping[str, int]]) -> tuple[Evidence, ...]:
    from .evidence import tokens

    result: list[Evidence] = []
    for word in tokens(message):
        support = int(learned.get(word, {}).get(skill_name, 0))
        if support >= 2:
            result.append(Evidence("learned", word, min(4.0, 1.0 + support / 4), f"verifiziertes Lernsignal ({support})"))
    return tuple(result)


def select(
    message: str,
    skills: Iterable[SkillRecord],
    *,
    already_loaded: Iterable[str] = (),
    learned: Mapping[str, Mapping[str, int]] | None = None,
    matrix: Mapping[str, tuple[Evidence, ...]] | None = None,
) -> RoutingDecision:
    loaded = _canonical_set(already_loaded)
    learned = learned or {}
    matrix = matrix or {}
    skills = tuple(skills)
    dfs = document_frequencies(skills)
    candidates: list[CandidateDecision] = []
    rejected: list[CandidateDecision] = []
    seen: set[str] = set()
    for skill in skills:
        canonical = skill.canonical_name
        if canonical in seen:
            continue
        seen.add(canonical)
        evidence = (
            tuple(_scaled(item, dfs) for item in evidence_for(message, skill))
            + _learned_evidence(message, canonical, learned)
            + matrix.get(canonical, ())
        )
        score = sum(item.weight for item in evidence)
        exact_score = sum(item.weight for item in evidence if item.kind != "subword")
        is_loaded = canonical in loaded
        if is_loaded:
            rejected.append(
                CandidateDecision(
                    skill,
                    "reject",
                    1.0,
                    evidence,
                    "bereits systemseitig geladen",
                    True,
                    score,
                    exact_score,
                )
            )
            continue
        distinct_kinds = {item.kind for item in evidence}
        has_exact_evidence = any(item.kind in {"name", "tag", "description", "learned", "matrix"} for item in evidence)
        is_matrix_required = any(item.kind == "matrix" and "Pflicht" in item.detail for item in evidence)
        if score < 3.0 or not evidence or not has_exact_evidence:
            if not has_exact_evidence:
                reason = "isoliertes Stamm-/Teilwortsignal"
            elif not _has_specific_signal(evidence, dfs):
                reason = "generisches Signal (katalogweit häufig)"
            else:
                reason = "keine ausreichende Evidenz"
            rejected.append(
                CandidateDecision(
                    skill,
                    "reject",
                    _confidence(score, len(distinct_kinds)),
                    evidence,
                    reason,
                    score=score,
                    exact_score=exact_score,
                )
            )
            continue
        confidence = _confidence(score, len(distinct_kinds))
        decision: DecisionKind = "required" if is_matrix_required or any(item.kind == "name" for item in evidence) else "recommended"
        candidates.append(
            CandidateDecision(
                skill,
                decision,
                confidence,
                evidence,
                "mehrere taskbezogene Evidenzen" if len(distinct_kinds) > 1 else "taskbezogene Evidenz",
                score=score,
                exact_score=exact_score,
            )
        )

    def ranking(item: CandidateDecision) -> tuple[float, float, str]:
        return (-item.confidence, -item.exact_score, item.skill.canonical_name)

    candidates.sort(key=ranking)
    required = [item for item in candidates if item.decision == "required" and any(ev.kind == "matrix" for ev in item.evidence)]
    discovered = [item for item in candidates if item not in required]
    candidates = required + discovered[: max(0, MAX_CANDIDATES - len(required))]
    overflow = [item for item in discovered if item not in candidates]
    rejected.extend(
        replace(item, decision="reject", reason="Kandidatenbudget überschritten")
        for item in overflow
    )
    fallback = None if candidates else "no_high_confidence_match"
    return RoutingDecision(tuple(candidates), tuple(rejected), fallback)
