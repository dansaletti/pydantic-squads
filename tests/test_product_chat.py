import io
import os
import re

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import pytest

pytest.importorskip("pydantic_ai", reason="requires the 'ai' extra: uv sync --extra ai")
pytest.importorskip("rich", reason="requires the 'observability' extra: uv sync --extra observability")

from pydantic_ai import models as pydantic_ai_models
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from rich.console import Console

from pydantic_squads.product.assembly import ProductSquad
from pydantic_squads.product.chat import ChatSession, synthesis_markdown
from pydantic_squads.product.contracts import (
    Backlog,
    BriefDraft,
    BriefRejection,
    ContentPack,
    ContentPiece,
    Divergence,
    Finding,
    FindingKind,
    FounderQuestion,
    HXAnswer,
    OpinionDraft,
    Prototype,
    Screen,
    SendBack,
    Story,
    Synthesis,
    SynthesisDraft,
    Triage,
)
from pydantic_squads.product.knowledge import MarkdownKnowledgeBase

pydantic_ai_models.ALLOW_MODEL_REQUESTS = False

BRIEF = BriefDraft(
    problem="Managers do not know route sharing exists",
    hypothesis="A fake door shows whether they want it",
    success_metric="waitlist signups",
    acceptance_criteria=["One call to action"],
    owner_roles=["growth_pm"],
)


def _output(model):
    def turn(messages, info):
        title = type(model).__name__
        tool = next(t for t in info.output_tools if t.parameters_json_schema.get("title") == title)
        return ModelResponse(parts=[ToolCallPart(tool.name, model.model_dump(mode="json"))])

    return turn


def _tool(name: str, **args):
    return lambda messages, info: ModelResponse(parts=[ToolCallPart(name, args)])


def _text(text: str):
    return lambda messages, info: ModelResponse(parts=[TextPart(text)])


def _run_dir(messages, kind: str) -> str:
    for message in messages:
        for part in message.parts:
            match = re.search(rf"under '(squad/{kind}/[^']+)/'", str(getattr(part, "content", "")))
            if match:
                return match.group(1)
    raise AssertionError(f"no {kind} directory in the prompt")


def _write(kind: str, name: str):
    def turn(messages, info):
        path = f"{_run_dir(messages, kind)}/{name}"
        return ModelResponse(parts=[ToolCallPart("write_note", {"path": path, "content": "<html></html>"})])

    return turn


def _prototype(questions: list[FounderQuestion] | None = None):
    def turn(messages, info):
        prototype = Prototype(
            screens=[Screen(name="Landing", purpose="Collect signups", stories=["Landing page"], states=["default"])],
            html_path=f"{_run_dir(messages, 'design')}/p.html",
            founder_questions=questions or [],
        )
        return _output(prototype)(messages, info)

    return turn


def _pack(open_questions: list[str] | None = None):
    def turn(messages, info):
        piece = ContentPiece(kind="post", channel="instagram", title="Teaser", path=f"{_run_dir(messages, 'content')}/post.md")
        return _output(ContentPack(pieces=[piece], open_questions=open_questions or []))(messages, info)

    return turn


class Squad:
    """A fake model for the whole squad, each agent played from its own list of turns."""

    def __init__(self, **scripts):
        defaults = {
            "chat": [],
            "Triage": [_output(Triage(request="A fake-door page", roles=["growth_pm"], rationale="Growth owns it"))],
            "OpinionDraft": [_output(OpinionDraft(recommendation="Run it", confidence="medium"))] * 4,
            "SynthesisDraft": [_output(SynthesisDraft(summary="Run the test", proposed_brief=BRIEF))] * 4,
            "HXAnswer": [_output(HXAnswer(question="q", summary="s", findings=[Finding(claim="No data", kind=FindingKind.GAP)]))],
            "Backlog": [_output(Backlog(stories=[Story(title="Landing page", acceptance_criteria=["One CTA"], needs_design=True)]))],
            "Prototype": [],
            "ContentPack": [],
        }
        self.scripts = {kind: iter(turns) for kind, turns in {**defaults, **scripts}.items()}

    def __call__(self, messages, info):
        titles = {t.parameters_json_schema.get("title") for t in info.output_tools}
        kind = next((k for k in self.scripts if k in titles), "chat")
        return next(self.scripts[kind])(messages, info)


