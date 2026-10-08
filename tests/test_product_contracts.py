from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from pydantic_squads.product import (
    Backlog,
    Brief,
    BriefDraft,
    BriefRejection,
    ComponentProposal,
    ContentPack,
    ContentPiece,
    Finding,
    FindingKind,
    FounderQuestion,
    HumanDecision,
    HXAnswer,
    MarketingGuidance,
    Opinion,
    OpinionDraft,
    Prototype,
    Screen,
    SendBack,
    Story,
    design_coverage_errors,
    validate_brief,
)


def test_evidence_requires_source():
    """An evidence finding without a source is rejected"""
    with pytest.raises(ValidationError, match="requires at least one source"):
        Finding(claim="Users churn at step 3", kind=FindingKind.EVIDENCE, sources=[])


def test_assumption_requires_source():
    """An assumption finding without a source is rejected"""
    with pytest.raises(ValidationError, match="requires at least one source"):
        Finding(claim="Users probably churn at step 3", kind=FindingKind.ASSUMPTION, sources=[])


def test_gap_rejects_source():
    """A gap finding cannot cite a source"""
    with pytest.raises(ValidationError, match="must not have sources"):
        Finding(claim="No data on step 3 churn", kind=FindingKind.GAP, sources=["notes/x.md"])


def test_evidence_with_source_is_valid():
    """An evidence finding with a source is accepted"""
    finding = Finding(claim="Users churn at step 3", kind=FindingKind.EVIDENCE, sources=["notes/interview-1.md"])
    assert finding.sources == ["notes/interview-1.md"]


def test_gap_without_source_is_valid():
    """A gap finding with no sources is accepted"""
    finding = Finding(claim="No data on step 3 churn", kind=FindingKind.GAP, sources=[])
    assert finding.sources == []


def test_hx_answer_requires_at_least_one_finding():
    """HXAnswer must include at least one finding"""
    with pytest.raises(ValidationError):
        HXAnswer(question="Why do users churn?", summary="Unclear", findings=[])


def test_hx_answer_with_findings_is_valid():
    """HXAnswer accepts a question with its supporting findings"""
    answer = HXAnswer(
        question="Why do users churn?",
        summary="Step 3 is confusing",
        findings=[Finding(claim="Users churn at step 3", kind=FindingKind.EVIDENCE, sources=["notes/x.md"])],
    )
    assert len(answer.findings) == 1


def test_story_requires_acceptance_criteria():
    """A Story must have at least one acceptance criterion"""
    with pytest.raises(ValidationError):
        Story(title="Shorter signup wizard", acceptance_criteria=[], needs_design=True)


def test_backlog_requires_at_least_one_story():
    """A Backlog must contain at least one story"""
    with pytest.raises(ValidationError):
        Backlog(stories=[])


def test_backlog_with_stories_is_valid():
    """A Backlog accepts one or more stories"""
    backlog = Backlog(stories=[Story(title="Shorter wizard", acceptance_criteria=["Wizard has 3 steps"], needs_design=True)])
    assert len(backlog.stories) == 1


def test_send_back_requires_questions():
    """A SendBack must include at least one open question"""
    with pytest.raises(ValidationError):
        SendBack(reason="Scope is unclear", questions=[])


def test_send_back_with_questions_is_valid():
    """A SendBack accepts a reason with open questions"""
    send_back = SendBack(reason="Scope is unclear", questions=["Which platforms are in scope?"])
    assert send_back.questions == ["Which platforms are in scope?"]


