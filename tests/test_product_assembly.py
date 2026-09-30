import asyncio
import json
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
    UsageLimitExceeded,
    UsageLimits,
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
    _normalize_path,
    _path_allowed,
    _read_note,
    _register_consult_hx,
    _register_note_tools,
    _search_notes,
    _sources_exist,
    _write_note,
)
from pydantic_squads.product.contracts import Backlog, Bet, Finding, FindingKind, HXAnswer, Revision, SendBack, Story
from pydantic_squads.product.knowledge import MarkdownKnowledgeBase
from pydantic_squads.product.roles import GROWTH_PM, HX, PRODUCT_OWNER

pydantic_ai_models.ALLOW_MODEL_REQUESTS = False

TEST_CONTEXT = "A B2B tool for small logistics companies. Primary persona: dispatch manager."


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


def test_read_note_missing_note_raises_model_retry_not_file_not_found_error(tmp_path):
    """read_note converts a missing note into ModelRetry, never a raw FileNotFoundError"""
    kb = MarkdownKnowledgeBase(tmp_path)
    with pytest.raises(ModelRetry):
        _read_note(_role(read=["**"]), kb, "public/missing.md")


def test_read_note_directory_raises_model_retry_not_os_error(tmp_path):
    """read_note converts a directory matching the path into ModelRetry, never a raw OSError"""
    kb = MarkdownKnowledgeBase(tmp_path)
    (tmp_path / "adir.md").mkdir()
    with pytest.raises(ModelRetry):
        _read_note(_role(read=["**"]), kb, "adir.md")


def test_read_note_symlink_escaping_root_raises_model_retry_not_value_error(tmp_path):
    """read_note converts a symlink escaping the vault into ModelRetry, never a raw ValueError"""
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret")
    kb = MarkdownKnowledgeBase(tmp_path)
    (tmp_path / "escape.md").symlink_to(outside / "secret.md")
    with pytest.raises(ModelRetry):
        _read_note(_role(read=["**"]), kb, "escape.md")


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


def test_growth_pm_write_note_requires_approval_for_assumptions(tmp_path):
    """The real Growth PM role requires approval to write to assumptions/** (ADR 0004)"""
    kb = MarkdownKnowledgeBase(tmp_path)
    with pytest.raises(ApprovalRequired):
        _write_note(GROWTH_PM, kb, "assumptions/x.md", "content", approved=False)
    result = _write_note(GROWTH_PM, kb, "assumptions/x.md", "content", approved=True)
    assert "approved" in result
    assert kb.read("assumptions/x.md").content == "content"


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


# -- path normalization / traversal ---------------------------------------


def test_normalize_path_resolves_dot_dot_segments():
    """_normalize_path collapses '..' segments before any glob check happens"""
    assert _normalize_path("squad/bets/../../docs/x.md") == "docs/x.md"


def test_normalize_path_resolves_dot_segments():
    """_normalize_path drops './' segments"""
    assert _normalize_path("./docs/x.md") == "docs/x.md"


def test_normalize_path_rejects_absolute_path():
    """_normalize_path rejects an absolute path"""
    assert _normalize_path("/etc/passwd") is None


def test_normalize_path_rejects_traversal_above_root():
    """_normalize_path rejects '..' that would escape the vault root"""
    assert _normalize_path("../outside.md") is None


def test_write_note_traversal_requires_approval_not_free_write(tmp_path):
    """A write disguised with '../' traversal is checked against its real, normalized target"""
    kb = MarkdownKnowledgeBase(tmp_path)
    role = _role(write=["squad/bets/**"], write_with_approval=["docs/**"])
    with pytest.raises(ApprovalRequired):
        _write_note(role, kb, "squad/bets/../../docs/x.md", "content", approved=False)
    assert not (tmp_path / "docs" / "x.md").exists()


def test_write_note_traversal_writes_to_normalized_path_once_approved(tmp_path):
    """Once approved, a traversal path writes to its normalized target, not the raw one"""
    kb = MarkdownKnowledgeBase(tmp_path)
    role = _role(write_with_approval=["docs/**"])
    _write_note(role, kb, "squad/bets/../../docs/x.md", "content", approved=True)
    assert kb.read("docs/x.md").content == "content"


