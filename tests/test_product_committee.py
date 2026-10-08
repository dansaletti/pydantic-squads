import asyncio
import os

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import pytest

pytest.importorskip("pydantic_ai", reason="requires the 'ai' extra: uv sync --extra ai")

from pydantic_ai import Agent, DeferredToolRequests, ModelRetry, UsageLimits
from pydantic_ai import models as pydantic_ai_models
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from pydantic_squads.product import committee
from pydantic_squads.product.assembly import ProductSquad, _check_triage, _register_opinion_source_validator
from pydantic_squads.product.contracts import (
    Backlog,
    Brief,
    BriefDraft,
    Divergence,
    Finding,
    FindingKind,
    GapGroup,
    HXAnswer,
    KnowledgeGap,
    Opinion,
    OpinionDraft,
    Story,
    Synthesis,
    SynthesisDraft,
    Triage,
)
from pydantic_squads.product.knowledge import MarkdownKnowledgeBase
from pydantic_squads.product.observability import HX_SINK, SpanSink, load_cycle

pydantic_ai_models.ALLOW_MODEL_REQUESTS = False

TEST_CONTEXT = "A B2B tool for small logistics companies. Primary persona: dispatch manager."
REQUEST = "A fake-door landing page for route sharing"


def _draft(**overrides) -> OpinionDraft:
    defaults = dict(recommendation="Run it for two weeks", confidence="medium", sources=["interviews/a.md"])
    return OpinionDraft(**{**defaults, **overrides})


def _output(model):
    """A model turn that calls the output tool matching `model`'s type."""

    def turn(messages, info):
        title = type(model).__name__
        tool = next(t for t in info.output_tools if t.parameters_json_schema.get("title") == title)
        return ModelResponse(parts=[ToolCallPart(tool.name, model.model_dump(mode="json"))])

    return turn


def _pm_agent(fn) -> Agent:
    agent = Agent(FunctionModel(fn), deps_type=MarkdownKnowledgeBase, output_type=OpinionDraft)
    _register_opinion_source_validator(agent)
    return agent


def _kb(tmp_path) -> MarkdownKnowledgeBase:
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("interviews/a.md", "evidence text")
    return kb


# -- committee.opinion(): one isolated run ----------------------------------


def test_opinion_is_stamped_with_the_role_that_ran(tmp_path):
    """opinion() returns the PM's draft as an Opinion carrying the role id the runtime gave it"""
    run = asyncio.run(committee.opinion(_pm_agent(_output(_draft())), "pm_product", _kb(tmp_path), REQUEST))
    assert run.opinion == Opinion(role="pm_product", **_draft().model_dump())


def test_opinion_run_starts_from_the_request_alone(tmp_path):
    """An opinion run has no message history: the model sees one message, holding the request"""
    seen = []

    def fn(messages, info):
        seen.append(messages)
        return _output(_draft())(messages, info)

    asyncio.run(committee.opinion(_pm_agent(fn), "pm_product", _kb(tmp_path), REQUEST))
    [messages] = seen
    assert len(messages) == 1
    assert REQUEST in messages[0].parts[-1].content


def test_opinion_sources_must_exist_in_the_knowledge_base(tmp_path):
    """An opinion citing a note that does not exist is sent back to the PM until its sources are real"""
    turns = iter([_output(_draft(sources=["interviews/made-up.md"])), _output(_draft(sources=["interviews/a.md (§2)"]))])
    agent = _pm_agent(lambda messages, info: next(turns)(messages, info))
    run = asyncio.run(committee.opinion(agent, "growth_pm", _kb(tmp_path), REQUEST))
    assert run.opinion.sources == ["interviews/a.md"]
    retries = [part for m in run.messages for part in m.parts if type(part).__name__ == "RetryPromptPart"]
    assert len(retries) == 1 and "interviews/made-up.md" in retries[0].content


def test_opinion_that_never_cites_a_real_note_fails(tmp_path):
    """A PM that keeps citing a missing note ends the run with an error, never an Opinion"""
    agent = _pm_agent(_output(_draft(sources=["interviews/made-up.md"])))
    with pytest.raises(UnexpectedModelBehavior):
        asyncio.run(committee.opinion(agent, "growth_pm", _kb(tmp_path), REQUEST))
    assert HX_SINK.get() is None


def test_opinion_respects_usage_limits(tmp_path):
    """usage_limits is passed to the PM's run"""
    agent = _pm_agent(_output(_draft()))
    with pytest.raises(UsageLimitExceeded):
        asyncio.run(
            committee.opinion(agent, "growth_pm", _kb(tmp_path), REQUEST, usage_limits=UsageLimits(request_limit=0))
        )


# -- committee.opinions(): the fan-out ---------------------------------------


def test_opinions_are_formed_in_parallel_and_returned_in_order(tmp_path):
    """Every PM's run is in flight at once, and the opinions come back in the order asked"""
    started = []
    all_started = asyncio.Event()

    def waiting_agent() -> Agent:
        async def fn(messages, info):
            started.append(1)
            if len(started) == 3:
                all_started.set()
            # Runs done one after the other would never all have started: this would time out.
            await asyncio.wait_for(all_started.wait(), timeout=5)
            return _output(_draft())(messages, info)

        return _pm_agent(fn)

    agents = {role_id: waiting_agent() for role_id in ("pm_marketing", "growth_pm", "pm_product")}
    runs = asyncio.run(committee.opinions(agents, _kb(tmp_path), REQUEST))
    assert [run.opinion.role for run in runs] == ["pm_marketing", "growth_pm", "pm_product"]


# -- The round, through ProductSquad -----------------------------------------

ROLE_BY_NAME = {"Growth PM": "growth_pm", "Product PM": "pm_product", "Marketing PM": "pm_marketing"}


def _triage(*roles: str) -> Triage:
    return Triage(request=REQUEST, roles=list(roles), rationale="They hold the views this request needs")


