"""The committee: PMs give opinions in parallel, and a synthesis keeps their disagreements.

Needs the optional `ai` extra. Agents are built in `assembly.py`; this
module only runs them, so it never needs to import it. Nothing here loops:
a round is opinions, a synthesis, and at most one rebuttal followed by a
second synthesis (ADR 0013).
"""

import asyncio
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic_ai import Agent, ModelRetry, UsageLimits
from pydantic_ai.messages import ModelMessage

from pydantic_squads.product.contracts import (
    Divergence,
    FindingKind,
    GapGroup,
    HXAnswer,
    KnowledgeGap,
    Opinion,
    OpinionDraft,
    Synthesis,
    SynthesisDraft,
)
from pydantic_squads.product.knowledge import KnowledgeBase
from pydantic_squads.product.observability import HX_SINK, SpanSink

PMAgents = Mapping[str, Agent[KnowledgeBase, OpinionDraft]]


@dataclass(frozen=True)
class OpinionRun:
    """One PM's opinion, with what its run left behind for the trace."""

    opinion: Opinion
    messages: list[ModelMessage]
    sink: SpanSink
    duration_ms: float


@dataclass(frozen=True)
class SynthesisDeps:
    """What a synthesis run is checked against: the PMs whose opinions it consolidates."""

    roles: frozenset[str]


@dataclass(frozen=True)
class SynthesisRun:
    """One synthesis by the Facilitator, with its messages for the trace."""

    draft: SynthesisDraft
    messages: list[ModelMessage]
    duration_ms: float


@dataclass(frozen=True)
class Round:
    """Everything one round of the committee produced."""

    opinions: list[OpinionRun]
    rebuttals: list[OpinionRun]
    syntheses: list[SynthesisRun]  # one, or two when there was a rebuttal
    synthesis: Synthesis


FACILITATOR = "facilitator"  # who asked HX what the PMs are handed as shared evidence


def evidence_block(evidence: Sequence[HXAnswer]) -> str:
    """HX answers as compact text for a prompt: the question, the summary, and each finding with its sources."""
    blocks = []
    for answer in evidence:
        findings = "\n".join(
            f"- [{finding.kind.value}] {finding.claim}"
            + (f" (sources: {', '.join(finding.sources)})" if finding.sources else "")
            for finding in answer.findings
        )
        blocks.append(f"Question: {answer.question}\nSummary: {answer.summary}\n{findings}")
    return "\n\n".join(blocks)


def opinion_prompt(request: str, evidence: Sequence[HXAnswer] = ()) -> str:
    parts = [
        "Give your opinion on the request below, from your role's point of view only.\n"
        "Consult HX before claiming anything about users, and cite the notes your opinion rests on "
        "by their exact path. You do not see the other PMs' opinions and must not guess them.\n"
        "Be brief: the recommendation in one short paragraph, and at most five risks and three "
        "questions for the human, one sentence each. Leave out what any PM would say.",
        f"Request:\n{request}",
    ]
    if evidence:
        parts.append(
            "HX already answered the questions below for this request. Every PM has these answers. "
            "Do not ask HX again what they settle: consult it only for what your own view needs and "
            "they leave open.\n\n" + evidence_block(evidence)
        )
    return "\n\n".join(parts)


def rebuttal_prompt(request: str, own: Opinion, divergences: Sequence[Divergence]) -> str:
    points = "\n\n".join(
        f"Topic: {d.topic}\n" + "\n".join(f"- {role}: {position}" for role, position in d.positions.items())
        for d in divergences
    )
    return (
        "The PMs disagree on the points below. This is your one reply: keep your opinion or revise it, "
        "and say why. Answer from your role's point of view only; you will not be asked again.\n"
        "Be brief: in the recommendation say only what you keep or change on these points and why, in "
        "one short paragraph, without restating the rest of your opinion. List a risk or a question "
        "only if it is new.\n\n"
        f"Request:\n{request}\n\n"
        f"Your opinion:\n{own.model_dump_json(indent=2)}\n\n"
        f"Points of disagreement:\n{points}"
    )