def test_write_note_absolute_path_rejected(tmp_path):
    """write_note rejects an absolute path even if it looks like it matches a glob"""
    kb = MarkdownKnowledgeBase(tmp_path)
    role = _role(write=["**"])
    with pytest.raises(ModelRetry):
        _write_note(role, kb, "/etc/passwd", "content", approved=False)


def test_read_note_traversal_denied(tmp_path):
    """A read disguised with '../' traversal is checked against its real, normalized target"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("docs/x.md", "secret")
    role = _role(read=["squad/bets/**"])
    with pytest.raises(ModelRetry):
        _read_note(role, kb, "squad/bets/../../docs/x.md")


def test_path_allowed_normalizes_before_matching():
    """_path_allowed (used by search_notes/list_by_tag) checks the normalized path"""
    assert not _path_allowed("squad/bets/../../docs/x.md", ["squad/bets/**"])
    assert _path_allowed("squad/bets/../../docs/x.md", ["docs/**"])


# -- tool registration matches Role.tools ----------------------------------


def _registered_tool_names(role: Role) -> list[str]:
    """Register `role`'s note tools on a fresh agent and return what got registered."""
    captured = {}

    def fn(messages, info):
        captured["names"] = sorted(t.name for t in info.function_tools)
        return ModelResponse(parts=[TextPart("ok")])

    agent = Agent(FunctionModel(fn), deps_type=str)
    _register_note_tools(agent, role)
    agent.run_sync("hi", deps="kb")
    return captured["names"]


def test_growth_pm_registers_exactly_its_declared_note_tools():
    """The Growth PM's registered note tools match Role.tools exactly (list_by_tag is not declared)"""
    assert _registered_tool_names(GROWTH_PM) == sorted(t for t in GROWTH_PM.tools if t != "consult_hx")


def test_hx_registers_exactly_its_declared_note_tools():
    """HX's registered note tools match Role.tools exactly"""
    assert _registered_tool_names(HX) == sorted(HX.tools)


def test_product_owner_registers_exactly_its_declared_note_tools():
    """The Product Owner's registered note tools match Role.tools exactly (list_by_tag is not declared)"""
    assert _registered_tool_names(PRODUCT_OWNER) == sorted(PRODUCT_OWNER.tools)


def test_consult_hx_registered_when_role_declares_it():
    """consult_hx is registered on an agent whose Role.tools lists it"""
    captured = {}

    def fn(messages, info):
        captured["names"] = sorted(t.name for t in info.function_tools)
        return ModelResponse(parts=[TextPart("ok")])

    pm_agent = Agent(FunctionModel(fn), deps_type=str)
    hx_agent = Agent(FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("x")])), deps_type=str)
    _register_consult_hx(pm_agent, GROWTH_PM, hx_agent, [None])
    pm_agent.run_sync("hi", deps="kb")
    assert "consult_hx" in captured["names"]


def test_consult_hx_not_registered_when_role_does_not_declare_it():
    """consult_hx is not registered on a role that doesn't list it in Role.tools"""
    captured = {}

    def fn(messages, info):
        captured["names"] = sorted(t.name for t in info.function_tools)
        return ModelResponse(parts=[TextPart("ok")])

    po_agent = Agent(FunctionModel(fn), deps_type=str)
    hx_agent = Agent(FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("x")])), deps_type=str)
    _register_consult_hx(po_agent, PRODUCT_OWNER, hx_agent, [None])
    po_agent.run_sync("hi", deps="kb")
    assert captured["names"] == []


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


def test_sources_exist_retries_when_source_is_a_directory(tmp_path):
    """The HX output validator raises ModelRetry when a cited source is a directory, not a note"""
    kb = MarkdownKnowledgeBase(tmp_path)
    (tmp_path / "adir.md").mkdir()
    answer = HXAnswer(
        question="q",
        summary="s",
        findings=[Finding(claim="c", kind=FindingKind.EVIDENCE, sources=["adir.md"])],
    )
    with pytest.raises(ModelRetry):
        _sources_exist(kb, answer)


