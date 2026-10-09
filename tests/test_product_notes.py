from datetime import datetime, timezone

from pydantic_squads.product.contracts import (
    Brief,
    BriefDraft,
    BriefRecord,
    Divergence,
    FounderQuestion,
    HumanDecision,
    KnowledgeGap,
    Opinion,
    Prototype,
    Screen,
    Synthesis,
)
from pydantic_squads.product.knowledge import _parse_note
from pydantic_squads.product.notes import brief_note, decision_note, founder_questions_note, synthesis_note

DECIDED_AT = datetime(2026, 10, 8, 17, 30, tzinfo=timezone.utc)
LOCAL = DECIDED_AT.astimezone()


def _decision(verdict: str = "approved", notes: str = "") -> HumanDecision:
    return HumanDecision(verdict=verdict, notes=notes, decided_at=DECIDED_AT)


def _draft() -> BriefDraft:
    return BriefDraft(
        problem="Dispatch managers cannot share a route",
        hypothesis="If we offer sharing, they will use it",
        success_metric="20% click the call to action",
        acceptance_criteria=["The page has one call to action", "Clicks are counted"],
        owner_roles=["growth_pm", "pm_product"],
    )


def _record(notes: str = "") -> BriefRecord:
    brief = Brief(**_draft().model_dump(), human_decision=_decision(notes=notes))
    return BriefRecord(brief_id="b1", cycle_id="c1", brief=brief, created_at=DECIDED_AT)


def _opinion(role: str = "growth_pm", **overrides) -> Opinion:
    defaults = dict(recommendation="Run it for two weeks", confidence="medium")
    return Opinion(role=role, **{**defaults, **overrides})


def _synthesis(**overrides) -> Synthesis:
    defaults = dict(summary="Agreed", proposed_brief=_draft(), request="A fake door\nfor route sharing", opinions=[_opinion()])
    return Synthesis(**{**defaults, **overrides})


def _prototype(*questions: FounderQuestion) -> Prototype:
    return Prototype(
        screens=[Screen(name="Progress", purpose="p", states=["default"])],
        html_path="squad/design/c1/p.html",
        founder_questions=list(questions),
    )


def test_brief_note_is_markdown_a_person_reads():
    """An approved brief is a title, the decision, the owners by name, and one section per field"""
    frontmatter, body = _parse_note(brief_note(_record()))
    assert frontmatter == {
        "cycle_id": "c1",
        "schema_version": "1",
        "brief_id": "b1",
        "decided_at": DECIDED_AT.isoformat(),
        "data": "squad/briefs/b1.json",
    }
    assert body == (
        "# Brief\n\n"
        f"- **Decision:** ✅ Approved on {LOCAL:%Y-%m-%d %H:%M}\n"
        "- **Owners:** Growth PM, Product PM\n\n"
        "## Problem\n\nDispatch managers cannot share a route\n\n"
        "## Hypothesis\n\nIf we offer sharing, they will use it\n\n"
        "## Success metric\n\n20% click the call to action\n\n"
        "## Acceptance criteria\n\n- [ ] The page has one call to action\n- [ ] Clicks are counted\n"
    )


def test_brief_note_quotes_the_humans_notes():
    """The notes given with the approval are a blockquote, line by line"""
    assert "\n\n> Go ahead\n>\n> But keep it small\n\n## Problem" in brief_note(_record("Go ahead\n\nBut keep it small"))


def test_brief_note_in_portuguese():
    """With language pt-BR the labels and the date are Portuguese, and role names stay as the squad's"""
    note = brief_note(_record(), "pt-BR")
    assert f"- **Decisão:** ✅ Aprovado em {LOCAL:%d/%m/%Y %H:%M}" in note
    assert "- **Responsáveis:** Growth PM, Product PM" in note
    for heading in ("## Problema", "## Hipótese", "## Métrica de sucesso", "## Critérios de aceite"):
        assert heading in note


def test_decision_note_links_what_was_decided():
    """An approval names when it was given, the synthesis it was given on, and the brief it made"""
    note = decision_note(_decision(notes="Go ahead"), "c1", "squad/committee/c1/synthesis-2.md", "squad/briefs/b1.md")
    frontmatter, body = _parse_note(note)
    assert frontmatter == {
        "cycle_id": "c1",
        "schema_version": "1",
        "verdict": "approved",
        "decided_at": DECIDED_AT.isoformat(),
        "synthesis": "squad/committee/c1/synthesis-2.md",
        "brief": "squad/briefs/b1.md",
    }
    assert body == (
        "# Decision: ✅ Approved\n\n"
        f"- **When:** {LOCAL:%Y-%m-%d %H:%M}\n"
        "- **Synthesis:** `squad/committee/c1/synthesis-2.md`\n"
        "- **Brief:** `squad/briefs/b1.md`\n\n"
        "## Notes\n\nGo ahead\n"
    )


def test_decision_note_for_a_rejection_has_no_brief():
    """A rejection says so, in the squad's language, and names no brief"""
    note = decision_note(_decision("rejected"), "c1", "squad/committee/c1/synthesis-1.md", language="pt-BR")
    frontmatter, body = _parse_note(note)
    assert "brief" not in frontmatter and "Brief" not in body
    assert body.startswith("# Decisão: ❌ Rejeitado\n")
    assert body.endswith("## Notas\n\nSem notas.\n")