def _brief_draft(**overrides) -> BriefDraft:
    defaults = dict(
        problem="Dispatch managers do not know route sharing exists",
        hypothesis="A fake-door landing page shows whether they want it",
        success_metric="waitlist signups",
        acceptance_criteria=["The page has one call to action"],
        owner_roles=["growth_pm", "pm_product"],
    )
    return BriefDraft(**{**defaults, **overrides})


def _synthesis(summary: str = "Both PMs back a two-week test", divergences: list[Divergence] | None = None):
    return SynthesisDraft(
        summary=summary,
        divergences=divergences or [],
        questions_for_human=["Is two weeks acceptable?"],
        proposed_brief=_brief_draft(),
    )


def _divergence(**positions: str) -> Divergence:
    return Divergence(topic="How long to run it", positions=positions)


def _gap(claim: str = "Nobody asked dispatch managers about sharing") -> HXAnswer:
    return HXAnswer(question="model's own wording", summary="s", findings=[Finding(claim=claim, kind=FindingKind.GAP)])


class Committee:
    """A fake model for the whole squad: it tells the agents apart and plays each from its own script.

    `calls` records every model call as (kind, role), so a test can count
    exactly who ran, and how often.
    """

    def __init__(self, *, triage=None, syntheses=(), drafts=None, replies=None, consults=None, hx=None, chat=()):
        self.triage = iter(triage if triage is not None else [_output(_triage("growth_pm", "pm_product"))])
        self.syntheses = iter(syntheses or [_synthesis()])
        self.drafts = drafts or {}
        self.replies = replies or {}
        self.consults = consults or {}  # role -> the question it puts to HX before giving its opinion
        self.hx = hx or (lambda question: _gap())
        self.chat = iter(chat)
        self.calls: list[tuple[str, str | None]] = []
        self.prompts: dict[tuple[str, str | None], str] = {}
        self.offered: dict[str, list[str]] = {}
        self.history: dict[str, int] = {}

    def _note(self, kind: str, role: str | None, messages, info) -> None:
        self.calls.append((kind, role))
        self.prompts[(kind, role)] = str(messages[-1].parts[-1].content)
        self.offered.setdefault(kind, sorted(t.name for t in info.function_tools))
        self.history.setdefault(kind, len(messages))

    def __call__(self, messages, info):
        titles = {t.parameters_json_schema.get("title") for t in info.output_tools}
        if "HXAnswer" in titles:
            self._note("hx", None, messages, info)
            return _output(self.hx(messages[0].parts[-1].content))(messages, info)
        if "SynthesisDraft" in titles:
            self._note("synthesis", None, messages, info)
            return _output(next(self.syntheses))(messages, info)
        if "OpinionDraft" in titles:
            system = next(p.content for p in messages[0].parts if type(p).__name__ == "SystemPromptPart")
            role = next(role for name, role in ROLE_BY_NAME.items() if system.startswith(f"You are the {name} "))
            user = str(messages[0].parts[-1].content)
            if "This is your one reply" in user:
                self._note("reply", role, messages, info)
                return _output(self.replies.get(role, _draft(recommendation="I keep my opinion")))(messages, info)
            if role in self.consults and len(messages) == 1:
                return ModelResponse(parts=[ToolCallPart("consult_hx", {"question": self.consults[role]})])
            self._note("opinion", role, messages, info)
            return _output(self.drafts.get(role, _draft()))(messages, info)
        if "Triage" in titles:
            self._note("triage", None, messages, info)
            return next(self.triage)(messages, info)
        self._note("chat", None, messages, info)
        return next(self.chat)(messages, info)

    def count(self, kind: str) -> int:
        return sum(1 for called, _role in self.calls if called == kind)

    def roles(self, kind: str) -> list[str]:
        return sorted(role for called, role in self.calls if called == kind)


def _squad(tmp_path, script: Committee, **kwargs) -> ProductSquad:
    return ProductSquad(_kb(tmp_path), context=TEST_CONTEXT, model=FunctionModel(script), **kwargs)


def _tool_call(name: str, **args):
    return lambda messages, info: ModelResponse(parts=[ToolCallPart(name, args)])


def _text(text: str):
    return lambda messages, info: ModelResponse(parts=[TextPart(text)])


# -- triage -------------------------------------------------------------------


def test_review_hears_only_the_pms_the_triage_picked(tmp_path):
    """review() runs the PMs the Facilitator triaged in, and no other"""
    script = Committee(triage=[_output(_triage("pm_marketing", "growth_pm"))])
    synthesis = _squad(tmp_path, script).review(REQUEST)
    assert isinstance(synthesis, Synthesis)
    assert [o.role for o in synthesis.opinions] == ["pm_marketing", "growth_pm"]
    assert script.roles("opinion") == ["growth_pm", "pm_marketing"]
    assert REQUEST in script.prompts[("triage", None)]


def test_triage_cannot_name_a_role_outside_the_committee(tmp_path):
    """A triage naming a role that gives no opinion is sent back to the Facilitator"""
    script = Committee(triage=[_output(_triage("growth_pm", "product_owner")), _output(_triage("growth_pm"))])
    synthesis = _squad(tmp_path, script).review(REQUEST)
    assert [o.role for o in synthesis.opinions] == ["growth_pm"]
    assert script.count("triage") == 2


def test_check_triage_hears_each_pm_once():
    """_check_triage drops a PM named twice and refuses an unknown one"""
    assert _check_triage(_triage("pm_product", "growth_pm", "pm_product")).roles == ["pm_product", "growth_pm"]
    with pytest.raises(ModelRetry, match="designer"):
        _check_triage(_triage("designer"))


