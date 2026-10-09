import asyncio
import os
import re
from datetime import datetime, timezone

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import pytest

pytest.importorskip("pydantic_ai", reason="requires the 'ai' extra: uv sync --extra ai")

from pydantic_ai import Agent, ModelRetry
from pydantic_ai import models as pydantic_ai_models
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RunUsage

from pydantic_squads.product.assembly import (
    ProductSquad,
    _check_content_pack,
    _consult_pm_marketing,
    _register_consult_pm_marketing,
)
from pydantic_squads.product.contracts import (
    Backlog,
    Brief,
    BriefDraft,
    BriefRejection,
    ContentPack,
    ContentPiece,
    FounderQuestion,
    HumanDecision,
    MarketingGuidance,
    Prototype,
    Screen,
    Story,
)
from pydantic_squads.product.knowledge import MarkdownKnowledgeBase
from pydantic_squads.product.observability import SpanSink, load_cycle
from pydantic_squads.product.roles import PRODUCT_OWNER

pydantic_ai_models.ALLOW_MODEL_REQUESTS = False

TEST_CONTEXT = "A B2B tool for small logistics companies. Primary persona: dispatch manager."
TONE = "Which tone should the empty state use?"


def _kb(tmp_path) -> MarkdownKnowledgeBase:
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("docs/product-marketing.md", "Tone: plain and direct.")
    return kb


def _output(model):
    def turn(messages, info):
        title = type(model).__name__
        tool = next(t for t in info.output_tools if t.parameters_json_schema.get("title") == title)
        return ModelResponse(parts=[ToolCallPart(tool.name, model.model_dump(mode="json"))])

    return turn


def _tool(name: str, **args):
    return lambda messages, info: ModelResponse(parts=[ToolCallPart(name, args)])


def _run_dir(messages, kind: str) -> str:
    """The squad/<kind>/<cycle_id> directory the squad put in the agent's prompt."""
    for message in messages:
        for part in message.parts:
            match = re.search(rf"under '(squad/{kind}/[^']+)/'", str(getattr(part, "content", "")))
            if match:
                return match.group(1)
    raise AssertionError(f"no {kind} directory in the prompt")


def _squad_model(*, marketing=(), designer=(), social=(), offered: dict | None = None) -> FunctionModel:
    """Plays the PM Marketing, the Designer and Social Media, each from its own list of turns."""
    scripts = {"MarketingGuidance": iter(marketing), "Prototype": iter(designer), "ContentPack": iter(social)}

    def fn(messages, info):
        titles = {t.parameters_json_schema.get("title") for t in info.output_tools}
        kind = next(k for k in scripts if k in titles)
        if offered is not None:
            offered.setdefault(kind, sorted(t.name for t in info.function_tools))
        turn = next(scripts[kind], None)
        assert turn is not None, f"the {kind} agent was called more times than scripted"
        return turn(messages, info)

    return FunctionModel(fn)


def _answered(question: str = TONE) -> MarketingGuidance:
    return MarketingGuidance(
        question=question, answered=True, guidance="Plain and direct", sources=["docs/product-marketing.md"]
    )


def _unanswered(question: str = TONE) -> MarketingGuidance:
    return MarketingGuidance(question=question, answered=False, guidance="No note settles the tone")


# -- The PM Marketing as a query tool ----------------------------------------


def test_marketing_guidance_carries_the_callers_question_word_for_word(tmp_path):
    """consult_pm_marketing stamps the question asked onto the answer, whatever the model wrote there"""
    squad = ProductSquad(
        _kb(tmp_path), context=TEST_CONTEXT, model=_squad_model(marketing=[_output(_answered("something else"))])
    )
    guidance = asyncio.run(_consult_pm_marketing(squad._marketing, squad.kb, RunUsage(), TONE))
    assert guidance.question == TONE
    assert guidance.answered and guidance.sources == ["docs/product-marketing.md"]