def _session(tmp_path, script: Squad, lines: list[str] | None = None, *, trace: bool = False):
    """A session on a fake squad, with its output captured and its input scripted."""
    out = io.StringIO()
    answers = iter(lines or [])

    def ask(prompt: str) -> str:
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    def make_squad() -> ProductSquad:
        return ProductSquad(
            MarkdownKnowledgeBase(tmp_path / "vault"),
            model=FunctionModel(script),
            context="ctx",
            trace_dir=tmp_path / "traces" if trace else None,
        )

    session = ChatSession(make_squad, console=Console(file=out, width=160, force_terminal=False), ask=ask)
    return session, out


def _approved(tmp_path, script: Squad, lines: list[str] | None = None):
    session, out = _session(tmp_path, script, lines)
    session.handle("/review A fake-door page")
    session.handle("/approve go ahead")
    return session, out


# -- the conversation and the gate -------------------------------------------


def test_a_line_of_text_goes_to_the_facilitator(tmp_path):
    """Plain text is sent to the Facilitator and its reply is shown"""
    session, out = _session(tmp_path, Squad(chat=[_text("Who is it for?")]))
    assert session.handle("I want a fake door") is True
    assert "Who is it for?" in out.getvalue() and "Facilitator" in out.getvalue()


def test_review_shows_the_synthesis_and_the_decisions_open(tmp_path):
    """/review runs the round and shows the synthesis with how to decide"""
    session, out = _session(tmp_path, Squad())
    session.handle("/review A fake-door page")
    shown = out.getvalue()
    assert "Run the test" in shown and "Proposed brief" in shown
    assert "Decide: /approve [NOTES], /adjust NOTES or /reject REASON." in shown
    assert f"squad/committee/{session.squad.cycle_id}/" in shown


def test_close_takes_the_conversation_to_the_committee(tmp_path):
    """/close after a conversation shows the synthesis"""
    session, out = _session(tmp_path, Squad(chat=[_text("Who is it for?")]))
    session.handle("I want a fake door")
    session.handle("/close")
    assert "Synthesis" in out.getvalue()


def test_review_needs_a_text(tmp_path):
    """/review with nothing after it shows its usage and calls no model"""
    session, out = _session(tmp_path, Squad(Triage=[]))
    session.handle("/review")
    assert "Usage: /review TEXT" in out.getvalue()


def test_adjust_then_approve_gives_the_session_a_brief(tmp_path):
    """/adjust redoes the synthesis and /approve keeps the Brief for the next commands"""
    session, out = _session(tmp_path, Squad())
    session.handle("/review A fake-door page")
    session.handle("/adjust shorter")
    session.handle("/approve go ahead")
    assert session.brief is not None and session.brief.human_decision.notes == "go ahead"
    assert out.getvalue().count("Proposed brief") == 2
    assert "Approved." in out.getvalue()


def test_reject_leaves_no_brief(tmp_path):
    """/reject ends the request and the session holds no Brief"""
    session, out = _session(tmp_path, Squad())
    session.handle("/review A fake-door page")
    session.handle("/reject not now")
    assert session.brief is None and "Rejected." in out.getvalue()


def test_a_command_out_of_order_is_explained_not_raised(tmp_path):
    """/approve with nothing to approve says why and keeps the session going"""
    session, out = _session(tmp_path, Squad())
    assert session.handle("/approve") is True
    assert "Cannot do that now: approve() needs a synthesis" in out.getvalue()


def test_a_model_failure_does_not_end_the_session(tmp_path):
    """An error from the model is shown and the session carries on"""

    def broken(messages, info):
        raise RuntimeError("the model is down")

    session, out = _session(tmp_path, Squad(chat=[broken]))
    assert session.handle("hello") is True
    assert "the model is down" in out.getvalue()


def test_unknown_commands_blank_lines_and_help(tmp_path):
    """An unknown command points to /help, a blank line does nothing, and /help lists the commands"""
    session, out = _session(tmp_path, Squad())
    session.handle("/bogus")
    session.handle("   ")
    session.handle("/help")
    assert "Unknown command /bogus. See /help." in out.getvalue()
    assert "/approve [NOTES]" in out.getvalue()