def test_close_request_triages_the_conversation(tmp_path):
    """close_request() triages with the whole conversation in view, and then runs the round"""
    script = Committee(chat=[_text("Who is it for?")])
    squad = _squad(tmp_path, script)
    squad.chat("I want a fake-door landing page")
    synthesis = squad.close_request()
    assert isinstance(synthesis, Synthesis)
    assert script.history["triage"] == 3  # the chat's two messages, then the closing prompt
    assert synthesis.request == REQUEST


def test_review_needs_a_request_unless_resuming(tmp_path):
    """review() with neither a request nor a deferred result is a usage error"""
    with pytest.raises(ValueError, match="needs a request"):
        _squad(tmp_path, Committee()).review()


@pytest.mark.parametrize("entry", ["close_request", "review"])
def test_triage_that_needs_approval_pauses_before_the_round(tmp_path, entry):
    """A write that needs approval during triage comes back deferred; resolving it resumes into the round"""
    write = _tool_call("write_note", path="docs/request.md", content="notes")
    script = Committee(triage=[write, _output(_triage("growth_pm"))])
    squad = _squad(tmp_path, script)
    start = squad.close_request if entry == "close_request" else (lambda **kw: squad.review(REQUEST, **kw))
    resume = squad.close_request if entry == "close_request" else squad.review

    pending = start()
    assert isinstance(pending, DeferredToolRequests)
    assert script.count("opinion") == 0

    synthesis = resume(deferred_tool_results=pending.build_results(approve_all=True))
    assert isinstance(synthesis, Synthesis)
    assert squad.kb.read("docs/request.md").content == "notes"


# -- what the Facilitator can and cannot do ----------------------------------


def test_facilitator_has_no_tool_to_call_a_pm(tmp_path):
    """In the conversation the Facilitator can consult HX and handle notes, and nothing reaches a PM"""
    script = Committee(chat=[_text("hi")])
    _squad(tmp_path, script).chat("hello")
    assert script.offered["chat"] == ["consult_hx", "read_note", "search_notes", "write_note"]
    assert script.calls == [("chat", None)]


def test_synthesis_run_has_no_tools_and_no_history(tmp_path):
    """The Facilitator consolidating opinions is offered no tool at all and sees only the synthesis prompt"""
    script = Committee()
    _squad(tmp_path, script).review(REQUEST)
    assert script.offered["synthesis"] == []
    assert script.history["synthesis"] == 1


def test_synthesis_has_no_recommendation_of_its_own():
    """A Synthesis has nowhere to put a Facilitator recommendation"""
    assert not any("recommend" in name for name in Synthesis.model_fields)
    assert {"opinions", "rebuttals", "gaps", "request"} <= set(Synthesis.model_fields) - set(SynthesisDraft.model_fields)


def test_synthesis_cannot_speak_for_a_pm_that_gave_no_opinion(tmp_path):
    """A divergence citing a PM outside the round is sent back to the Facilitator"""
    made_up = _synthesis(divergences=[_divergence(growth_pm="two weeks", pm_marketing="a month")])
    script = Committee(syntheses=[made_up, _synthesis()])
    synthesis = _squad(tmp_path, script).review(REQUEST)
    assert synthesis.divergences == []
    assert script.count("synthesis") == 2 and script.count("reply") == 0


# -- fan-out and rebuttal -----------------------------------------------------


def test_review_forms_the_opinions_in_parallel(tmp_path):
    """Through ProductSquad too, every triaged PM's run is in flight before any of them answers"""
    script = Committee(triage=[_output(_triage("growth_pm", "pm_product", "pm_marketing"))])
    started: list[int] = []
    gates: dict[int, asyncio.Event] = {}

    async def fn(messages, info):
        titles = {t.parameters_json_schema.get("title") for t in info.output_tools}
        if "OpinionDraft" in titles:
            gate = gates.setdefault(id(asyncio.get_running_loop()), asyncio.Event())
            started.append(1)
            if len(started) == 3:
                gate.set()
            await asyncio.wait_for(gate.wait(), timeout=5)
        return script(messages, info)

    squad = ProductSquad(_kb(tmp_path), context=TEST_CONTEXT, model=FunctionModel(fn))
    assert len(squad.review(REQUEST).opinions) == 3


def test_agreeing_pms_get_one_synthesis_and_no_rebuttal(tmp_path):
    """With no divergence there is one synthesis and nobody is asked to reply"""
    script = Committee()
    synthesis = _squad(tmp_path, script).review(REQUEST)
    assert synthesis.rebuttals == []
    assert (script.count("synthesis"), script.count("reply")) == (1, 0)


def test_only_the_pms_in_a_divergence_reply_and_only_once(tmp_path):
    """A divergence gives its PMs one reply each; a second synthesis that still diverges ends the round"""
    diverging = _synthesis(divergences=[_divergence(growth_pm="two weeks", pm_product="a month")])
    script = Committee(
        triage=[_output(_triage("growth_pm", "pm_product", "pm_marketing"))],
        syntheses=[diverging, diverging],
        replies={"growth_pm": _draft(recommendation="Three weeks would do")},
    )
    synthesis = _squad(tmp_path, script).review(REQUEST)
    assert script.roles("reply") == ["growth_pm", "pm_product"]  # pm_marketing was not cited
    assert script.count("synthesis") == 2
    assert [o.role for o in synthesis.rebuttals] == ["growth_pm", "pm_product"]
    assert synthesis.rebuttals[0].recommendation == "Three weeks would do"
    assert synthesis.divergences == diverging.divergences  # still there for the human
    assert "a month" in script.prompts[("reply", "growth_pm")]