def test_marketing_guidance_is_a_fresh_run_that_only_reads(tmp_path):
    """The PM Marketing answers from the question alone, with read tools only: no HX, no writing"""
    offered = {}
    seen = []

    def answer(messages, info):
        seen.append(messages)
        return _output(_answered())(messages, info)

    squad = ProductSquad(
        _kb(tmp_path), context=TEST_CONTEXT, model=_squad_model(marketing=[answer, answer], offered=offered)
    )
    asyncio.run(_consult_pm_marketing(squad._marketing, squad.kb, RunUsage(), TONE))
    asyncio.run(_consult_pm_marketing(squad._marketing, squad.kb, RunUsage(), "Which name?"))
    assert offered["MarketingGuidance"] == ["read_note", "search_notes"]
    assert [len(messages) for messages in seen] == [1, 1]


def test_marketing_guidance_must_cite_a_note_that_exists(tmp_path):
    """A source that is not in the knowledge base sends the answer back to the PM Marketing"""
    made_up = _answered().model_copy(update={"sources": ["docs/brand-book.md"]})
    squad = ProductSquad(
        _kb(tmp_path),
        context=TEST_CONTEXT,
        model=_squad_model(marketing=[_output(made_up), _output(_answered())]),
    )
    guidance = asyncio.run(_consult_pm_marketing(squad._marketing, squad.kb, RunUsage(), TONE))
    assert guidance.sources == ["docs/product-marketing.md"]


def test_marketing_run_is_collected_under_the_tool_call_that_asked(tmp_path):
    """A consultation's messages land in the caller's sink as a pm_marketing run"""
    squad = ProductSquad(_kb(tmp_path), context=TEST_CONTEXT, model=_squad_model(marketing=[_output(_answered())]))
    sink = SpanSink()
    asyncio.run(_consult_pm_marketing(squad._marketing, squad.kb, RunUsage(), TONE, tool_call_id="call-1", sink=sink))
    agent, messages = sink.nested_runs["call-1"]
    assert agent == "pm_marketing"
    assert messages[0].parts[-1].content == TONE


def test_consult_pm_marketing_not_registered_when_role_does_not_declare_it():
    """A role without consult_pm_marketing in Role.tools is not offered it"""
    captured = {}

    def fn(messages, info):
        captured["names"] = [t.name for t in info.function_tools]
        return ModelResponse(parts=[TextPart("ok")])

    po_agent = Agent(FunctionModel(fn), deps_type=str)
    _register_consult_pm_marketing(po_agent, PRODUCT_OWNER, Agent(FunctionModel(fn), deps_type=str))
    po_agent.run_sync("hi", deps="kb")
    assert captured["names"] == []


# -- Designer: brand questions go to the PM Marketing first ------------------


def _backlog() -> Backlog:
    return Backlog(stories=[Story(title="See progress", acceptance_criteria=["Shows the step"], needs_design=True)])


def _write_html(messages, info):
    path = f"{_run_dir(messages, 'design')}/prototype.html"
    return ModelResponse(parts=[ToolCallPart("write_note", {"path": path, "content": "<html></html>"})])


def _prototype(questions: list[FounderQuestion] | None = None):
    def turn(messages, info):
        prototype = Prototype(
            screens=[Screen(name="Progress", purpose="p", stories=["See progress"], states=["default"])],
            html_path=f"{_run_dir(messages, 'design')}/prototype.html",
            founder_questions=questions or [],
        )
        return _output(prototype)(messages, info)

    return turn


def _positioning(marketing_question: str = TONE) -> FounderQuestion:
    return FounderQuestion(
        question="Which tone?",
        context="The empty state needs a voice",
        origin="positioning",
        suggested_default="Plain",
        marketing_question=marketing_question,
    )


def test_brand_question_the_marketing_pm_answered_cannot_go_to_the_founder(tmp_path):
    """A positioning founder question is refused when the PM Marketing answered it from the knowledge base"""
    squad = ProductSquad(
        _kb(tmp_path),
        context=TEST_CONTEXT,
        model=_squad_model(
            marketing=[_output(_answered())],
            designer=[_write_html, _tool("consult_pm_marketing", question=TONE), _prototype([_positioning()]), _prototype()],
        ),
    )
    prototype = squad.design(_backlog())
    assert isinstance(prototype, Prototype)
    assert prototype.founder_questions == []


