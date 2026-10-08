"""Typed hand-off contracts for the product squad.

Plain pydantic models with no dependency on pydantic_ai (ADR 0001), so they
are validated and tested without calling an LLM.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)


class FindingKind(str, Enum):
    EVIDENCE = "evidence"  # observed directly, e.g. an interview or usage data
    ASSUMPTION = "assumption"  # written by the team, not yet confirmed by users
    GAP = "gap"  # a question the knowledge base cannot answer


class Finding(BaseModel):
    """A single claim HX makes, classified by how well-founded it is."""

    model_config = ConfigDict(frozen=True)

    claim: str
    kind: FindingKind
    sources: list[str] = Field(
        default_factory=list,
        description=(
            "Exact paths of the notes this claim comes from. At least one for evidence or an assumption. "
            "Always empty for a gap: name the notes you searched in the claim instead."
        ),
    )

    @model_validator(mode="after")
    def _sources_match_kind(self) -> "Finding":
        if self.kind in (FindingKind.EVIDENCE, FindingKind.ASSUMPTION) and not self.sources:
            raise ValueError(f"a {self.kind.value} finding requires at least one source")
        if self.kind == FindingKind.GAP and self.sources:
            raise ValueError("a gap finding must not have sources")
        return self


class HXAnswer(BaseModel):
    """HX's response to a question from the role that consulted it."""

    model_config = ConfigDict(frozen=True)

    question: str
    summary: str
    findings: list[Finding] = Field(min_length=1)


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
    """The Product Owner's output when a brief is clear enough to build."""

    model_config = ConfigDict(frozen=True)

    stories: list[Story] = Field(min_length=1)


class SendBack(BaseModel):
    """Sent by the Designer instead of a prototype when a story is too ambiguous to become a screen.

    The Product Owner does not send back: it rejects a brief with a
    `BriefRejection` (ADR 0011).
    """

    model_config = ConfigDict(frozen=True)

    reason: str
    questions: list[str] = Field(min_length=1)


_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class HumanDecision(BaseModel):
    """What the human decided about a proposed brief, and when.

    Stamped by code when the human approves or rejects a `Synthesis`: no
    model writes it.
    """

    model_config = ConfigDict(frozen=True)

    verdict: Literal["approved", "rejected"]
    notes: str = ""
    decided_at: datetime


class BriefDraft(BaseModel):
    """A brief as proposed to the human: everything but the decision."""

    model_config = ConfigDict(frozen=True)

    problem: _Text
    hypothesis: _Text
    success_metric: _Text
    acceptance_criteria: list[_Text] = Field(min_length=1)
    owner_roles: list[_Text] = Field(min_length=1)


class Brief(BriefDraft):
    """A brief the human approved: the only thing the Product Owner accepts (ADR 0011)."""

    human_decision: HumanDecision

    @field_validator("human_decision")
    @classmethod
    def _approved(cls, decision: HumanDecision) -> HumanDecision:
        if decision.verdict != "approved":
            raise ValueError(f"a brief needs an approved human decision, got '{decision.verdict}'")
        return decision


class BriefRejection(BaseModel):
    """Why a brief did not become a backlog, and which of its fields to fix.

    Returned by `validate_brief` when a field is missing, and by the Product
    Owner when a complete brief is still too ambiguous to become stories.
    """

    model_config = ConfigDict(frozen=True)

    missing_fields: list[str] = Field(default_factory=list)
    reason: _Text


def validate_brief(data: object) -> Brief | BriefRejection:
    """`data` as a `Brief`, or a `BriefRejection` naming every field that is missing or invalid.

    `data` is a mapping or a model (a `BriefDraft` is rejected for its
    missing `human_decision`). Never raises on a bad brief: the rejection is
    the answer.
    """
    if isinstance(data, BaseModel):
        data = data.model_dump()
    try:
        return Brief.model_validate(data)
    except ValidationError as error:
        errors = error.errors()
        missing = list(dict.fromkeys(str(e["loc"][0]) for e in errors if e["loc"]))
        details = "; ".join(f"{'.'.join(str(part) for part in e['loc']) or 'brief'}: {e['msg']}" for e in errors)
        return BriefRejection(
            missing_fields=missing, reason=f"The brief is not ready for the Product Owner. {details}"
        )


class OpinionDraft(BaseModel):
    """A PM's opinion on a request, as the PM writes it."""

    model_config = ConfigDict(frozen=True)

    recommendation: _Text
    risks: list[_Text] = Field(default_factory=list)
    questions_for_human: list[_Text] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]
    sources: list[str] = Field(default_factory=list)


class Opinion(OpinionDraft):
    """A PM's opinion with the role that gave it.

    `role` is stamped by the runtime, never written by the model, and
    `sources` are checked against the knowledge base before an opinion
    exists.
    """

    role: _Text


class Triage(BaseModel):
    """What the Facilitator closes a conversation into: the request, made clear, and who should be heard.

    `roles` are the PMs asked for an opinion. It holds no opinion on the
    request itself: the Facilitator does not give one.
    """

    model_config = ConfigDict(frozen=True)

    request: _Text
    roles: list[_Text] = Field(min_length=1)
    rationale: _Text


class Divergence(BaseModel):
    """A point the PMs disagree on, with each one's position kept as it is."""

    model_config = ConfigDict(frozen=True)

    topic: _Text
    positions: dict[str, _Text] = Field(min_length=2)


class KnowledgeGap(BaseModel):
    """Something HX said the knowledge base does not know, and the questions that surfaced it."""

    model_config = ConfigDict(frozen=True)

    gap: _Text
    questions: list[_Text] = Field(min_length=1)
    asked_by: list[_Text] = Field(min_length=1)