def synthesis_prompt(
    request: str,
    opinions: Sequence[Opinion],
    rebuttals: Sequence[Opinion],
    gaps: Sequence[KnowledgeGap],
    *,
    previous: SynthesisDraft | None = None,
    notes: str | None = None,
) -> str:
    parts = [
        "Consolidate the PMs' opinions on this request for the human to decide.\n"
        "Do not add an opinion or a recommendation of your own. List every point the PMs disagree on as "
        "a divergence, keyed by role id, with each PM's position as that PM put it: do not settle or "
        "soften it. Then propose the brief the human would approve, built only from the request and "
        "the opinions, with the PMs behind it as owner_roles.\n"
        "Be brief: the summary in one short paragraph, and each position in one or two sentences. "
        "The human has the full opinions next to this, so do not repeat them.",
        f"Request:\n{request}",
        "Opinions:\n" + "\n".join(o.model_dump_json(indent=2) for o in opinions),
    ]
    if rebuttals:
        parts.append(
            "Replies after the first synthesis (each PM answered once):\n"
            + "\n".join(o.model_dump_json(indent=2) for o in rebuttals)
        )
    if gaps:
        parts.append(
            "What HX said the knowledge base does not know, as it reported each gap:\n"
            + "\n".join(f"{number}. {g.gap}" for number, g in enumerate(gaps, start=1))
            + "\nHX often words the same gap differently on each consultation. In gap_groups, put together "
            "the gaps that say the same thing: one plain sentence per group, and the numbers of its gaps. "
            "A gap that matches no other is a group of one. Do not drop a gap, and do not soften one or "
            "explain it away."
        )
    if previous is not None:
        parts.append(f"Your previous synthesis:\n{previous.model_dump_json(indent=2)}")
    if notes is not None:
        parts.append(f"The human asked for this adjustment. Redo the synthesis with it:\n{notes}")
    return "\n\n".join(parts)


def check_synthesis(deps: SynthesisDeps, draft: SynthesisDraft) -> SynthesisDraft:
    """Refuse a synthesis that puts a position in the mouth of a PM that gave no opinion."""
    for divergence in draft.divergences:
        unknown = sorted(set(divergence.positions) - deps.roles)
        if unknown:
            raise ModelRetry(
                f"divergence '{divergence.topic}' cites {unknown}, which gave no opinion: "
                f"key each position by one of {sorted(deps.roles)}"
            )
    return draft


def consolidate_gaps(runs: Sequence[OpinionRun], shared: Sequence[HXAnswer] = ()) -> list[KnowledgeGap]:
    """Every gap HX reported to the PMs in `runs`, with the questions that surfaced it.

    `shared` are the answers HX gave the Facilitator before the round: their
    gaps are listed too, as asked by the Facilitator.

    Only gaps worded the same (ignoring case and spacing) are merged here.
    HX usually rewords a gap on each consultation, so this is the raw list:
    the Facilitator groups it in the synthesis, and `group_gaps` holds that
    grouping to every gap in it.
    """
    found: dict[str, tuple[str, list[str], list[str]]] = {}
    asked = [(FACILITATOR, list(shared)), *((run.opinion.role, run.sink.hx_answers) for run in runs)]
    for role, answers in asked:
        for answer in answers:
            for finding in answer.findings:
                if finding.kind != FindingKind.GAP:
                    continue
                key = " ".join(finding.claim.lower().split())
                _gap, questions, asked_by = found.setdefault(key, (finding.claim, [], []))
                if answer.question not in questions:
                    questions.append(answer.question)
                if role not in asked_by:
                    asked_by.append(role)
    return [KnowledgeGap(gap=gap, questions=questions, asked_by=asked_by) for gap, questions, asked_by in found.values()]


def group_gaps(raw: Sequence[KnowledgeGap], groups: Sequence[GapGroup]) -> list[KnowledgeGap]:
    """`raw` as the Facilitator grouped it, with every raw gap in exactly one group, whatever it wrote.

    A group's questions and PMs are those of its gaps, joined here. A gap
    the Facilitator put in two groups stays in the first; a number that is
    no gap is ignored; and a gap it left out becomes a group of its own, in
    HX's words. So grouping can make the list shorter but cannot lose a gap.
    """
    placed: set[int] = set()
    grouped: list[KnowledgeGap] = []
    for group in groups:
        members = [n for n in dict.fromkeys(group.gaps) if 1 <= n <= len(raw) and n not in placed]
        if not members:
            continue
        placed.update(members)
        gaps = [raw[n - 1] for n in members]
        grouped.append(
            KnowledgeGap(
                gap=group.summary,
                questions=list(dict.fromkeys(q for gap in gaps for q in gap.questions)),
                asked_by=list(dict.fromkeys(role for gap in gaps for role in gap.asked_by)),
            )
        )
    grouped.extend(gap for number, gap in enumerate(raw, start=1) if number not in placed)
    return grouped


async def _pm_run(
    agent: Agent[KnowledgeBase, OpinionDraft],
    role_id: str,
    kb: KnowledgeBase,
    prompt: str,
    usage_limits: UsageLimits | None,
) -> OpinionRun:
    sink = SpanSink()
    sink_token = HX_SINK.set(sink)
    started = time.monotonic()
    try:
        result = await agent.run(prompt, deps=kb, usage_limits=usage_limits)
    finally:
        HX_SINK.reset(sink_token)
    return OpinionRun(
        opinion=Opinion(role=role_id, **result.output.model_dump()),
        messages=result.new_messages(),
        sink=sink,
        duration_ms=(time.monotonic() - started) * 1000,
    )


