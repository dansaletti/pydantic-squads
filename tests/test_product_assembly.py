import asyncio
import os

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import pytest

pytest.importorskip("pydantic_ai", reason="requires the 'ai' extra: uv sync --extra ai")

from pydantic_ai import (
    Agent,
    ApprovalRequired,
    DeferredToolRequests,
    ModelRetry,
    RunUsage,
    Tool,
    models as pydantic_ai_models,
)
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from pydantic_squads import InteractionMode, Permissions, Role
from pydantic_squads.product.assembly import (
    ProductSquad,
    _consult_hx,
    _list_by_tag,
    _matches,
    _read_note,
    _search_notes,
    _sources_exist,
    _write_note,
)
from pydantic_squads.product.contracts import Backlog, Bet, Finding, FindingKind, HXAnswer, SendBack, Story
from pydantic_squads.product.knowledge import MarkdownKnowledgeBase

pydantic_ai_models.ALLOW_MODEL_REQUESTS = False


def _role(read: list[str] | None = None, write: list[str] | None = None, write_with_approval: list[str] | None = None) -> Role:
    return Role(
        id="tester",
        name="Tester",
        mission="m",
        responsibilities=["r"],
        out_of_scope=["o"],
        mode=InteractionMode.TASK,
        talks_to=["growth_pm"],
        permissions=Permissions(
            read=read if read is not None else ["**"],
            write=write or [],
            write_with_approval=write_with_approval or [],
        ),
        delivers="d",
    )


def _text(text: str):
    return lambda messages, info: ModelResponse(parts=[TextPart(text)])


def _call_tool(name: str, args: dict):
    return lambda messages, info: ModelResponse(parts=[ToolCallPart(name, args)])


def _call_output_tool(model):
    """Call whichever output tool matches `model`'s type (output_type may be a union)."""

    def turn(messages, info):
        title = type(model).__name__
        tool = next(t for t in info.output_tools if t.parameters_json_schema.get("title") == title)
        return ModelResponse(parts=[ToolCallPart(tool.name, model.model_dump(mode="json"))])

    return turn


def _scripted_model(*turns) -> FunctionModel:
    """A FunctionModel that plays back `turns` in order, one per model call."""
    state = {"n": 0}

    def fn(messages, info):
        i = state["n"]
        state["n"] += 1
        assert i < len(turns), f"scripted model called more times ({i + 1}) than turns provided ({len(turns)})"
        return turns[i](messages, info)

    return FunctionModel(fn)


# -- _matches / note tool functions (permission logic, no LLM involved) -----


def test_matches_returns_true_for_matching_glob():
    """_matches returns True when the path matches one of the patterns"""
    assert _matches("docs/x.md", ["docs/**"])


def test_matches_returns_false_when_nothing_matches():
    """_matches returns False when the path matches none of the patterns"""
    assert not _matches("other/x.md", ["docs/**"])


def test_search_notes_filters_by_read_permission(tmp_path):
    """search_notes only returns notes the role is allowed to read"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("public/a.md", "alpha content")
    kb.write("private/b.md", "alpha content too")
    role = _role(read=["public/**"])
    assert [n.path for n in _search_notes(role, kb, "alpha")] == ["public/a.md"]


def test_list_by_tag_filters_by_read_permission(tmp_path):
    """list_by_tag only returns notes the role is allowed to read"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("public/a.md", "---\ntags: [x]\n---\nbody")
    kb.write("private/b.md", "---\ntags: [x]\n---\nbody")
    role = _role(read=["public/**"])
    assert [n.path for n in _list_by_tag(role, kb, "x")] == ["public/a.md"]


def test_read_note_allowed(tmp_path):
    """read_note returns the note when the path is covered by the read permission"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("public/a.md", "alpha")
    assert _read_note(_role(read=["public/**"]), kb, "public/a.md").content == "alpha"


def test_read_note_denied(tmp_path):
    """read_note raises ModelRetry when the path is outside the read permission"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("private/b.md", "beta")
    with pytest.raises(ModelRetry):
        _read_note(_role(read=["public/**"]), kb, "private/b.md")


def test_write_note_free_write(tmp_path):
    """write_note writes directly to a path covered by the write permission"""
    kb = MarkdownKnowledgeBase(tmp_path)
    role = _role(write=["squad/bets/**"])
    result = _write_note(role, kb, "squad/bets/x.md", "content", approved=False)
    assert "wrote" in result
    assert kb.read("squad/bets/x.md").content == "content"


def test_write_note_requires_approval(tmp_path):
    """write_note raises ApprovalRequired for an unapproved write_with_approval path"""
    kb = MarkdownKnowledgeBase(tmp_path)
    role = _role(write_with_approval=["docs/**"])
    with pytest.raises(ApprovalRequired):
        _write_note(role, kb, "docs/x.md", "content", approved=False)