def test_synthesis_markdown_shows_divergences_gaps_and_replies():
    """The synthesis lists each position, each gap with who asked, and marks a reply"""
    from pydantic_squads.product.contracts import KnowledgeGap, Opinion

    opinion = Opinion(role="growth_pm", recommendation="Two weeks", confidence="low")
    synthesis = Synthesis(
        request="r",
        summary="They disagree",
        divergences=[Divergence(topic="Duration", positions={"growth_pm": "two weeks", "pm_product": "a month"})],
        questions_for_human=["Is two weeks fine?"],
        proposed_brief=BRIEF,
        opinions=[opinion],
        rebuttals=[opinion.model_copy(update={"recommendation": "Three weeks"})],
        gaps=[KnowledgeGap(gap="No usage data", questions=["Do they share?"], asked_by=["growth_pm"])],
    )
    text = synthesis_markdown(synthesis)
    for expected in (
        "- _pm_product_: a month",
        "- No usage data _(asked by growth_pm)_",
        "- Is two weeks fine?",
        "**growth_pm** (reply) _(low confidence)_: Three weeks",
    ):
        assert expected in text
    quiet = synthesis_markdown(synthesis.model_copy(update={"divergences": [], "gaps": [], "questions_for_human": []}))
    assert "### Divergences\n\nNone." in quiet and "HX reported no gap." in quiet and "- none" in quiet


# -- approving a write --------------------------------------------------------


def test_a_write_that_needs_approval_asks_and_then_writes(tmp_path):
    """A protected write is shown, and written once the human says yes"""
    script = Squad(chat=[_tool("write_note", path="docs/request.md", content="the request"), _text("Saved.")])
    session, out = _session(tmp_path, script, ["y"])
    session.handle("save this")
    assert "Approval needed: write_note docs/request.md" in out.getvalue() and "the request" in out.getvalue()
    assert session.squad.kb.read("docs/request.md").content == "the request"


@pytest.mark.parametrize("reason, told", [("wrong folder", "wrong folder"), ("", "The human denied this write.")])
def test_a_denied_write_tells_the_agent_why(tmp_path, reason, told):
    """Saying no asks for a reason, and the agent is told it (or that the human denied the write)"""
    seen = []

    def after(messages, info):
        seen.append(str(messages[-1].parts[0].content))
        return _text("Understood.")(messages, info)

    script = Squad(chat=[_tool("write_note", path="docs/request.md", content="x"), after])
    session, _out = _session(tmp_path, script, ["n", reason])
    session.handle("save this")
    assert told in seen[0]
    assert not (tmp_path / "vault" / "docs" / "request.md").exists()


# -- after the gate -----------------------------------------------------------


def test_submit_and_content_need_an_approved_brief(tmp_path):
    """/submit and /content before /approve say what to do first"""
    session, out = _session(tmp_path, Squad())
    session.handle("/submit")
    session.handle("/content")
    assert out.getvalue().count("There is no approved brief yet") == 2


def test_submit_shows_the_backlog(tmp_path):
    """/submit shows the Product Owner's backlog and keeps it for /design"""
    stories = [
        Story(title="Landing page", acceptance_criteria=["One CTA"], needs_design=True),
        Story(title="Store signups", acceptance_criteria=["Saved"], needs_design=False),
    ]
    session, out = _approved(tmp_path, Squad(Backlog=[_output(Backlog(stories=stories))]))
    session.handle("/submit")
    assert session.backlog is not None
    assert "Landing page (needs design)" in out.getvalue() and "Store signups (no design)" in out.getvalue()


def test_submit_shows_a_product_owner_rejection(tmp_path):
    """A brief the Product Owner rejects is shown with its reason, and there is no backlog"""
    rejection = BriefRejection(missing_fields=["success_metric"], reason="The metric has no baseline")
    session, out = _approved(tmp_path, Squad(Backlog=[_output(rejection)]))
    session.handle("/submit")
    assert session.backlog is None
    assert "The metric has no baseline" in out.getvalue() and "success_metric" in out.getvalue()


@pytest.mark.parametrize("open_questions", [[], ["Which tone?"]])
def test_content_lists_the_pieces(tmp_path, open_questions):
    """/content lists each piece with its path, and the open questions when there are any"""
    script = Squad(ContentPack=[_write("content", "post.md"), _pack(open_questions)])
    session, out = _approved(tmp_path, script)
    session.handle("/content")
    assert "Teaser (post, instagram)" in out.getvalue()
    assert ("Which tone?" in out.getvalue()) is bool(open_questions)