def test_sources_exist_retries_when_source_escapes_root(tmp_path):
    """The HX output validator raises ModelRetry when a cited source resolves outside the vault"""
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret")
    kb = MarkdownKnowledgeBase(tmp_path)
    (tmp_path / "escape.md").symlink_to(outside / "secret.md")
    answer = HXAnswer(
        question="q",
        summary="s",
        findings=[Finding(claim="c", kind=FindingKind.EVIDENCE, sources=["escape.md"])],
    )
    with pytest.raises(ModelRetry):
        _sources_exist(kb, answer)


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
        output_type=HXAnswer,
    )
    usage = RunUsage()
    result = asyncio.run(_consult_hx(hx_agent, kb, usage, "q"))
    assert result == answer
    assert usage.requests == 1


# -- ProductSquad: chat() --------------------------------------------------


def test_chat_returns_growth_pm_reply(tmp_path):
    """chat() sends the message to the Growth PM and returns its text reply"""
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(kb, context=TEST_CONTEXT, model=_scripted_model(_text("Hi founder, what's on your mind?")))
    assert squad.chat("Hey") == "Hi founder, what's on your mind?"


def test_chat_writes_note_in_write_glob(tmp_path):
    """The Growth PM writes freely to a path covered by its write permission"""
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(
        kb,
        context=TEST_CONTEXT,
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
        context=TEST_CONTEXT,
        model=_scripted_model(
            _call_tool("write_note", {"path": "elsewhere/x.md", "content": "nope"}),
            _text("Sorry, I can't write there."),
        ),
    )
    assert squad.chat("Save this somewhere weird") == "Sorry, I can't write there."
    assert not (tmp_path / "elsewhere" / "x.md").exists()


def test_chat_can_search_and_read_notes(tmp_path):
    """The Growth PM can search and read notes through its own tools"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("notes/a.md", "---\ntags: [x]\n---\nalpha content")
    squad = ProductSquad(
        kb,
        context=TEST_CONTEXT,
        model=_scripted_model(
            _call_tool("search_notes", {"query": "alpha"}),
            _call_tool("read_note", {"path": "notes/a.md"}),
            _text("Found it."),
        ),
    )
    assert squad.chat("Look into alpha") == "Found it."


def test_hx_can_list_notes_by_tag(tmp_path):
    """HX can list notes by tag through its own tools (not declared on the Growth PM)"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("notes/a.md", "---\ntags: [x]\n---\nalpha content")
    answer = HXAnswer(
        question="q",
        summary="s",
        findings=[Finding(claim="c", kind=FindingKind.GAP, sources=[])],
    )
    squad = ProductSquad(
        kb,
        context=TEST_CONTEXT,
        model=_scripted_model(
            _call_tool("consult_hx", {"question": "What do we know about x?"}),
            _call_tool("list_by_tag", {"tag": "x"}),
            _call_output_tool(answer),
            _text("Done."),
        ),
    )
    assert squad.chat("Look into x") == "Done."


def test_chat_write_requires_approval_then_resumes(tmp_path):
    """A write to a write_with_approval path defers, then resumes once approved"""
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(
        kb,
        context=TEST_CONTEXT,
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
        context=TEST_CONTEXT,
        model=_scripted_model(
            _call_tool("consult_hx", {"question": "Why do users churn?"}),
            _call_output_tool(answer),
            _text("HX says step 3 confuses users."),
        ),
    )
    assert squad.chat("Why are users churning?") == "HX says step 3 confuses users."


# -- ProductSquad: context is included in every agent's instructions ------


def _system_prompt(messages) -> str:
    """Extract the SystemPromptPart content pydantic_ai sends for `system_prompt=...`."""
    for part in messages[0].parts:
        if type(part).__name__ == "SystemPromptPart":
            return part.content
    raise AssertionError("no SystemPromptPart found in the first request")