def _decision(verdict: str = "approved") -> HumanDecision:
    return HumanDecision(verdict=verdict, decided_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


def _brief_data(**overrides) -> dict:
    defaults = dict(
        problem="New dispatch managers drop out of the signup wizard",
        hypothesis="Shortening onboarding lifts activation",
        success_metric="activation_rate +5pp",
        acceptance_criteria=["The wizard has 3 steps"],
        owner_roles=["growth_pm"],
        human_decision=_decision(),
    )
    return {**defaults, **overrides}


def test_brief_requires_an_approved_human_decision():
    """A Brief whose human decision is a rejection does not validate"""
    with pytest.raises(ValidationError, match="approved human decision"):
        Brief(**_brief_data(human_decision=_decision("rejected")))


def test_brief_rejects_blank_text():
    """A Brief field holding only whitespace counts as empty"""
    with pytest.raises(ValidationError):
        Brief(**_brief_data(problem="   "))
    with pytest.raises(ValidationError):
        Brief(**_brief_data(acceptance_criteria=[" "]))


def test_validate_brief_returns_the_brief_when_complete():
    """validate_brief returns a Brief for complete data, and a Brief unchanged"""
    brief = validate_brief(_brief_data())
    assert isinstance(brief, Brief)
    assert validate_brief(brief) == brief


def test_validate_brief_names_every_missing_field():
    """validate_brief rejects incomplete data naming each field once, in the brief's order"""
    rejection = validate_brief({"problem": "p", "acceptance_criteria": ["", ""]})
    assert isinstance(rejection, BriefRejection)
    assert rejection.missing_fields == [
        "hypothesis",
        "success_metric",
        "acceptance_criteria",
        "owner_roles",
        "human_decision",
    ]
    assert "success_metric" in rejection.reason


def test_validate_brief_rejects_a_draft_for_its_missing_decision():
    """A BriefDraft has no human decision, so validate_brief rejects it"""
    draft = BriefDraft(**{k: v for k, v in _brief_data().items() if k != "human_decision"})
    rejection = validate_brief(draft)
    assert isinstance(rejection, BriefRejection)
    assert rejection.missing_fields == ["human_decision"]


def test_validate_brief_rejects_a_decision_that_is_not_an_approval():
    """validate_brief names human_decision when the human rejected the brief"""
    rejection = validate_brief(_brief_data(human_decision=_decision("rejected")))
    assert isinstance(rejection, BriefRejection)
    assert rejection.missing_fields == ["human_decision"]


def test_validate_brief_rejects_data_that_is_not_a_brief_at_all():
    """validate_brief rejects, without raising, something that is not even a mapping"""
    rejection = validate_brief("build me a landing page")
    assert isinstance(rejection, BriefRejection)
    assert rejection.missing_fields == []
    assert rejection.reason.startswith("The brief is not ready")


def test_brief_rejection_requires_a_reason():
    """A BriefRejection without a reason is rejected"""
    with pytest.raises(ValidationError):
        BriefRejection(missing_fields=["problem"], reason="")



# -- Designer contracts (ADR 0007) -------------------------------------------


def test_story_requires_needs_design():
    """A Story has no needs_design default: the Product Owner must decide"""
    with pytest.raises(ValidationError, match="needs_design"):
        Story(title="Shorter wizard", acceptance_criteria=["3 steps"])


def _screen(name: str = "Signup", stories: list[str] | None = None) -> Screen:
    return Screen(name=name, purpose="Sign up", stories=stories or [], states=["default"])


def test_screen_requires_a_state():
    """A Screen must list at least one state"""
    with pytest.raises(ValidationError):
        Screen(name="Signup", purpose="Sign up", states=[])


def test_prototype_requires_a_screen():
    """A Prototype must have at least one screen"""
    with pytest.raises(ValidationError):
        Prototype(screens=[], html_path="squad/design/c/prototype.html")


def test_prototype_defaults_changes_and_questions_to_empty():
    """A Prototype's design-system changes and founder questions default to empty"""
    prototype = Prototype(screens=[_screen()], html_path="squad/design/c/prototype.html")
    assert prototype.design_system_changes == []
    assert prototype.founder_questions == []


def test_component_proposal_carries_name_reason_and_spec():
    """A ComponentProposal records what to add, why, and how it works"""
    proposal = ComponentProposal(name="Stepper", reason="Wizard needs progress", spec="Dots, current one filled")
    assert proposal.name == "Stepper"


def test_hx_gap_question_requires_the_hx_question():
    """An hx_gap FounderQuestion must reference the question put to HX"""
    with pytest.raises(ValidationError, match="question put to HX"):
        FounderQuestion(question="Q?", context="c", origin="hx_gap", suggested_default="d")


def test_hx_gap_question_with_hx_question_is_valid():
    """An hx_gap FounderQuestion that references its HX question is valid"""
    q = FounderQuestion(question="Q?", context="c", origin="hx_gap", suggested_default="d", hx_question="Do users X?")
    assert q.hx_question == "Do users X?"


def test_positioning_question_rejects_an_hx_question():
    """A positioning FounderQuestion never references an HX question"""
    with pytest.raises(ValidationError, match="must not reference an HX question"):
        FounderQuestion(
            question="Q?",
            context="c",
            origin="positioning",
            suggested_default="d",
            hx_question="x",
            marketing_question="Which tone?",
        )


def test_positioning_question_requires_the_marketing_question():
    """A positioning FounderQuestion must reference the question put to the PM Marketing"""
    with pytest.raises(ValidationError, match="question put to the PM Marketing"):
        FounderQuestion(question="Tone?", context="c", origin="positioning", suggested_default="Friendly")


def test_positioning_question_with_marketing_question_is_valid():
    """A positioning FounderQuestion that references its PM Marketing question is valid"""
    q = FounderQuestion(
        question="Tone?", context="c", origin="positioning", suggested_default="Friendly", marketing_question="Which tone?"
    )
    assert q.hx_question is None
    assert q.marketing_question == "Which tone?"


def test_hx_gap_question_rejects_a_marketing_question():
    """An hx_gap FounderQuestion never references a PM Marketing question"""
    with pytest.raises(ValidationError, match="must not reference a PM Marketing question"):
        FounderQuestion(
            question="Q?", context="c", origin="hx_gap", suggested_default="d", hx_question="x", marketing_question="y"
        )


def test_answered_marketing_guidance_requires_a_source():
    """A MarketingGuidance that answers the question must cite the note it comes from"""
    with pytest.raises(ValidationError, match="requires at least one source"):
        MarketingGuidance(question="Which tone?", answered=True, guidance="Friendly")


def test_unanswered_marketing_guidance_has_no_sources():
    """A MarketingGuidance that could not answer says what is missing and cites nothing"""
    with pytest.raises(ValidationError, match="must not have sources"):
        MarketingGuidance(question="Which tone?", answered=False, guidance="No brand note", sources=["docs/x.md"])
    guidance = MarketingGuidance(question="Which tone?", answered=False, guidance="No brand note")
    assert guidance.sources == []


def test_content_pack_needs_at_least_one_piece():
    """A ContentPack with no pieces is rejected, and a piece's kind is one of the known ones"""
    with pytest.raises(ValidationError):
        ContentPack(pieces=[])
    with pytest.raises(ValidationError):
        ContentPiece(kind="billboard", channel="street", title="t", path="squad/content/c/x.md")


def _backlog() -> Backlog:
    return Backlog(
        stories=[
            Story(title="See progress", acceptance_criteria=["Shows step"], needs_design=True),
            Story(title="Store drafts", acceptance_criteria=["Draft saved"], needs_design=False),
        ]
    )


def test_coverage_gate_passes_when_every_design_story_is_on_a_screen():
    """The coverage gate passes when every needs_design story is on some screen"""
    prototype = Prototype(screens=[_screen(stories=["See progress"])], html_path="p.html")
    assert design_coverage_errors(_backlog(), prototype) == []


def test_coverage_gate_ignores_stories_that_need_no_design():
    """Stories with needs_design=False may be left off every screen"""
    prototype = Prototype(screens=[_screen(stories=["See progress"])], html_path="p.html")
    assert not any("Store drafts" in e for e in design_coverage_errors(_backlog(), prototype))


def test_coverage_gate_flags_an_uncovered_design_story():
    """The coverage gate flags a needs_design story that is on no screen"""
    prototype = Prototype(screens=[_screen()], html_path="p.html")
    assert design_coverage_errors(_backlog(), prototype) == ["story 'See progress' needs design but is in no screen"]


def test_coverage_gate_flags_a_screen_citing_an_unknown_story():
    """The coverage gate flags a screen that cites a story missing from the backlog"""
    prototype = Prototype(screens=[_screen(stories=["See progress", "Invented"])], html_path="p.html")
    assert design_coverage_errors(_backlog(), prototype) == ["screen 'Signup' cites unknown story 'Invented'"]


def test_opinion_draft_needs_a_recommendation_and_a_known_confidence():
    """An OpinionDraft without a recommendation, or with a made-up confidence, is rejected"""
    with pytest.raises(ValidationError):
        OpinionDraft(recommendation=" ", confidence="high")
    with pytest.raises(ValidationError):
        OpinionDraft(recommendation="Ship it", confidence="certain")


def test_opinion_draft_has_no_role_for_the_model_to_fill():
    """The role is not part of what a PM writes: only Opinion carries it"""
    assert "role" not in OpinionDraft.model_fields
    opinion = Opinion(role="pm_product", recommendation="Ship it", confidence="low")
    assert opinion.role == "pm_product"
    assert opinion.risks == [] and opinion.questions_for_human == [] and opinion.sources == []


def test_finding_schema_tells_the_model_a_gap_has_no_sources():
    """The schema HX fills in says, on the field itself, that a gap's sources are empty"""
    description = Finding.model_json_schema()["properties"]["sources"]["description"]
    assert "empty for a gap" in description
