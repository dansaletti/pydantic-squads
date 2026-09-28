import pytest
from pydantic import ValidationError

from pydantic_squads.product import Backlog, Bet, Finding, FindingKind, HXAnswer, SendBack, Story


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
        Story(title="Shorter signup wizard", acceptance_criteria=[])


def test_backlog_requires_at_least_one_story():
    """A Backlog must contain at least one story"""
    with pytest.raises(ValidationError):
        Backlog(stories=[])


def test_backlog_with_stories_is_valid():
    """A Backlog accepts one or more stories"""
    backlog = Backlog(stories=[Story(title="Shorter wizard", acceptance_criteria=["Wizard has 3 steps"])])
    assert len(backlog.stories) == 1


def test_send_back_requires_questions():
    """A SendBack must include at least one open question"""
    with pytest.raises(ValidationError):
        SendBack(reason="Scope is unclear", questions=[])


def test_send_back_with_questions_is_valid():
    """A SendBack accepts a reason with open questions"""
    send_back = SendBack(reason="Scope is unclear", questions=["Which platforms are in scope?"])
    assert send_back.questions == ["Which platforms are in scope?"]
