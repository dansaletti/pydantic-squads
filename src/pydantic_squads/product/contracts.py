"""Typed hand-off contracts for the product squad.

Plain pydantic models with no dependency on pydantic_ai (ADR 0001), so they
are validated and tested without calling an LLM.
"""

from datetime import datetime
from enum import Enum
from typing import Literal

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
    """A single user story with testable acceptance criteria.

    `needs_design` has no default: the Product Owner decides, per story,
    whether it changes what a user sees or does (ADR 0007).
    """

    model_config = ConfigDict(frozen=True)

    title: str
    acceptance_criteria: list[str] = Field(min_length=1)
    needs_design: bool


class Backlog(BaseModel):
    """The Product Owner's output when a bet is clear enough to build."""

    model_config = ConfigDict(frozen=True)

    stories: list[Story] = Field(min_length=1)


class SendBack(BaseModel):
    """Sent instead of a deliverable when the input is too ambiguous to work from.

    The Product Owner sends back a bet too ambiguous to become stories; the
    Designer sends back a backlog with a story too ambiguous to become a
    screen.
    """

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


class Screen(BaseModel):
    """One screen of a prototype and the stories it covers, by title."""

    model_config = ConfigDict(frozen=True)

    name: str
    purpose: str
    stories: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    states: list[str] = Field(min_length=1)


class ComponentProposal(BaseModel):
    """A design-system component or token the Designer proposes adding."""

    model_config = ConfigDict(frozen=True)

    name: str
    reason: str
    spec: str


class FounderQuestion(BaseModel):
    """A question only the founder can answer, with the Designer's suggested default.

    `origin="hx_gap"` means HX had no answer: `hx_question` is the question
    that was put to HX. `origin="positioning"` covers positioning, tone and
    brand, which are the founder's call and never go through HX.
    """

    model_config = ConfigDict(frozen=True)

    question: str
    context: str
    origin: Literal["hx_gap", "positioning"]
    suggested_default: str
    hx_question: str | None = None

    @model_validator(mode="after")
    def _hx_question_matches_origin(self) -> "FounderQuestion":
        if self.origin == "hx_gap" and not self.hx_question:
            raise ValueError("an hx_gap question must reference the question put to HX")
        if self.origin == "positioning" and self.hx_question is not None:
            raise ValueError("a positioning question must not reference an HX question")
        return self


class Prototype(BaseModel):
    """The Designer's output: a navigable HTML prototype and what it asks of the founder."""

    model_config = ConfigDict(frozen=True)

    screens: list[Screen] = Field(min_length=1)
    html_path: str
    design_system_changes: list[ComponentProposal] = Field(default_factory=list)
    founder_questions: list[FounderQuestion] = Field(default_factory=list)


DesignerOutput = Prototype | SendBack
"""The Designer always delivers a `Prototype` or sends the backlog back."""


def design_coverage_errors(backlog: Backlog, prototype: Prototype) -> list[str]:
    """Why `prototype` doesn't cover `backlog`, or `[]` when it does.

    Every story with `needs_design=True` must appear in some `Screen`, and
    every story a `Screen` cites must exist in the backlog.
    """
    titles = {story.title for story in backlog.stories}
    covered = {title for screen in prototype.screens for title in screen.stories}
    errors = [
        f"story '{story.title}' needs design but is in no screen"
        for story in backlog.stories
        if story.needs_design and story.title not in covered
    ]
    errors.extend(
        f"screen '{screen.name}' cites unknown story '{title}'"
        for screen in prototype.screens
        for title in screen.stories
        if title not in titles
    )
    return errors


SpanStatus = Literal["ok", "retry", "error", "awaiting_approval"]
"""How a span's step resolved: succeeded, was retried, failed, or is still waiting on a human."""


class Span(BaseModel):
    """One timed step of a cycle: a model call, or a single tool call within one.

    Derived after the fact from a run's messages (`product.observability`,
    ADR 0006), never constructed by an agent. `parent_span_id` nests a tool
    call under the model call that made it, and nests HX's own spans under
    the Growth PM's `consult_hx` tool span.
    """

    model_config = ConfigDict(frozen=True)

    span_id: str
    parent_span_id: str | None = None
    agent: Literal["growth_pm", "hx", "product_owner", "designer"]
    operation: str
    tool_call_id: str | None = None
    started_at: datetime
    duration_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    status: SpanStatus
    detail: str | None = None
    output_type: str | None = None


class CycleHeader(BaseModel):
    """The first line of a cycle's trace file."""

    model_config = ConfigDict(frozen=True)

    cycle_id: str
    schema_version: int = 1
    started_at: datetime


class CycleSnapshot(BaseModel):
    """The last line of a cycle's trace file: enough to resume `chat()`.

    `message_history_json` is an opaque string here — only
    `product.observability` (the `ai` extra) knows how to turn it back into
    a list of `pydantic_ai` messages.
    """

    model_config = ConfigDict(frozen=True)

    cycle_id: str
    schema_version: int = 1
    message_history_json: str
    ended_at: datetime


class BetRecord(BaseModel):
    """A closed `Bet`, as written to the knowledge base.

    Kept separate from `Bet` itself: `Bet` is the Growth PM's LLM output
    schema, and these bookkeeping ids are never something a model fills in.
    """

    model_config = ConfigDict(frozen=True)

    bet_version_id: str
    previous_bet_version_id: str | None = None
    cycle_id: str
    schema_version: int = 1
    bet: Bet
    created_at: datetime
