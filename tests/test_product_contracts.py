import pytest
from pydantic import ValidationError

from pydantic_squads.product import (
    Backlog,
    Bet,
    ComponentProposal,
    Finding,
    FindingKind,
    FounderQuestion,
    HXAnswer,
    Prototype,
    Revision,
    Screen,
    SendBack,
    Story,
    design_coverage_errors,
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


def test_bet_requires_scope_and_out_of_scope():
    """A Bet must state both what is in scope and what is out"""
    with pytest.raises(ValidationError):
        Bet(
            hypothesis="Shortening onboarding lifts activation",
            metric="activation_rate",
            expected_impact="+5pp",
            scope=[],
            out_of_scope=["Payment flow"],
        )


def test_bet_defaults_assumptions_and_evidence_to_empty():
    """A Bet's assumptions and evidence_used default to an empty list"""
    bet = Bet(
        hypothesis="Shortening onboarding lifts activation",
        metric="activation_rate",
        expected_impact="+5pp",
        scope=["Signup wizard"],
        out_of_scope=["Payment flow"],
    )
    assert bet.assumptions == []
    assert bet.evidence_used == []


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


def _bet(**overrides) -> Bet:
    defaults = dict(
        hypothesis="Shortening onboarding lifts activation",
        metric="activation_rate",
        expected_impact="+5pp",
        scope=["Signup wizard"],
        out_of_scope=["Payments"],
    )
    return Bet(**{**defaults, **overrides})


def test_revision_carries_both_the_new_bet_and_the_send_back():
    """A Revision pairs the PM's new Bet with the SendBack that prompted it"""
    send_back = SendBack(reason="Scope is unclear", questions=["Which platforms are in scope?"])
    bet = _bet()
    revision = Revision(bet=bet, send_back=send_back)
    assert revision.bet == bet
    assert revision.send_back == send_back


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
    with pytest.raises(ValidationError, match="must not reference"):
        FounderQuestion(question="Q?", context="c", origin="positioning", suggested_default="d", hx_question="x")


def test_positioning_question_without_hx_question_is_valid():
    """A positioning FounderQuestion without an HX question is valid"""
    q = FounderQuestion(question="Tone?", context="c", origin="positioning", suggested_default="Friendly")
    assert q.hx_question is None


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