def test_write_note_approved_writes(tmp_path):
    """write_note writes once a write_with_approval path has been approved"""
    kb = MarkdownKnowledgeBase(tmp_path)
    role = _role(write_with_approval=["docs/**"])
    result = _write_note(role, kb, "docs/x.md", "content", approved=True)
    assert "approved" in result
    assert kb.read("docs/x.md").content == "content"


def test_write_note_denied(tmp_path):
    """write_note raises ModelRetry for a path covered by no write permission"""
    kb = MarkdownKnowledgeBase(tmp_path)
    with pytest.raises(ModelRetry):
        _write_note(_role(), kb, "anywhere/x.md", "content", approved=False)


# -- HX output validator ------------------------------------------------


def test_sources_exist_passes_when_source_present(tmp_path):
    """The HX output validator accepts an answer whose sources all exist"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("notes/a.md", "evidence")
    answer = HXAnswer(
        question="q",
        summary="s",
        findings=[Finding(claim="c", kind=FindingKind.EVIDENCE, sources=["notes/a.md"])],
    )
    assert _sources_exist(kb, answer) is answer


def test_sources_exist_retries_when_source_missing(tmp_path):
    """The HX output validator raises ModelRetry when a cited source does not exist"""
    kb = MarkdownKnowledgeBase(tmp_path)
    answer = HXAnswer(
        question="q",
        summary="s",
        findings=[Finding(claim="c", kind=FindingKind.EVIDENCE, sources=["notes/missing.md"])],
    )
    with pytest.raises(ModelRetry):
        _sources_exist(kb, answer)


def test_sources_exist_passes_through_deferred_requests(tmp_path):
    """The HX output validator does not inspect a DeferredToolRequests output"""
    kb = MarkdownKnowledgeBase(tmp_path)
    deferred = DeferredToolRequests()
    assert _sources_exist(kb, deferred) is deferred


# -- consult_hx delegation ------------------------------------------------


def test_consult_hx_passes_usage_through(tmp_path):
    """consult_hx forwards the caller's usage object into the nested HX run"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("interviews/a.md", "evidence text")
    answer = HXAnswer(
        question="q",
        summary="s",
        findings=[Finding(claim="c", kind=FindingKind.EVIDENCE, sources=["interviews/a.md"])],
    )
    hx_agent = Agent(
        _scripted_model(_call_output_tool(answer)),
        deps_type=MarkdownKnowledgeBase,
        output_type=[HXAnswer, DeferredToolRequests],
    )
    usage = RunUsage()
    result = asyncio.run(_consult_hx(hx_agent, kb, usage, "q"))
    assert result == answer
    assert usage.requests == 1


def test_consult_hx_raises_when_hx_defers():
    """consult_hx raises ModelRetry, not a type error, when HX itself needs approval"""

    def dummy() -> str:
        return "unused"

    hx_agent = Agent(
        _scripted_model(_call_tool("dummy", {})),
        deps_type=str,
        output_type=[HXAnswer, DeferredToolRequests],
        tools=[Tool(dummy, requires_approval=True)],
    )
    with pytest.raises(ModelRetry):
        asyncio.run(_consult_hx(hx_agent, "kb", RunUsage(), "q"))


# -- ProductSquad: chat() --------------------------------------------------


def test_chat_returns_growth_pm_reply(tmp_path):
    """chat() sends the message to the Growth PM and returns its text reply"""
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(kb, model=_scripted_model(_text("Hi founder, what's on your mind?")))
    assert squad.chat("Hey") == "Hi founder, what's on your mind?"


def test_chat_writes_note_in_write_glob(tmp_path):
    """The Growth PM writes freely to a path covered by its write permission"""
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(
        kb,
        model=_scripted_model(
            _call_tool("write_note", {"path": "squad/bets/x.md", "content": "draft"}),
            _text("Saved the draft."),
        ),
    )
    assert squad.chat("Save this bet draft") == "Saved the draft."
    assert kb.read("squad/bets/x.md").content == "draft"


def test_chat_write_outside_permissions_is_denied_and_retried(tmp_path):
    """A write outside every permission glob triggers a retry the model can recover from"""
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(
        kb,
        model=_scripted_model(
            _call_tool("write_note", {"path": "elsewhere/x.md", "content": "nope"}),
            _text("Sorry, I can't write there."),
        ),
    )
    assert squad.chat("Save this somewhere weird") == "Sorry, I can't write there."
    assert not (tmp_path / "elsewhere" / "x.md").exists()