def test_original_opinions_reach_the_human_untouched(tmp_path):
    """The synthesis carries each PM's first opinion whole, whatever the replies and the summary say"""
    diverging = _synthesis(divergences=[_divergence(growth_pm="two weeks", pm_product="a month")])
    drafts = {
        "growth_pm": _draft(recommendation="Two weeks", risks=["Small sample"], confidence="low"),
        "pm_product": _draft(recommendation="A month", questions_for_human=["Can we wait?"]),
    }
    script = Committee(syntheses=[diverging, _synthesis("They now agree")], drafts=drafts)
    synthesis = _squad(tmp_path, script).review(REQUEST)
    assert synthesis.opinions == [
        Opinion(role="growth_pm", **drafts["growth_pm"].model_dump()),
        Opinion(role="pm_product", **drafts["pm_product"].model_dump()),
    ]
    assert synthesis.summary == "They now agree"


# -- what we do not know ------------------------------------------------------


def test_synthesis_lists_the_gaps_hx_reported_with_their_questions(tmp_path):
    """A gap two PMs ran into is one entry, with both questions and both PMs, in the synthesis and its note"""
    script = Committee(
        consults={"growth_pm": "Do they share routes today?", "pm_product": "How do they share routes?"},
    )
    squad = _squad(tmp_path, script)
    synthesis = squad.review(REQUEST)
    assert synthesis.gaps == [
        KnowledgeGap(
            gap="Nobody asked dispatch managers about sharing",
            questions=["Do they share routes today?", "How do they share routes?"],
            asked_by=["growth_pm", "pm_product"],
        )
    ]
    note = squad.kb.read(f"squad/committee/{squad.cycle_id}/synthesis-1.md").content
    assert "## What we don't know" in note
    assert "- Asked HX: Do they share routes today?" in note
    assert "- Asked by: growth_pm, pm_product" in note


def test_gaps_ignore_evidence_and_keep_distinct_gaps_apart(tmp_path):
    """Only gap findings are listed, and two different gaps stay two entries"""

    def hx(question: str) -> HXAnswer:
        if "today" in question:
            return _gap("No usage data on sharing")
        return HXAnswer(
            question="q",
            summary="s",
            findings=[
                Finding(claim="Managers email routes", kind=FindingKind.EVIDENCE, sources=["interviews/a.md"]),
                Finding(claim="Nobody asked about pricing", kind=FindingKind.GAP),
            ],
        )

    script = Committee(consults={"growth_pm": "Do they share today?", "pm_product": "Would they pay?"}, hx=hx)
    synthesis = _squad(tmp_path, script).review(REQUEST)
    assert [g.gap for g in synthesis.gaps] == ["No usage data on sharing", "Nobody asked about pricing"]
    assert synthesis.gaps[1].asked_by == ["pm_product"]


def test_consolidate_gaps_matches_wording_loosely_and_lists_each_question_once():
    """The same gap worded with other case or spacing is one entry, and a repeated question is listed once"""

    def run(role: str, *claims: str) -> committee.OpinionRun:
        sink = SpanSink()
        for claim in claims:
            sink.hx_answers.append(_gap(claim).model_copy(update={"question": "Do they share?"}))
        return committee.OpinionRun(Opinion(role=role, **_draft().model_dump()), [], sink, 0.0)

    gaps = committee.consolidate_gaps([run("growth_pm", "No data  on Sharing", "no data on sharing"), run("growth_pm")])
    assert gaps == [KnowledgeGap(gap="No data  on Sharing", questions=["Do they share?"], asked_by=["growth_pm"])]


def _raw(*claims: str) -> list[KnowledgeGap]:
    return [
        KnowledgeGap(gap=claim, questions=[f"question {n}"], asked_by=[role])
        for n, (claim, role) in enumerate(zip(claims, ["growth_pm", "pm_product", "pm_marketing", "growth_pm"]), 1)
    ]


def test_group_gaps_joins_the_questions_and_pms_of_a_group():
    """A group is one gap in the Facilitator's words, carrying every question and PM of the gaps in it"""
    raw = _raw("No user evidence", "There are no interviews", "Nobody measured trust")
    grouped = committee.group_gaps(raw, [GapGroup(summary="No user research exists", gaps=[1, 2])])
    assert grouped == [
        KnowledgeGap(
            gap="No user research exists",
            questions=["question 1", "question 2"],
            asked_by=["growth_pm", "pm_product"],
        ),
        raw[2],  # left out by the Facilitator: kept, in HX's words
    ]


def test_group_gaps_cannot_lose_or_repeat_a_gap():
    """Whatever the Facilitator writes, every raw gap ends up in exactly one group"""
    raw = _raw("a", "b", "c", "d")
    groups = [
        GapGroup(summary="first", gaps=[1, 1, 2, 9]),  # a repeat and a number that is no gap
        GapGroup(summary="second", gaps=[2, 3]),  # 2 was already placed
        GapGroup(summary="empty once cleaned", gaps=[1, 0]),
    ]
    grouped = committee.group_gaps(raw, groups)
    assert [g.gap for g in grouped] == ["first", "second", "d"]
    assert [g.questions for g in grouped] == [["question 1", "question 2"], ["question 3"], ["question 4"]]
    assert committee.group_gaps(raw, []) == raw
    assert committee.group_gaps([], [GapGroup(summary="nothing to group", gaps=[1])]) == []


def test_facilitator_groups_reworded_gaps_and_the_note_keeps_hx_words(tmp_path):
    """Gaps HX worded differently become one entry when the Facilitator groups them; the raw ones stay in the note"""

    def hx(question: str) -> HXAnswer:
        return _gap("No user evidence at all" if "today" in question else "There are no interviews yet")

    grouped = _synthesis().model_copy(update={"gap_groups": [GapGroup(summary="No user research exists", gaps=[1, 2])]})
    script = Committee(
        syntheses=[grouped], consults={"growth_pm": "Do they share today?", "pm_product": "Would they pay?"}, hx=hx
    )
    squad = _squad(tmp_path, script)
    synthesis = squad.review(REQUEST)

    assert synthesis.gaps == [
        KnowledgeGap(
            gap="No user research exists",
            questions=["Do they share today?", "Would they pay?"],
            asked_by=["growth_pm", "pm_product"],
        )
    ]
    assert [g.gap for g in synthesis.raw_gaps] == ["No user evidence at all", "There are no interviews yet"]
    prompt = script.prompts[("synthesis", None)]
    assert "1. No user evidence at all" in prompt and "2. There are no interviews yet" in prompt
    note = squad.kb.read(f"squad/committee/{squad.cycle_id}/synthesis-1.md").content
    assert "### No user research exists" in note
    assert "## Gaps as HX reported them" in note
    assert "- There are no interviews yet (asked by pm_product)" in note