def test_growth_pm_and_hx_instructions_include_product_context(tmp_path):
    """Both the Growth PM's and HX's instructions include the given product context"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("interviews/a.md", "evidence")
    answer = HXAnswer(
        question="q",
        summary="s",
        findings=[Finding(claim="c", kind=FindingKind.EVIDENCE, sources=["interviews/a.md"])],
    )
    captured_prompts = []

    def fn(messages, info):
        captured_prompts.append(_system_prompt(messages))
        if len(captured_prompts) == 1:
            return ModelResponse(parts=[ToolCallPart("consult_hx", {"question": "q"})])
        if len(captured_prompts) == 2:
            return _call_output_tool(answer)(messages, info)
        return ModelResponse(parts=[TextPart("done")])

    squad = ProductSquad(kb, model=FunctionModel(fn), context=TEST_CONTEXT)
    squad.chat("hi")
    assert len(captured_prompts) == 3
    assert TEST_CONTEXT in captured_prompts[0]  # Growth PM
    assert TEST_CONTEXT in captured_prompts[1]  # HX


def test_product_owner_instructions_include_product_context(tmp_path):
    """The Product Owner's instructions include the given product context"""
    kb = MarkdownKnowledgeBase(tmp_path)
    backlog = Backlog(stories=[Story(title="Story", acceptance_criteria=["done"], needs_design=True)])
    captured = {}

    def fn(messages, info):
        captured["prompt"] = _system_prompt(messages)
        return _call_output_tool(backlog)(messages, info)

    squad = ProductSquad(kb, model=FunctionModel(fn), context=TEST_CONTEXT)
    squad.submit_bet(_bet())
    assert TEST_CONTEXT in captured["prompt"]


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
    squad = ProductSquad(kb, context=TEST_CONTEXT, model=_scripted_model(_call_output_tool(bet)))
    assert squad.close_bet() == bet


def test_submit_bet_returns_backlog(tmp_path):
    """submit_bet() hands the bet to the Product Owner and returns its Backlog"""
    kb = MarkdownKnowledgeBase(tmp_path)
    backlog = Backlog(stories=[Story(title="Shorter wizard", acceptance_criteria=["3 steps"], needs_design=True)])
    squad = ProductSquad(kb, context=TEST_CONTEXT, model=_scripted_model(_call_output_tool(backlog)))
    assert squad.submit_bet(_bet()) == backlog


def test_submit_bet_returns_revision_without_resubmitting_to_po(tmp_path):
    """On a SendBack, submit_bet() returns a Revision instead of resubmitting it to the PO"""
    send_back = SendBack(reason="Scope is unclear", questions=["Which platform?"])
    revised_bet = _bet(scope=["Signup wizard", "web only"])
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(
        kb,
        context=TEST_CONTEXT,
        # Only 2 turns: PO(SendBack), PM(revise). A 3rd call (a second PO
        # run) would overrun the script and fail the test.
        model=_scripted_model(_call_output_tool(send_back), _call_output_tool(revised_bet)),
    )
    result = squad.submit_bet(_bet())
    assert isinstance(result, Revision)
    assert result.bet == revised_bet
    assert result.send_back == send_back


def test_submit_bet_resubmits_only_when_called_again_with_the_revision(tmp_path):
    """The founder must call submit_bet(revision.bet) to actually reach the PO"""
    send_back = SendBack(reason="Scope is unclear", questions=["Which platform?"])
    revised_bet = _bet(scope=["Signup wizard", "web only"])
    backlog = Backlog(stories=[Story(title="Story", acceptance_criteria=["done"], needs_design=True)])
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(
        kb,
        context=TEST_CONTEXT,
        model=_scripted_model(
            _call_output_tool(send_back),  # PO, first submission
            _call_output_tool(revised_bet),  # PM revises
            _call_output_tool(backlog),  # PO, second submission (founder resubmitted)
        ),
    )
    revision = squad.submit_bet(_bet())
    assert isinstance(revision, Revision)
    assert squad.submit_bet(revision.bet) == backlog


def test_submit_bet_needs_a_bet_unless_resuming(tmp_path):
    """submit_bet() without a bet and without a pending revision is a usage error"""
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(kb, context=TEST_CONTEXT, model=_scripted_model())
    with pytest.raises(ValueError):
        squad.submit_bet()


def test_submit_bet_revision_can_defer_for_approval(tmp_path):
    """submit_bet() surfaces a DeferredToolRequests if revising the bet needs write approval"""
    send_back = SendBack(reason="Scope is unclear", questions=["Which platform?"])
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(
        kb,
        context=TEST_CONTEXT,
        model=_scripted_model(
            _call_output_tool(send_back),
            _call_tool("write_note", {"path": "docs/context.md", "content": "notes"}),
        ),
    )
    result = squad.submit_bet(_bet())
    assert isinstance(result, DeferredToolRequests)


