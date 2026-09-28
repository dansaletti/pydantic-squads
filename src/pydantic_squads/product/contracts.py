"""Typed hand-off contracts for the product squad.

Plain pydantic models with no dependency on pydantic_ai (ADR 0001), so they
are validated and tested without calling an LLM.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FindingKind(str, Enum):
    EVIDENCE = "evidence"  # observed directly, e.g. an interview or usage data
    ASSUMPTION = "assumption"  # written by the team, not yet confirmed by users
    GAP = "gap"  # a question the knowledge base cannot answer


class Finding(BaseModel):
    """A single claim HX makes, classified by how well-founded it is."""

    model_config = ConfigDict(frozen=True)

    claim: str
    kind: FindingKind
    sources: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sources_match_kind(self) -> "Finding":
        if self.kind in (FindingKind.EVIDENCE, FindingKind.ASSUMPTION) and not self.sources:
            raise ValueError(f"a {self.kind.value} finding requires at least one source")
        if self.kind == FindingKind.GAP and self.sources:
            raise ValueError("a gap finding must not have sources")
        return self


class HXAnswer(BaseModel):
    """HX's response to a question from the Growth PM."""

    model_config = ConfigDict(frozen=True)

    question: str
    summary: str
    findings: list[Finding] = Field(min_length=1)


class Bet(BaseModel):
    """A founder-approved bet, ready to hand off to the Product Owner."""

    model_config = ConfigDict(frozen=True)

    hypothesis: str
    metric: str
    expected_impact: str
    scope: list[str] = Field(min_length=1)
    out_of_scope: list[str] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)


class Story(BaseModel):
    """A single user story with testable acceptance criteria."""

    model_config = ConfigDict(frozen=True)

    title: str
    acceptance_criteria: list[str] = Field(min_length=1)


class Backlog(BaseModel):
    """The Product Owner's output when a bet is clear enough to build."""

    model_config = ConfigDict(frozen=True)

    stories: list[Story] = Field(min_length=1)


class SendBack(BaseModel):
    """The Product Owner's output when a bet is too ambiguous to become stories."""

    model_config = ConfigDict(frozen=True)

    reason: str
    questions: list[str] = Field(min_length=1)


POOutput = Backlog | SendBack
"""The Product Owner always delivers a `Backlog` or sends the bet back."""


class Revision(BaseModel):
    """A `Bet` the Growth PM revised after a Product Owner `SendBack`.

    Carries the `SendBack` that prompted the revision alongside the new
    `Bet`, so the founder can see the Product Owner's reason and questions
    when deciding whether to approve it.
    """

    model_config = ConfigDict(frozen=True)

    bet: Bet
    send_back: SendBack