def test_design_needs_a_backlog(tmp_path):
    """/design before /submit says so"""
    session, out = _approved(tmp_path, Squad())
    session.handle("/design")
    assert "There is no backlog yet: /submit first." in out.getvalue()


def test_design_with_nothing_to_design(tmp_path):
    """/design on a backlog with no story that needs design says there is nothing to do"""
    backlog = Backlog(stories=[Story(title="Store signups", acceptance_criteria=["Saved"], needs_design=False)])
    session, out = _approved(tmp_path, Squad(Backlog=[_output(backlog)]))
    session.handle("/submit")
    session.handle("/design")
    assert "No story in the backlog needs design." in out.getvalue()


def test_design_shows_a_send_back(tmp_path):
    """A backlog the Designer sends back is shown with its reason and questions"""
    send_back = SendBack(reason="Too vague to draw", questions=["Which page?"])
    session, out = _approved(tmp_path, Squad(Prototype=[_output(send_back)]))
    session.handle("/submit")
    session.handle("/design")
    assert "Too vague to draw" in out.getvalue() and "Which page?" in out.getvalue()


def test_design_asks_the_prototypes_questions_and_revises_with_the_answers(tmp_path):
    """The prototype's questions are asked; an answer triggers one revision round, Enter keeps the default"""
    question = FounderQuestion(
        question="Which headline?", context="No note says", origin="hx_gap", suggested_default="Plain", hx_question="q"
    )
    script = Squad(Prototype=[_write("design", "p.html"), _prototype([question]), _prototype([question])])
    session, out = _approved(tmp_path, script, ["Bold", ""])
    session.handle("/submit")
    session.handle("/design")
    shown = out.getvalue()
    assert shown.count("Prototype") == 2 and "1. Which headline?" in shown
    assert f"squad/design/{session.squad.cycle_id}/p.html" in shown


# -- cost, gantt, resume, leaving --------------------------------------------


def test_cost_and_gantt_show_the_cycle(tmp_path):
    """/cost shows the per-agent table, and /gantt the chart followed by the same table"""
    session, out = _session(tmp_path, Squad())
    session.handle("/cost")
    assert "Nothing has run yet." in out.getvalue()
    session.handle("/review A fake-door page")
    session.handle("/gantt")
    shown = out.getvalue()
    assert "fan_out" in shown and "Cost of the current cycle" in shown
    assert "growth_pm" in shown and "total" in shown and "estimate at API list prices" in shown


def test_resume_continues_an_earlier_cycle(tmp_path):
    """/resume loads another cycle's conversation into a fresh squad and drops the brief"""
    first, _out = _session(tmp_path, Squad(chat=[_text("Who is it for?")]), trace=True)
    first.handle("I want a fake door")
    cycle_id = first.squad.cycle_id

    session, out = _session(tmp_path, Squad(), trace=True)
    session.handle("/resume")
    session.handle("/resume nope")
    session.handle(f"/resume {cycle_id}")
    shown = out.getvalue()
    assert "Usage: /resume CYCLE_ID" in shown and "No trace found for cycle nope." in shown
    assert session.squad.cycle_id == cycle_id and f"Conversation of cycle {cycle_id} resumed." in shown


def test_resume_without_a_trace_dir_is_explained(tmp_path):
    """/resume on a session with no trace directory says what it needs"""
    session, out = _session(tmp_path, Squad())
    session.handle("/resume abc")
    assert "Cannot do that now: resume() needs trace_dir" in out.getvalue()


def test_run_reads_until_quit_and_then_shows_the_cost(tmp_path):
    """run() shows the commands, handles each line, and on /quit shows the cost and the cycle"""
    session, out = _session(tmp_path, Squad(chat=[_text("Who is it for?")]), ["hello", "/quit", "never read"])
    session.run()
    shown = out.getvalue()
    assert "pydantic-squads chat" in shown and "Who is it for?" in shown
    assert "Cost of the current cycle" in shown and f"Cycle: {session.squad.cycle_id}" in shown


def test_run_ends_quietly_when_input_ends(tmp_path):
    """run() with no input at all ends without a cycle to report"""
    session, out = _session(tmp_path, Squad(), [])
    session.run()
    assert "Nothing has run yet." in out.getvalue() and "Cycle:" not in out.getvalue()