def test_submit_bet_resume_after_deferred_revision_does_not_call_po_again(tmp_path):
    """Resuming a deferred bet revision resumes only the Growth PM, never the Product Owner"""
    send_back = SendBack(reason="Scope is unclear", questions=["Which platform?"])
    revised_bet = _bet(scope=["Signup wizard", "web only"])
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(
        kb,
        context=TEST_CONTEXT,
        # Exactly 3 turns: PO(SendBack), PM(defers on write_note), PM(resumed
        # -> Bet). A stray 4th call (an unexpected PO re-run) would overrun
        # the script and fail the test.
        model=_scripted_model(
            _call_output_tool(send_back),
            _call_tool("write_note", {"path": "docs/context.md", "content": "notes"}),
            _call_output_tool(revised_bet),
        ),
    )
    pending = squad.submit_bet(_bet())
    assert isinstance(pending, DeferredToolRequests)

    resumed = squad.submit_bet(deferred_tool_results=pending.build_results(approve_all=True))
    assert isinstance(resumed, Revision)
    assert resumed.bet == revised_bet
    assert resumed.send_back == send_back
    assert kb.read("docs/context.md").content == "notes"


# -- ProductSquad: observability (ADR 0006) --------------------------------


def test_chat_with_trace_dir_writes_a_cycle_jsonl_file(tmp_path):
    """chat() with trace_dir set writes a {cycle_id}.jsonl trace file with a header, spans and a snapshot"""
    kb = MarkdownKnowledgeBase(tmp_path / "vault")
    trace_dir = tmp_path / "traces"
    squad = ProductSquad(kb, context=TEST_CONTEXT, model=_scripted_model(_text("hi")), trace_dir=trace_dir)

    squad.chat("hey")

    files = list(trace_dir.glob("*.jsonl"))
    assert len(files) == 1
    assert files[0].stem == squad._cycle_id
    kinds = [json.loads(line)["kind"] for line in files[0].read_text().splitlines()]
    assert kinds[0] == "CycleHeader"
    assert kinds[-1] == "CycleSnapshot"
    assert "Span" in kinds


def test_chat_without_trace_dir_writes_no_trace_file_but_still_has_a_cycle_id(tmp_path):
    """A ProductSquad without trace_dir still generates a cycle_id, just doesn't persist anything"""
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(kb, context=TEST_CONTEXT, model=_scripted_model(_text("hi")))

    squad.chat("hey")

    assert squad._cycle_id is not None
    assert not (tmp_path / f"{squad._cycle_id}.jsonl").exists()


def test_close_bet_writes_a_bet_note_with_frontmatter(tmp_path):
    """close_bet() writes a squad/bets/<id>.md note carrying cycle_id/schema_version/bet_version_id"""
    kb = MarkdownKnowledgeBase(tmp_path)
    bet = _bet()
    squad = ProductSquad(kb, context=TEST_CONTEXT, model=_scripted_model(_call_output_tool(bet)))

    squad.close_bet()

    bet_notes = list((tmp_path / "squad" / "bets").glob("*.md"))
    assert len(bet_notes) == 1
    note = kb.read(f"squad/bets/{bet_notes[0].stem}.md")
    assert note.frontmatter["cycle_id"] == squad._cycle_id
    assert note.frontmatter["schema_version"] == "1"
    assert note.frontmatter["bet_version_id"] == bet_notes[0].stem
    assert "previous_bet_version_id" not in note.frontmatter
    assert bet.hypothesis in note.content


def test_bet_revision_note_carries_previous_bet_version_id(tmp_path):
    """A revised Bet's note carries previous_bet_version_id pointing at the Bet it replaced"""
    send_back = SendBack(reason="Scope is unclear", questions=["Which platform?"])
    revised_bet = _bet(scope=["Signup wizard", "web only"])
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(
        kb,
        context=TEST_CONTEXT,
        model=_scripted_model(
            _call_output_tool(_bet()),  # close_bet()
            _call_output_tool(send_back),  # PO sends it back
            _call_output_tool(revised_bet),  # PM revises
        ),
    )
    squad.close_bet()
    before = {p.stem for p in (tmp_path / "squad" / "bets").glob("*.md")}

    result = squad.submit_bet(_bet())

    assert isinstance(result, Revision)
    after = {p.stem for p in (tmp_path / "squad" / "bets").glob("*.md")}
    new_id = next(iter(after - before))
    first_id = next(iter(before))
    note = kb.read(f"squad/bets/{new_id}.md")
    assert note.frontmatter["previous_bet_version_id"] == first_id