async def opinion(
    agent: Agent[KnowledgeBase, OpinionDraft],
    role_id: str,
    kb: KnowledgeBase,
    request: str,
    *,
    evidence: Sequence[HXAnswer] = (),
    usage_limits: UsageLimits | None = None,
) -> OpinionRun:
    """Run `agent` once on `request`, with no message history, and stamp the opinion with `role_id`.

    The role is stamped here, not written by the model: an opinion cannot
    claim to come from another PM. `evidence` is what HX already answered
    for this request: the PM is handed it instead of asking again.
    """
    return await _pm_run(agent, role_id, kb, opinion_prompt(request, evidence), usage_limits)


async def opinions(
    agents: PMAgents,
    kb: KnowledgeBase,
    request: str,
    *,
    evidence: Sequence[HXAnswer] = (),
    usage_limits: UsageLimits | None = None,
) -> list[OpinionRun]:
    """The opinion of every PM in `agents` on `request`, all at once, in the order of `agents`.

    Each PM runs on its own: none sees another's opinion.
    """
    return list(
        await asyncio.gather(
            *(
                opinion(agent, role_id, kb, request, evidence=evidence, usage_limits=usage_limits)
                for role_id, agent in agents.items()
            )
        )
    )


async def rebuttals(
    agents: PMAgents,
    kb: KnowledgeBase,
    request: str,
    given: Sequence[Opinion],
    divergences: Sequence[Divergence],
    *,
    usage_limits: UsageLimits | None = None,
) -> list[OpinionRun]:
    """One reply from each PM cited in `divergences`, all at once; the others are not asked.

    A PM sees its own opinion and the points it is cited in, positions
    included. This is called at most once per round: a reply is never
    answered.
    """
    runs = []
    for own in given:
        cited = [d for d in divergences if own.role in d.positions]
        if cited:
            runs.append(_pm_run(agents[own.role], own.role, kb, rebuttal_prompt(request, own, cited), usage_limits))
    return list(await asyncio.gather(*runs))


async def synthesize(
    agent: Agent[SynthesisDeps, SynthesisDraft],
    request: str,
    given: Sequence[Opinion],
    replies: Sequence[Opinion],
    gaps: Sequence[KnowledgeGap],
    *,
    previous: SynthesisDraft | None = None,
    notes: str | None = None,
    usage_limits: UsageLimits | None = None,
) -> SynthesisRun:
    """One synthesis of `given` (and `replies`), in a run with no tools and no message history."""
    prompt = synthesis_prompt(request, given, replies, gaps, previous=previous, notes=notes)
    started = time.monotonic()
    result = await agent.run(
        prompt, deps=SynthesisDeps(roles=frozenset(o.role for o in given)), usage_limits=usage_limits
    )
    return SynthesisRun(
        draft=result.output, messages=result.new_messages(), duration_ms=(time.monotonic() - started) * 1000
    )


def build_synthesis(
    request: str,
    draft: SynthesisDraft,
    given: Sequence[Opinion],
    replies: Sequence[Opinion],
    gaps: Sequence[KnowledgeGap],
) -> Synthesis:
    """`draft` with what the runtime attaches: the request, the opinions as given, the replies and the gaps.

    `gaps` are the raw ones, as HX reported them; the synthesis gets both
    those and the grouped list built from the draft's `gap_groups`.
    """
    return Synthesis(
        **draft.model_dump(),
        request=request,
        opinions=list(given),
        rebuttals=list(replies),
        gaps=group_gaps(gaps, draft.gap_groups),
        raw_gaps=list(gaps),
    )


async def run_round(
    pm_agents: PMAgents,
    synthesis_agent: Agent[SynthesisDeps, SynthesisDraft],
    kb: KnowledgeBase,
    request: str,
    *,
    evidence: Sequence[HXAnswer] = (),
    usage_limits: UsageLimits | None = None,
) -> Round:
    """One round: every PM's opinion in parallel, a synthesis, and at most one rebuttal.

    `evidence` is what HX already answered the Facilitator for this request:
    every PM gets it, so the same question is not put to HX once per PM.

    When the first synthesis finds divergences, the PMs cited in them reply
    once and the synthesis is redone with those replies. Whatever still
    diverges after that stays in the synthesis for the human: there is no
    second rebuttal.
    """
    opinion_runs = await opinions(pm_agents, kb, request, evidence=evidence, usage_limits=usage_limits)
    given = [run.opinion for run in opinion_runs]
    gaps = consolidate_gaps(opinion_runs, evidence)
    first = await synthesize(synthesis_agent, request, given, [], gaps, usage_limits=usage_limits)
    if not first.draft.divergences:
        return Round(opinion_runs, [], [first], build_synthesis(request, first.draft, given, [], gaps))

    rebuttal_runs = await rebuttals(
        pm_agents, kb, request, given, first.draft.divergences, usage_limits=usage_limits
    )
    replies = [run.opinion for run in rebuttal_runs]
    gaps = consolidate_gaps([*opinion_runs, *rebuttal_runs], evidence)
    second = await synthesize(
        synthesis_agent, request, given, replies, gaps, previous=first.draft, usage_limits=usage_limits
    )
    return Round(
        opinion_runs, rebuttal_runs, [first, second], build_synthesis(request, second.draft, given, replies, gaps)
    )