def test_brand_question_the_marketing_pm_could_not_answer_reaches_the_founder(tmp_path):
    """Only what the PM Marketing left unanswered becomes a positioning question, recorded with what was asked"""
    kb = _kb(tmp_path)
    squad = ProductSquad(
        kb,
        context=TEST_CONTEXT,
        model=_squad_model(
            marketing=[_output(_unanswered())],
            designer=[_write_html, _tool("consult_pm_marketing", question=TONE), _prototype([_positioning()])],
        ),
    )
    prototype = squad.design(_backlog())
    assert isinstance(prototype, Prototype)
    assert prototype.founder_questions == [_positioning()]
    note = kb.read(f"squad/design/{squad.cycle_id}/questions.md").content
    assert f"- **Asked the Marketing PM:** {TONE}" in note


def test_brand_question_never_put_to_the_marketing_pm_is_refused(tmp_path):
    """A Designer that keeps asking the founder about brand without consulting the PM Marketing gets no Prototype"""
    squad = ProductSquad(
        _kb(tmp_path),
        context=TEST_CONTEXT,
        model=_squad_model(designer=[_write_html, _prototype([_positioning()]), _prototype([_positioning()])]),
    )
    with pytest.raises(UnexpectedModelBehavior):
        squad.design(_backlog())


def test_open_brand_question_carries_over_to_a_revision_round(tmp_path):
    """A brand question the founder left open may stay in the revised prototype without asking again"""
    squad = ProductSquad(
        _kb(tmp_path),
        context=TEST_CONTEXT,
        model=_squad_model(
            marketing=[_output(_unanswered())],
            designer=[
                _write_html,
                _tool("consult_pm_marketing", question=TONE),
                _prototype([_positioning()]),
                _prototype([_positioning()]),  # the revision: no new consultation
            ],
        ),
    )
    squad.design(_backlog())
    revised = squad.design(_backlog(), answers={})
    assert isinstance(revised, Prototype)
    assert revised.founder_questions == [_positioning()]


def test_marketing_consultation_is_nested_under_the_designer_in_the_trace(tmp_path):
    """The PM Marketing's run shows in the trace as a child of the Designer's consult_pm_marketing span"""
    trace_dir = tmp_path / "traces"
    squad = ProductSquad(
        _kb(tmp_path / "vault"),
        context=TEST_CONTEXT,
        trace_dir=trace_dir,
        model=_squad_model(
            marketing=[_output(_answered())],
            designer=[_write_html, _tool("consult_pm_marketing", question=TONE), _prototype()],
        ),
    )
    squad.design(_backlog())
    _header, spans, _snapshot = load_cycle(trace_dir, squad.cycle_id)
    by_id = {span.span_id: span for span in spans}
    [marketing_call] = [s for s in spans if s.agent == "pm_marketing" and s.operation == "model_call"]
    parent = by_id[marketing_call.parent_span_id]
    assert (parent.agent, parent.operation) == ("designer", "tool:consult_pm_marketing")


# -- Social Media: produce_content() ------------------------------------------