def test_chat_can_search_list_and_read_notes(tmp_path):
    """The Growth PM can search, list by tag and read notes through its tools"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("notes/a.md", "---\ntags: [x]\n---\nalpha content")
    squad = ProductSquad(
        kb,
        model=_scripted_model(
            _call_tool("search_notes", {"query": "alpha"}),
            _call_tool("list_by_tag", {"tag": "x"}),
            _call_tool("read_note", {"path": "notes/a.md"}),
            _text("Found it."),
        ),
    )
    assert squad.chat("Look into alpha") == "Found it."


def test_chat_write_requires_approval_then_resumes(tmp_path):
    """A write to a write_with_approval path defers, then resumes once approved"""
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(
        kb,
        model=_scripted_model(
            _call_tool("write_note", {"path": "docs/context.md", "content": "new context"}),
            _text("Wrote it after approval."),
        ),
    )
    pending = squad.chat("Update the docs")
    assert isinstance(pending, DeferredToolRequests)
    assert pending.approvals[0].tool_name == "write_note"

    reply = squad.chat(deferred_tool_results=pending.build_results(approve_all=True))
    assert reply == "Wrote it after approval."
    assert kb.read("docs/context.md").content == "new context"


def test_consult_hx_delegates_to_hx_agent(tmp_path):
    """The Growth PM's consult_hx tool runs the HX agent and returns its cited findings"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("interviews/a.md", "users get stuck at step 3")
    answer = HXAnswer(
        question="Why do users churn?",
        summary="Step 3 confuses users",
        findings=[Finding(claim="Users get stuck at step 3", kind=FindingKind.EVIDENCE, sources=["interviews/a.md"])],
    )
    squad = ProductSquad(
        kb,
        model=_scripted_model(
            _call_tool("consult_hx", {"question": "Why do users churn?"}),
            _call_output_tool(answer),
            _text("HX says step 3 confuses users."),
        ),
    )
    assert squad.chat("Why are users churning?") == "HX says step 3 confuses users."


# -- ProductSquad: close_bet() / submit_bet() ------------------------------


def _bet(**overrides) -> Bet:
    defaults = dict(
        hypothesis="Shortening onboarding lifts activation",
        metric="activation_rate",
        expected_impact="+5pp",
        scope=["Signup wizard"],
        out_of_scope=["Payments"],
    )
    return Bet(**{**defaults, **overrides})


def test_close_bet_forces_structured_bet_output(tmp_path):
    """close_bet() asks the Growth PM to produce a structured Bet"""
    kb = MarkdownKnowledgeBase(tmp_path)
    bet = _bet()
    squad = ProductSquad(kb, model=_scripted_model(_call_output_tool(bet)))
    assert squad.close_bet() == bet


def test_submit_bet_returns_backlog(tmp_path):
    """submit_bet() hands the bet to the Product Owner and returns its Backlog"""
    kb = MarkdownKnowledgeBase(tmp_path)
    backlog = Backlog(stories=[Story(title="Shorter wizard", acceptance_criteria=["3 steps"])])
    squad = ProductSquad(kb, model=_scripted_model(_call_output_tool(backlog)))
    assert squad.submit_bet(_bet()) == backlog


def test_submit_bet_relays_send_back_to_growth_pm(tmp_path):
    """A SendBack is relayed to the Growth PM, which revises the bet for a second attempt"""
    send_back = SendBack(reason="Scope is unclear", questions=["Which platform?"])
    revised_bet = _bet(scope=["Signup wizard", "web only"])
    backlog = Backlog(stories=[Story(title="Story", acceptance_criteria=["done"])])
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(
        kb,
        model=_scripted_model(
            _call_output_tool(send_back),
            _call_output_tool(revised_bet),
            _call_output_tool(backlog),
        ),
    )
    assert squad.submit_bet(_bet()) == backlog


def test_submit_bet_returns_deferred_when_revision_needs_approval(tmp_path):
    """submit_bet() surfaces a DeferredToolRequests if revising the bet needs approval"""
    send_back = SendBack(reason="Scope is unclear", questions=["Which platform?"])
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(
        kb,
        model=_scripted_model(
            _call_output_tool(send_back),
            _call_tool("write_note", {"path": "docs/context.md", "content": "notes"}),
        ),
    )
    result = squad.submit_bet(_bet())
    assert isinstance(result, DeferredToolRequests)


def test_submit_bet_returns_last_send_back_when_budget_exhausted(tmp_path):
    """submit_bet() gives up and returns the final SendBack after max_send_backs rounds"""
    send_back = SendBack(reason="Still unclear", questions=["?"])
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(
        kb,
        model=_scripted_model(
            _call_output_tool(send_back),
            _call_output_tool(_bet()),
            _call_output_tool(send_back),
        ),
        max_send_backs=1,
    )
    assert squad.submit_bet(_bet()) == send_back
