"""Typed data contracts for Skill Router v2."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

EvidenceKind = Literal["name", "tag", "description", "learned", "matrix"]
DecisionKind = Literal["required", "recommended", "observed", "reject"]


@dataclass(frozen=True)
class SkillRecord:
    name: str
    category: str
    description: str = ""
    tags: tuple[str, ...] = ()
    source: str = ""

    @property
    def canonical_name(self) -> str:
        return self.name.strip().casefold()


@dataclass(frozen=True)
class Evidence:
    kind: EvidenceKind
    value: str
    weight: float
    detail: str


@dataclass(frozen=True)
class CandidateDecision:
    skill: SkillRecord
    decision: DecisionKind
    confidence: float
    evidence: tuple[Evidence, ...] = ()
    reason: str = ""
    already_loaded: bool = False


@dataclass(frozen=True)
class RoutingDecision:
    candidates: tuple[CandidateDecision, ...] = ()
    rejected: tuple[CandidateDecision, ...] = ()
    fallback_reason: str | None = None
    estimated_chars: int = 0

    @property
    def accepted(self) -> tuple[CandidateDecision, ...]:
        return tuple(c for c in self.candidates if c.decision != "reject")


@dataclass
class SessionTurn:
    session_id: str
    message: str = ""
    turn_id: int = 0
    last_signature: tuple[str, ...] = ()
    injected: set[str] = field(default_factory=set)
    already_loaded: set[str] = field(default_factory=set)
    tool_results: list[object] = field(default_factory=list)
    last_response: str = ""