def test_adjust_regroups_the_same_raw_gaps(tmp_path):
    """adjust() gives the Facilitator the raw gaps again, so a new grouping never builds on an old one"""
    grouped = _synthesis().model_copy(update={"gap_groups": [GapGroup(summary="Grouped", gaps=[1])]})
    script = Committee(syntheses=[grouped, _synthesis()], consults={"growth_pm": "Do they share?"})
    squad = _squad(tmp_path, script)
    first = squad.review(REQUEST)
    adjusted = squad.adjust("List the gaps one by one")
    assert [g.gap for g in first.gaps] == ["Grouped"]
    assert adjusted.gaps == adjusted.raw_gaps == first.raw_gaps


def test_triage_prompts_spell_out_the_role_ids(tmp_path):
    """Both ways into a triage tell the Facilitator the exact ids to use for the PMs"""
    for start in (lambda squad: squad.review(REQUEST), lambda squad: squad.close_request()):
        script = Committee()
        start(_squad(tmp_path, script))
        prompt = script.prompts[("triage", None)]
        assert all(f"`{role_id}`" in prompt for role_id in ("growth_pm", "pm_product", "pm_marketing"))


# -- shared evidence: what HX already answered -------------------------------


def _consulting_chat(question: str):
    """Chat turns where the Facilitator consults HX once and then answers."""
    return [
        lambda messages, info: ModelResponse(parts=[ToolCallPart("consult_hx", {"question": question})]),
        _text("Here is what we know."),
    ]


def test_pms_are_handed_what_hx_already_answered_the_facilitator(tmp_path):
    """An HX answer from the conversation is in every PM's prompt, with its question, findings and sources"""

    def hx(question: str) -> HXAnswer:
        return HXAnswer(
            question="reworded by the model",
            summary="Managers email routes",
            findings=[Finding(claim="They email routes", kind=FindingKind.EVIDENCE, sources=["interviews/a.md"])],
        )

    script = Committee(chat=_consulting_chat("How do they share routes today?"), hx=hx)
    squad = _squad(tmp_path, script)
    squad.chat("I want route sharing")
    squad.close_request()
    for role in ("growth_pm", "pm_product"):
        prompt = script.prompts[("opinion", role)]
        assert "Question: How do they share routes today?" in prompt
        assert "- [evidence] They email routes (sources: interviews/a.md)" in prompt
        assert "Do not ask HX again" in prompt


def test_pms_get_no_evidence_section_when_hx_was_not_consulted(tmp_path):
    """With no earlier HX answer the PMs' prompt has no shared-evidence section"""
    script = Committee()
    _squad(tmp_path, script).review(REQUEST)
    assert "HX already answered" not in script.prompts[("opinion", "growth_pm")]


def test_a_gap_hx_gave_the_facilitator_is_in_the_synthesis(tmp_path):
    """A gap from the conversation counts as asked by the Facilitator, next to the PMs that hit it too"""
    script = Committee(chat=_consulting_chat("Do they share routes?"), consults={"growth_pm": "Would they pay?"})
    squad = _squad(tmp_path, script)
    squad.chat("I want route sharing")
    synthesis = squad.close_request()
    assert synthesis.raw_gaps == [
        KnowledgeGap(
            gap="Nobody asked dispatch managers about sharing",
            questions=["Do they share routes?", "Would they pay?"],
            asked_by=["facilitator", "growth_pm"],
        )
    ]


def test_shared_evidence_does_not_leak_into_the_next_request(tmp_path):
    """After a decision, what HX answered for the decided request is not handed to the next round's PMs"""
    script = Committee(
        chat=_consulting_chat("Do they share routes?"),
        triage=[_output(_triage("growth_pm"))] * 2,
        syntheses=[_synthesis(), _synthesis()],
    )
    squad = _squad(tmp_path, script)
    squad.chat("I want route sharing")
    squad.close_request()
    squad.reject("no")
    script.prompts.clear()
    squad.review("Something else entirely")
    assert "HX already answered" not in script.prompts[("opinion", "growth_pm")]


def test_prompts_ask_for_brevity(tmp_path):
    """The opinion, reply and synthesis prompts each tell the model to be brief"""
    diverging = _synthesis(divergences=[_divergence(growth_pm="two weeks", pm_product="a month")])
    script = Committee(syntheses=[diverging, diverging])
    _squad(tmp_path, script).review(REQUEST)
    for key in (("opinion", "growth_pm"), ("reply", "growth_pm"), ("synthesis", None)):
        assert "Be brief" in script.prompts[key]


# -- one model per role ------------------------------------------------------


def test_each_role_runs_on_its_own_model_when_given_one(tmp_path):
    """models= sends a role's agents to that model and leaves every other role on the squad's"""
    default, pm_model, hx_model = (FunctionModel(Committee()) for _ in range(3))
    squad = ProductSquad(
        _kb(tmp_path),
        context=TEST_CONTEXT,
        model=default,
        models={"growth_pm": pm_model, "pm_marketing": pm_model, "hx": hx_model},
    )
    assert squad._pms["growth_pm"].model is pm_model and squad._pms["pm_product"].model is default
    assert squad._marketing.model is pm_model and squad._pms["pm_marketing"].model is pm_model
    assert squad._hx.model is hx_model
    for agent in (squad._facilitator, squad._triager, squad._synthesizer, squad._po, squad._designer, squad._social):
        assert agent.model is default