def _brief() -> Brief:
    return Brief(
        problem="Dispatch managers do not know route sharing exists",
        hypothesis="A fake-door landing page shows whether they want it",
        success_metric="waitlist signups",
        acceptance_criteria=["The page has one call to action"],
        owner_roles=["pm_marketing"],
        human_decision=HumanDecision(verdict="approved", decided_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
    )


def _write_piece(name: str = "landing-page.md"):
    def turn(messages, info):
        path = f"{_run_dir(messages, 'content')}/{name}"
        return ModelResponse(parts=[ToolCallPart("write_note", {"path": path, "content": "# Share a route"})])

    return turn


def _pack(name: str = "landing-page.md", folder: str | None = None, open_questions: list[str] | None = None):
    def turn(messages, info):
        directory = folder or _run_dir(messages, "content")
        piece = ContentPiece(kind="landing_page", channel="web", title="Share a route", path=f"{directory}/{name}")
        return _output(ContentPack(pieces=[piece], open_questions=open_questions or []))(messages, info)

    return turn


def test_produce_content_writes_the_pieces_and_returns_the_pack(tmp_path):
    """produce_content() has Social Media write each piece under squad/content/<cycle_id>/ and list it"""
    kb = _kb(tmp_path)
    squad = ProductSquad(kb, context=TEST_CONTEXT, model=_squad_model(social=[_write_piece(), _pack()]))
    pack = squad.produce_content(_brief())
    assert isinstance(pack, ContentPack)
    [piece] = pack.pieces
    assert piece.path == f"squad/content/{squad.cycle_id}/landing-page.md"
    assert kb.read(piece.path).content == "# Share a route"


def test_produce_content_gives_social_media_the_brief(tmp_path):
    """Social Media's prompt carries the approved brief"""
    seen = []

    def write(messages, info):
        seen.append(messages[0].parts[-1].content)
        return _write_piece()(messages, info)

    squad = ProductSquad(_kb(tmp_path), context=TEST_CONTEXT, model=_squad_model(social=[write, _pack()]))
    squad.produce_content(_brief())
    assert _brief().hypothesis in seen[0]


def test_produce_content_needs_an_approved_brief(tmp_path):
    """A draft nobody approved is rejected before Social Media's model is called, and the trace shows it"""
    trace_dir = tmp_path / "traces"
    squad = ProductSquad(_kb(tmp_path / "vault"), context=TEST_CONTEXT, model=_squad_model(), trace_dir=trace_dir)
    draft = BriefDraft(**_brief().model_dump(exclude={"human_decision"}))
    rejection = squad.produce_content(draft)
    assert isinstance(rejection, BriefRejection)
    assert rejection.missing_fields == ["human_decision"]
    _header, [span], _snapshot = load_cycle(trace_dir, squad.cycle_id)
    assert (span.agent, span.operation, span.output_type) == ("social_media", "brief_validation", "BriefRejection")


def test_produce_content_refuses_a_piece_that_was_never_written(tmp_path):
    """A ContentPack listing a file that does not exist is sent back until the piece is written"""
    squad = ProductSquad(
        _kb(tmp_path), context=TEST_CONTEXT, model=_squad_model(social=[_pack(), _write_piece(), _pack()])
    )
    pack = squad.produce_content(_brief())
    assert isinstance(pack, ContentPack)


def test_social_media_takes_brand_doubts_to_the_marketing_pm(tmp_path):
    """Social Media can consult the PM Marketing, and lists what it could not answer as an open question"""
    offered = {}
    squad = ProductSquad(
        _kb(tmp_path),
        context=TEST_CONTEXT,
        model=_squad_model(
            marketing=[_output(_unanswered())],
            social=[_tool("consult_pm_marketing", question=TONE), _write_piece(), _pack(open_questions=[TONE])],
            offered=offered,
        ),
    )
    pack = squad.produce_content(_brief())
    assert pack.open_questions == [TONE]
    assert offered["ContentPack"] == ["consult_pm_marketing", "read_note", "search_notes", "write_note"]


def test_social_media_cannot_write_outside_the_content_folder(tmp_path):
    """Social Media's write_note is refused anywhere but squad/content/**"""
    kb = _kb(tmp_path)
    squad = ProductSquad(
        kb,
        context=TEST_CONTEXT,
        model=_squad_model(social=[_tool("write_note", path="docs/product-marketing.md", content="x"), _write_piece(), _pack()]),
    )
    squad.produce_content(_brief())
    assert kb.read("docs/product-marketing.md").content == "Tone: plain and direct."


def _piece(path: str) -> ContentPack:
    return ContentPack(pieces=[ContentPiece(kind="post", channel="linkedin", title="t", path=path)])


@pytest.mark.parametrize("path", ["squad/design/c1/post.md", "/etc/post.md", "squad/content/c1/../../docs/post.md"])
def test_check_content_pack_retries_on_a_piece_outside_the_content_dir(tmp_path, path):
    """_check_content_pack retries unless every piece is under this cycle's content dir"""
    with pytest.raises(ModelRetry, match="must be a file under"):
        _check_content_pack(_kb(tmp_path), "squad/content/c1", _piece(path))


def test_check_content_pack_normalizes_the_paths_it_accepts(tmp_path):
    """_check_content_pack returns the pack with each piece's path normalized"""
    kb = _kb(tmp_path)
    kb.write("squad/content/c1/post.md", "hello")
    checked = _check_content_pack(kb, "squad/content/c1", _piece("squad/content/c1/./post.md"))
    assert [piece.path for piece in checked.pieces] == ["squad/content/c1/post.md"]