def test_resume_continues_a_conversation_from_a_saved_cycle(tmp_path):
    """resume() reloads a saved cycle's history so a fresh ProductSquad's chat() continues it"""
    kb = MarkdownKnowledgeBase(tmp_path / "vault")
    trace_dir = tmp_path / "traces"
    first = ProductSquad(kb, context=TEST_CONTEXT, model=_scripted_model(_text("Hi founder!")), trace_dir=trace_dir)
    first.chat("hey")
    cycle_id = first._cycle_id

    captured = {}

    def fn(messages, info):
        captured["history_len"] = len(messages)
        return ModelResponse(parts=[TextPart("continuing")])

    second = ProductSquad(kb, context=TEST_CONTEXT, model=FunctionModel(fn), trace_dir=trace_dir)
    second.resume(cycle_id)
    reply = second.chat("still there?")

    assert reply == "continuing"
    assert second._cycle_id == cycle_id
    assert captured["history_len"] > 1


def test_resume_requires_trace_dir(tmp_path):
    """resume() raises when trace_dir was never set on this ProductSquad"""
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(kb, context=TEST_CONTEXT, model=_scripted_model())
    with pytest.raises(ValueError, match="trace_dir"):
        squad.resume("nope")


def test_resumed_approval_is_recorded_as_a_resolution_span(tmp_path):
    """Resuming a deferred write_note approval records an approval_resolution span in the trace"""
    kb = MarkdownKnowledgeBase(tmp_path / "vault")
    trace_dir = tmp_path / "traces"
    squad = ProductSquad(
        kb,
        context=TEST_CONTEXT,
        model=_scripted_model(
            _call_tool("write_note", {"path": "docs/context.md", "content": "new context"}),
            _text("Wrote it after approval."),
        ),
        trace_dir=trace_dir,
    )
    pending = squad.chat("Update the docs")
    reply = squad.chat(deferred_tool_results=pending.build_results(approve_all=True))
    assert reply == "Wrote it after approval."

    lines = [json.loads(line) for line in (trace_dir / f"{squad._cycle_id}.jsonl").read_text().splitlines()]
    resolution_spans = [
        line["data"] for line in lines if line["kind"] == "Span" and line["data"]["operation"] == "approval_resolution"
    ]
    assert len(resolution_spans) == 1
    assert resolution_spans[0]["status"] == "ok"
    assert resolution_spans[0]["detail"] == "approved"


def test_resumed_denial_is_recorded_as_a_resolution_span(tmp_path):
    """Denying a deferred write_note approval records an approval_resolution span with status error"""
    kb = MarkdownKnowledgeBase(tmp_path / "vault")
    trace_dir = tmp_path / "traces"
    squad = ProductSquad(
        kb,
        context=TEST_CONTEXT,
        model=_scripted_model(
            _call_tool("write_note", {"path": "docs/context.md", "content": "new context"}),
            _text("Understood, not writing it."),
        ),
        trace_dir=trace_dir,
    )
    pending = squad.chat("Update the docs")
    tool_call_id = pending.approvals[0].tool_call_id
    reply = squad.chat(deferred_tool_results=pending.build_results(approvals={tool_call_id: False}))
    assert reply == "Understood, not writing it."

    lines = [json.loads(line) for line in (trace_dir / f"{squad._cycle_id}.jsonl").read_text().splitlines()]
    resolution_spans = [
        line["data"] for line in lines if line["kind"] == "Span" and line["data"]["operation"] == "approval_resolution"
    ]
    assert len(resolution_spans) == 1
    assert resolution_spans[0]["status"] == "error"
    assert resolution_spans[0]["detail"] == "denied"


def test_usage_limits_is_enforced_within_a_call(tmp_path):
    """usage_limits passed to ProductSquad is enforced by pydantic_ai on every agent run"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("notes/a.md", "alpha")
    squad = ProductSquad(
        kb,
        context=TEST_CONTEXT,
        model=_scripted_model(_call_tool("search_notes", {"query": "alpha"}), _text("done")),
        usage_limits=UsageLimits(request_limit=1),
    )
    with pytest.raises(UsageLimitExceeded):
        squad.chat("look into alpha")