def test_a_role_model_can_be_a_claude_code_string(tmp_path):
    """A model string in models= is resolved like the squad's own, so "claude-code:haiku" works for one role"""
    squad = ProductSquad(
        _kb(tmp_path), context=TEST_CONTEXT, model="claude-code:sonnet", models={"hx": "claude-code:haiku"}
    )
    assert (squad._hx.model.model_name, squad._po.model.model_name) == ("haiku", "sonnet")


def test_models_must_name_roles_of_the_squad(tmp_path):
    """models= with an id that is no role is a usage error"""
    with pytest.raises(ValueError, match="orchestrator"):
        ProductSquad(_kb(tmp_path), context=TEST_CONTEXT, model=FunctionModel(Committee()), models={"orchestrator": "x"})


# -- the notes ----------------------------------------------------------------


def test_synthesis_note_shows_the_synthesis_and_everything_under_it(tmp_path):
    """The note at the gate has the summary, divergences, proposed brief and each PM's full opinion"""
    diverging = _synthesis(divergences=[_divergence(growth_pm="two weeks", pm_product="a month")])
    drafts = {"growth_pm": _draft(recommendation="Two weeks", risks=["Small sample"], questions_for_human=["OK?"])}
    script = Committee(syntheses=[diverging, diverging], drafts=drafts)
    squad = _squad(tmp_path, script)
    squad.review(REQUEST)
    note = squad.kb.read(f"squad/committee/{squad.cycle_id}/synthesis-1.md")
    assert note.frontmatter == {
        "cycle_id": squad.cycle_id,
        "schema_version": "1",
        "version": "1",
        "roles": ["growth_pm", "pm_product"],
    }
    for expected in (
        "### How long to run it",
        "- pm_product: a month",
        "- Question for the human: OK?",
        "- Risk: Small sample",
        "- Source: interviews/a.md",
        "- Acceptance criterion: The page has one call to action",
        "## Replies",
        "- Is two weeks acceptable?",
    ):
        assert expected in note.content


def test_synthesis_note_says_so_when_there_is_nothing_to_list():
    """A synthesis with no divergence, question or gap says None instead of leaving the section empty"""
    quiet = SynthesisDraft(summary="Agreed", proposed_brief=_brief_draft())
    synthesis = committee.build_synthesis(REQUEST, quiet, [Opinion(role="growth_pm", **_draft().model_dump())], [], [])
    note = committee.synthesis_note(synthesis, "c1", 1)
    assert "## Divergences\n\nNone." in note
    assert "## Questions for the human\n\nNone." in note
    assert "HX reported no gap during this round." in note
    assert "## Replies" not in note


# -- the gate -----------------------------------------------------------------


def test_adjust_redoes_only_the_synthesis(tmp_path):
    """adjust() runs the Facilitator's synthesis again with the notes, and no PM"""
    script = Committee(syntheses=[_synthesis(), _synthesis("Reworded for the human")])
    squad = _squad(tmp_path, script)
    first = squad.review(REQUEST)
    before = list(script.calls)

    adjusted = squad.adjust("Make the metric a conversion rate")

    assert script.calls[len(before) :] == [("synthesis", None)]
    assert "Make the metric a conversion rate" in script.prompts[("synthesis", None)]
    assert adjusted.summary == "Reworded for the human"
    assert adjusted.opinions == first.opinions and adjusted.gaps == first.gaps
    assert squad.pending_synthesis == adjusted
    assert squad.kb.read(f"squad/committee/{squad.cycle_id}/synthesis-2.md").frontmatter["version"] == "2"
    assert squad.kb.read(f"squad/committee/{squad.cycle_id}/synthesis-1.md").frontmatter["version"] == "1"


def test_approve_stamps_the_decision_without_calling_a_model(tmp_path):
    """approve() turns the proposed brief into a Brief by code, and writes it to squad/briefs"""
    script = Committee()
    squad = _squad(tmp_path, script)
    synthesis = squad.review(REQUEST)
    cycle_id = squad.cycle_id
    calls = len(script.calls)

    brief = squad.approve("Go ahead")

    assert len(script.calls) == calls
    assert isinstance(brief, Brief)
    assert brief.human_decision.verdict == "approved" and brief.human_decision.notes == "Go ahead"
    assert BriefDraft(**brief.model_dump(exclude={"human_decision"})) == synthesis.proposed_brief
    [brief_file] = (tmp_path / "squad" / "briefs").glob("*.md")
    note = squad.kb.read(f"squad/briefs/{brief_file.name}")
    assert note.frontmatter == {"cycle_id": cycle_id, "schema_version": "1", "brief_id": brief_file.stem}
    assert Brief.model_validate_json(note.content) == brief
    decision = squad.kb.read(f"squad/committee/{cycle_id}/decision.md")
    assert decision.frontmatter["verdict"] == "approved"
    assert decision.frontmatter["brief"] == f"squad/briefs/{brief_file.name}"
    assert squad.pending_synthesis is None


def test_reject_leaves_no_brief(tmp_path):
    """reject() ends the request: a decision note with the reason, no brief, and no model call"""
    script = Committee()
    squad = _squad(tmp_path, script)
    squad.review(REQUEST)
    calls = len(script.calls)

    decision = squad.reject("Not this quarter")

    assert len(script.calls) == calls
    assert decision.verdict == "rejected"
    assert not (tmp_path / "squad" / "briefs").exists()
    note = squad.kb.read(f"squad/committee/{squad.cycle_id}/decision.md")
    assert note.frontmatter["verdict"] == "rejected" and "brief" not in note.frontmatter
    assert "Not this quarter" in note.content
    assert squad.pending_synthesis is None