def test_synthesis_note_shows_everything_the_human_decides_on():
    """The synthesis note names roles as people read them and keeps each opinion's risks, questions and sources"""
    gap = KnowledgeGap(gap="Nobody was asked", questions=["Do they share?"], asked_by=["growth_pm", "pm_product"])
    raw = KnowledgeGap(gap="No interviews", questions=["Do they share?"], asked_by=["pm_product"])
    synthesis = _synthesis(
        divergences=[Divergence(topic="How long", positions={"growth_pm": "two weeks", "outsider": "a month"})],
        questions_for_human=["Is two weeks fine?", "Who owns it?"],
        gaps=[gap],
        raw_gaps=[raw],
        opinions=[_opinion(risks=["Small sample"], questions_for_human=["OK?"], sources=["interviews/a.md"])],
        rebuttals=[_opinion("pm_product", confidence="high")],
    )
    frontmatter, body = _parse_note(synthesis_note(synthesis, "c1", 2))
    assert frontmatter == {"cycle_id": "c1", "schema_version": "1", "version": "2", "roles": ["growth_pm"]}
    for expected in (
        "# Synthesis\n\n## Request\n\n> A fake door\n> for route sharing\n\n## Summary\n\nAgreed",
        "### How long\n\n- **Growth PM:** two weeks\n- **outsider:** a month",
        "## Questions for the human\n\n1. Is two weeks fine?\n2. Who owns it?",
        "### Nobody was asked\n\n- **Asked HX:** Do they share?\n- **Asked by:** Growth PM, Product PM",
        "## Gaps as HX reported them\n\n- No interviews _(Asked by: Product PM)_",
        "## Proposed brief\n\n**Owners:** Growth PM, Product PM\n\n### Problem\n\n",
        "### Acceptance criteria\n\n- [ ] The page has one call to action",
        "## Opinions\n\n### Growth PM\n\n**Confidence:** medium\n\nRun it for two weeks\n\n"
        "**Risks**\n\n- Small sample\n\n**Questions for the human**\n\n- OK?\n\n**Sources**\n\n- `interviews/a.md`",
        "## Replies\n\n### Product PM\n\n**Confidence:** high\n\nRun it for two weeks\n",
    ):
        assert expected in body


def test_synthesis_note_says_so_when_there_is_nothing_to_list():
    """A synthesis with no divergence, question or gap says None instead of leaving the section empty"""
    note = synthesis_note(_synthesis(), "c1", 1)
    assert "## Divergences\n\nNone." in note
    assert "## Questions for the human\n\nNone." in note
    assert "HX reported no gap during this round." in note
    assert "## Replies" not in note and "## Gaps as HX reported them" not in note
    assert "**Risks**" not in note and "**Sources**" not in note


def test_synthesis_note_in_portuguese():
    """With language pt-BR every heading and label of the synthesis note is Portuguese"""
    note = synthesis_note(_synthesis(rebuttals=[_opinion(confidence="low")]), "c1", 1, "pt-BR")
    for expected in (
        "# Síntese",
        "## Pedido",
        "## Resumo",
        "## Divergências\n\nNenhuma.",
        "## Perguntas para o humano\n\nNenhuma.",
        "## O que não sabemos\n\nO HX não reportou nenhuma lacuna nesta rodada.",
        "## Brief proposto\n\n**Responsáveis:**",
        "## Opiniões",
        "**Confiança:** média",
        "## Réplicas",
        "**Confiança:** baixa",
    ):
        assert expected in note


def test_founder_questions_note_leaves_room_for_each_answer():
    """questions.md has one section per question, with what was asked, the default, and an empty answer"""
    hx_gap = FounderQuestion(
        question="Do they use tablets?",
        context="Nobody was asked",
        origin="hx_gap",
        suggested_default="Phones only",
        hx_question="Which devices do users use?",
    )
    positioning = FounderQuestion(
        question="Which tone?",
        context="No brand note",
        origin="positioning",
        suggested_default="Friendly",
        marketing_question="What is our tone?",
    )
    frontmatter, body = _parse_note(founder_questions_note(_prototype(hx_gap, positioning), "c1"))
    assert frontmatter == {"cycle_id": "c1", "schema_version": "1", "prototype": "squad/design/c1/p.html"}
    assert body == (
        "# Questions for the founder\n\n"
        "**Prototype:** `squad/design/c1/p.html`\n\n"
        "## Do they use tablets?\n\nNobody was asked\n\n"
        "- **Origin:** HX had no answer\n"
        "- **Asked HX:** Which devices do users use?\n"
        "- **Suggested default:** Phones only\n"
        "- **Answer:**\n\n"
        "## Which tone?\n\nNo brand note\n\n"
        "- **Origin:** the Marketing PM had no answer\n"
        "- **Asked the Marketing PM:** What is our tone?\n"
        "- **Suggested default:** Friendly\n"
        "- **Answer:**\n"
    )


def test_founder_questions_note_without_questions_says_so():
    """A prototype with no founder question still gets a note, saying there is none, in the squad's language"""
    assert "No open questions." in founder_questions_note(_prototype(), "c1")
    note = founder_questions_note(_prototype(), "c1", "pt-BR")
    assert "# Perguntas para o founder\n\n**Protótipo:**" in note and "Nenhuma pergunta em aberto." in note