class GapGroup(BaseModel):
    """Gaps the Facilitator says are the same thing, by their numbers in the list it was given."""

    model_config = ConfigDict(frozen=True)

    summary: _Text = Field(description="The gap in one plain sentence: what is not known, not why it matters.")
    gaps: list[int] = Field(min_length=1, description="The numbers of the gaps in this group.")


class SynthesisDraft(BaseModel):
    """The Facilitator's consolidation of the PMs' opinions, as it writes it.

    There is no field for a recommendation of its own: the Facilitator
    consolidates, the human decides.
    """

    model_config = ConfigDict(frozen=True)

    summary: _Text
    divergences: list[Divergence] = Field(default_factory=list)
    questions_for_human: list[_Text] = Field(default_factory=list)
    gap_groups: list[GapGroup] = Field(default_factory=list)
    proposed_brief: BriefDraft


class Synthesis(SynthesisDraft):
    """What the human decides on: the consolidation next to everything it was made from.

    `request`, `opinions`, `rebuttals`, `gaps` and `raw_gaps` are attached by
    the runtime, never written by the model: the PMs' opinions arrive whole,
    so a summary cannot hide what one of them said.

    `raw_gaps` is every gap as HX reported it. `gaps` is the same gaps as
    the Facilitator grouped them (`gap_groups`), with the questions and PMs
    of each group joined by code: every raw gap is in exactly one of them.
    """

    request: _Text
    opinions: list[Opinion] = Field(min_length=1)
    rebuttals: list[Opinion] = Field(default_factory=list)
    gaps: list[KnowledgeGap] = Field(default_factory=list)
    raw_gaps: list[KnowledgeGap] = Field(default_factory=list)


class MarketingGuidance(BaseModel):
    """The PM Marketing's answer to a positioning, tone, brand or naming question.

    `answered=True` means the knowledge base settles it: `guidance` is the
    answer and `sources` the notes it comes from. `answered=False` means it
    does not: `guidance` says what is missing, and the question is one for
    the human.
    """

    model_config = ConfigDict(frozen=True)

    question: _Text
    answered: bool
    guidance: _Text
    sources: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sources_match_answered(self) -> "MarketingGuidance":
        if self.answered and not self.sources:
            raise ValueError("an answered question requires at least one source")
        if not self.answered and self.sources:
            raise ValueError("an unanswered question must not have sources")
        return self


class ContentPiece(BaseModel):
    """One piece of content the Social Media role wrote, and where it is."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["landing_page", "post", "email", "ad"]
    channel: _Text
    title: _Text
    path: _Text


class ContentPack(BaseModel):
    """The Social Media role's output for a brief: the pieces it wrote to the knowledge base."""

    model_config = ConfigDict(frozen=True)

    pieces: list[ContentPiece] = Field(min_length=1)
    open_questions: list[_Text] = Field(default_factory=list)


POOutput = Backlog | BriefRejection
"""The Product Owner always delivers a `Backlog` or rejects the brief."""


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
    brand, and means the PM Marketing could not answer from the knowledge
    base: `marketing_question` is the question that was put to it (ADR 0012).
    """

    model_config = ConfigDict(frozen=True)

    question: str
    context: str
    origin: Literal["hx_gap", "positioning"]
    suggested_default: str
    hx_question: str | None = None
    marketing_question: str | None = None

    @model_validator(mode="after")
    def _asked_question_matches_origin(self) -> "FounderQuestion":
        if self.origin == "hx_gap":
            if not self.hx_question:
                raise ValueError("an hx_gap question must reference the question put to HX")
            if self.marketing_question is not None:
                raise ValueError("an hx_gap question must not reference a PM Marketing question")
        else:
            if not self.marketing_question:
                raise ValueError("a positioning question must reference the question put to the PM Marketing")
            if self.hx_question is not None:
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


AgentName = Literal[
    "squad",
    "facilitator",
    "growth_pm",
    "pm_product",
    "pm_marketing",
    "hx",
    "product_owner",
    "designer",
    "social_media",
]
"""Who a span belongs to: a role, or `"squad"` for what no single role does.

`"squad"` spans are the request and its steps (`request`, `triage`,
`fan_out`, `rebuttal`, `synthesis`, `adjust`) and the human's decision
(ADR 0014).
"""

SpanStatus = Literal["ok", "retry", "error", "awaiting_approval"]
"""How a span's step resolved: succeeded, was retried, failed, or is still waiting on a human."""


class Span(BaseModel):
    """One timed step of a cycle: a model call, or a single tool call within one.

    Derived after the fact from a run's messages (`product.observability`,
    ADR 0006), never constructed by an agent. `parent_span_id` nests a tool
    call under the model call that made it, and nests a consulted role's
    spans (HX, the PM Marketing) under the tool span of the role that
    consulted it.
    """

    model_config = ConfigDict(frozen=True)

    span_id: str
    parent_span_id: str | None = None
    agent: AgentName
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
    model: str | None = None  # the model that answered, on a `model_call` span (roles can differ, ADR 0016)


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


class BriefRecord(BaseModel):
    """An approved `Brief`, as written to the knowledge base.

    Kept separate from `Brief` itself: these bookkeeping ids are stamped by
    the runtime, never filled in by a model.
    """

    model_config = ConfigDict(frozen=True)

    brief_id: str
    cycle_id: str
    schema_version: int = 1
    brief: Brief
    created_at: datetime