def test_approve_without_notes_says_so_in_the_decision_note(tmp_path):
    """A decision with no notes is still recorded, saying there were none"""
    squad = _squad(tmp_path, Committee())
    squad.review(REQUEST)
    squad.approve()
    assert "No notes." in squad.kb.read(f"squad/committee/{squad.cycle_id}/decision.md").content


@pytest.mark.parametrize("action", ["approve", "reject", "adjust"])
def test_the_gate_needs_a_synthesis_to_decide_on(tmp_path, action):
    """approve(), reject() and adjust() are usage errors when no synthesis is waiting"""
    squad = _squad(tmp_path, Committee())
    with pytest.raises(ValueError, match="needs a synthesis"):
        getattr(squad, action)("notes")


def test_a_decision_cannot_be_taken_twice(tmp_path):
    """Once approved, the same synthesis cannot be approved or rejected again"""
    squad = _squad(tmp_path, Committee())
    squad.review(REQUEST)
    squad.approve()
    with pytest.raises(ValueError, match="needs a synthesis"):
        squad.reject("changed my mind")


def test_adjust_needs_notes(tmp_path):
    """adjust() with blank notes is a usage error and leaves the synthesis as it was"""
    squad = _squad(tmp_path, Committee())
    synthesis = squad.review(REQUEST)
    with pytest.raises(ValueError, match="needs notes"):
        squad.adjust("  ")
    assert squad.pending_synthesis == synthesis


def test_the_approved_brief_goes_to_the_product_owner_in_the_same_cycle(tmp_path):
    """submit_brief() after approve() belongs to the request's cycle, and the brief passes the door"""
    backlog = Backlog(stories=[Story(title="Landing page", acceptance_criteria=["One CTA"], needs_design=True)])
    script = Committee()
    squad = _squad(tmp_path, script)
    squad.review(REQUEST)
    cycle_id = squad.cycle_id
    brief = squad.approve()

    with squad._po.override(model=FunctionModel(_output(backlog))):  # the fake has no Product Owner script
        assert squad.submit_brief(brief) == backlog
    assert squad.cycle_id == cycle_id


def test_the_next_conversation_after_a_decision_is_a_new_request(tmp_path):
    """After approve(), chat() starts over: no history from the decided request, and a new cycle_id"""
    script = Committee(chat=[_text("Tell me more"), _text("A new one, then")])
    squad = _squad(tmp_path, script)
    squad.chat("First request")
    squad.close_request()
    first_cycle = squad.cycle_id
    squad.approve()
    script.history.pop("chat")

    squad.chat("Second request")

    assert script.history["chat"] == 1
    assert squad.cycle_id != first_cycle


# -- the trace ----------------------------------------------------------------


def test_a_round_is_traced_run_by_run_with_the_decision(tmp_path):
    """The trace has the triage, each opinion with its HX consultation, the syntheses, the reply and the decision"""
    trace_dir = tmp_path / "traces"
    diverging = _synthesis(divergences=[_divergence(growth_pm="two weeks", pm_product="a month")])
    script = Committee(syntheses=[diverging, diverging], consults={"growth_pm": "Do they share?"})
    squad = ProductSquad(
        _kb(tmp_path / "vault"), context=TEST_CONTEXT, model=FunctionModel(script), trace_dir=trace_dir
    )
    squad.review(REQUEST)
    squad.reject("no")

    _header, spans, _snapshot = load_cycle(trace_dir, squad.cycle_id)
    by_id = {span.span_id: span for span in spans}
    assert [s.agent for s in spans if s.operation == "agent_run"] == [
        "facilitator",  # triage
        "growth_pm",
        "pm_product",
        "facilitator",  # first synthesis
        "growth_pm",  # reply
        "pm_product",
        "facilitator",  # second synthesis
    ]
    assert [s.output_type for s in spans if s.output_type] == [
        "Triage", "Opinion", "Opinion", "Synthesis", "Opinion", "Opinion", "Synthesis",
    ]  # fmt: skip
    [hx_call] = [s for s in spans if s.agent == "hx" and s.operation == "model_call"]
    assert by_id[hx_call.parent_span_id].agent == "growth_pm"
    decision = spans[-1]
    assert (decision.agent, decision.operation, decision.status, decision.detail) == (
        "squad", "human_decision", "error", "rejected",
    )  # fmt: skip


def _traced_round(tmp_path, script: Committee) -> tuple[ProductSquad, list, dict]:
    squad = ProductSquad(
        _kb(tmp_path / "vault"), context=TEST_CONTEXT, model=FunctionModel(script), trace_dir=tmp_path / "traces"
    )
    squad.review(REQUEST)
    _header, spans, _snapshot = load_cycle(tmp_path / "traces", squad.cycle_id)
    return squad, spans, {span.span_id: span for span in spans}


def test_a_round_is_one_request_span_with_its_steps_under_it(tmp_path):
    """The trace has a request span, its steps as children, and each agent run inside its step"""
    diverging = _synthesis(divergences=[_divergence(growth_pm="two weeks", pm_product="a month")])
    _squad_, spans, by_id = _traced_round(tmp_path, Committee(syntheses=[diverging, diverging]))

    [request] = [s for s in spans if s.operation == "request"]
    assert (request.agent, request.parent_span_id) == ("squad", None)
    steps = sorted((s for s in spans if s.parent_span_id == request.span_id), key=lambda s: s.started_at)
    assert [s.operation for s in steps] == ["triage", "fan_out", "synthesis", "rebuttal", "synthesis"]
    assert {s.agent for s in steps} == {"squad"}

    inside = {
        step.operation + str(i): sorted(s.agent for s in spans if s.parent_span_id == step.span_id)
        for i, step in enumerate(steps)
    }
    assert inside == {
        "triage0": ["facilitator"],
        "fan_out1": ["growth_pm", "pm_product"],
        "synthesis2": ["facilitator"],
        "rebuttal3": ["growth_pm", "pm_product"],
        "synthesis4": ["facilitator"],
    }
    assert all(by_id[s.parent_span_id].operation != "request" for s in spans if s.operation == "agent_run")


def test_a_step_lasts_as_long_as_the_runs_inside_it(tmp_path):
    """A step span starts with its first run and ends with its last, and the request covers every step"""
    _squad_, spans, _by_id = _traced_round(tmp_path, Committee())

    def end(span):
        return span.started_at.timestamp() * 1000 + span.duration_ms

    [fan_out] = [s for s in spans if s.operation == "fan_out"]
    runs = [s for s in spans if s.parent_span_id == fan_out.span_id]
    assert fan_out.started_at == min(r.started_at for r in runs)
    assert end(fan_out) == pytest.approx(max(end(r) for r in runs))
    [request] = [s for s in spans if s.operation == "request"]
    steps = [s for s in spans if s.parent_span_id == request.span_id]
    assert request.started_at == min(s.started_at for s in steps)
    assert end(request) == pytest.approx(max(end(s) for s in steps))


def test_adjust_and_the_decision_hang_under_the_same_request(tmp_path):
    """adjust() adds an adjust step, and the decision a human_decision span, under the round's request span"""
    script = Committee(syntheses=[_synthesis(), _synthesis("Reworded")])
    squad, _spans, _by_id = _traced_round(tmp_path, script)
    squad.adjust("Reword it")
    squad.approve()

    _header, spans, _snapshot = load_cycle(tmp_path / "traces", squad.cycle_id)
    [request] = [s for s in spans if s.operation == "request"]
    [adjust] = [s for s in spans if s.operation == "adjust"]
    [decision] = [s for s in spans if s.operation == "human_decision"]
    assert adjust.parent_span_id == request.span_id == decision.parent_span_id
    [run] = [s for s in spans if s.parent_span_id == adjust.span_id]
    assert (run.agent, run.operation) == ("facilitator", "agent_run")


def test_a_triage_resumed_after_approval_stays_one_step(tmp_path):
    """Both triage runs, before and after an approval, are inside the same triage step of one request"""
    write = _tool_call("write_note", path="docs/request.md", content="notes")
    script = Committee(triage=[write, _output(_triage("growth_pm"))])
    squad = ProductSquad(
        _kb(tmp_path / "vault"), context=TEST_CONTEXT, model=FunctionModel(script), trace_dir=tmp_path / "traces"
    )
    pending = squad.review(REQUEST)
    squad.review(deferred_tool_results=pending.build_results(approve_all=True))

    _header, spans, _snapshot = load_cycle(tmp_path / "traces", squad.cycle_id)
    [triage] = [s for s in spans if s.operation == "triage"]
    assert len([s for s in spans if s.operation == "request"]) == 1
    assert [s.agent for s in spans if s.parent_span_id == triage.span_id] == ["facilitator", "facilitator"]


# -- the Gantt of a live run --------------------------------------------------


def test_gantt_draws_the_round_from_memory_without_a_trace_dir(tmp_path):
    """gantt() charts the cycle with no trace_dir: the request's steps, and each PM on its own rows"""
    squad = _squad(tmp_path, Committee())
    assert "No spans" in squad.gantt().render()

    squad.review(REQUEST)

    chart = squad.gantt(use_colors=False, width=100).render()
    for row in (" squad", " facilitator", " growth_pm", " pm_product"):
        assert f"\n{row} \n" in chart
    for label in ("✓ request", "✓   fan_out", "✓   synthesis", "✓     agent_run", "✓       model_call"):
        assert label in chart


def test_gantt_shows_the_pms_running_at_the_same_time(tmp_path):
    """In the chart's data the PMs' runs overlap: each starts before the other ends"""
    squad = _squad(tmp_path, Committee())
    squad.review(REQUEST)
    runs = [s for s in squad.gantt().spans if s.agent in ("growth_pm", "pm_product") and "agent_run" in s.name]
    assert len(runs) == 2
    assert runs[0].start_ms < runs[1].end_ms and runs[1].start_ms < runs[0].end_ms


def test_gantt_matches_the_trace_file_and_survives_a_resume(tmp_path):
    """The chart from memory is the chart from the file, and resume() brings the cycle's spans back"""
    from pydantic_squads import TerminalGantt

    squad, _spans, _by_id = _traced_round(tmp_path, Committee())
    from_file = TerminalGantt.from_jsonl(tmp_path / "traces" / f"{squad.cycle_id}.jsonl", use_colors=False)
    assert squad.gantt(use_colors=False).render() == from_file.render()

    resumed = ProductSquad(
        _kb(tmp_path / "vault"), context=TEST_CONTEXT, model=FunctionModel(Committee()), trace_dir=tmp_path / "traces"
    )
    resumed.resume(squad.cycle_id)
    assert resumed.gantt(use_colors=False).render() == from_file.render()


def test_gantt_starts_over_with_the_next_request(tmp_path):
    """After a decision, the next conversation's chart no longer has the decided request's spans"""
    script = Committee(chat=[_text("A new one, then")])
    squad = _squad(tmp_path, script)
    squad.review(REQUEST)
    squad.approve()
    squad.chat("Second request")
    names = [span.name.strip() for span in squad.gantt().spans]
    assert "request" not in names and names.count("agent_run") == 1


def test_an_approval_is_traced_as_ok(tmp_path):
    """approve() records a human_decision span with status ok"""
    trace_dir = tmp_path / "traces"
    squad = ProductSquad(
        _kb(tmp_path / "vault"), context=TEST_CONTEXT, model=FunctionModel(Committee()), trace_dir=trace_dir
    )
    squad.review(REQUEST)
    squad.approve()
    _header, spans, _snapshot = load_cycle(trace_dir, squad.cycle_id)
    assert (spans[-1].operation, spans[-1].status, spans[-1].detail) == ("human_decision", "ok", "approved")
