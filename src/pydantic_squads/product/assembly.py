"""Assemble the product squad into runnable Pydantic AI agents.

Needs the optional `ai` extra (`pydantic-ai-slim`). The rest of
`pydantic_squads.product` stays dependency-free (ADR 0001); nothing else in
this package imports this module, so it works without `pydantic_ai` installed.
The agents built here are run by `ProductSquad`, and the committee's PMs
by `committee.py`.
"""

import asyncio
import fnmatch
import re
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic_ai import (
    Agent,
    ApprovalRequired,
    DeferredToolRequests,
    DeferredToolResults,
    ModelRetry,
    RunContext,
    UsageLimits,
)
from pydantic_ai.messages import ModelMessage

from pydantic_squads import Role, Squad
from pydantic_squads.product import committee
from pydantic_squads.product.claude_code import resolve_model
from pydantic_squads.product.contracts import (
    Backlog,
    Brief,
    BriefDraft,
    BriefRecord,
    BriefRejection,
    ContentPack,
    HumanDecision,
    HXAnswer,
    KnowledgeGap,
    MarketingGuidance,
    Opinion,
    OpinionDraft,
    Prototype,
    SendBack,
    Span,
    Synthesis,
    SynthesisDraft,
    Triage,
    design_coverage_errors,
    validate_brief,
)
from pydantic_squads.product.knowledge import (
    KnowledgeBase,
    Note,
    NoteExcerpt,
    SerializedKnowledgeBase,
    excerpt,
)
from pydantic_squads.product.observability import (
    HX_SINK,
    CycleRecorder,
    SpanSink,
    deserialize_history,
    extract_spans,
    load_cycle,
    merge_nested_spans,
    serialize_history,
)
from pydantic_squads.product.notes import brief_note, decision_note, founder_questions_note, synthesis_note
from pydantic_squads.product.squad import COMMITTEE_ROLES, Language, build_product_squad
from pydantic_squads.visualization import TerminalGantt


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def _normalize_path(path: str) -> str | None:
    """Canonicalize a vault-relative path before it is checked against a glob.

    Resolves `.`/`..` segments so a permission glob can't be bypassed with
    path traversal (e.g. `squad/bets/../../docs/x.md` really means
    `docs/x.md`). Returns `None` for an absolute path or one that would
    escape the vault root.
    """
    posix_path = PurePosixPath(path)
    if posix_path.is_absolute():
        return None
    parts: list[str] = []
    for part in posix_path.parts:
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)


def _path_allowed(path: str, patterns: list[str]) -> bool:
    normalized = _normalize_path(path)
    return normalized is not None and _matches(normalized, patterns)


# A committee synthesis repeats every opinion of its round: it matches any
# query about the request, is far larger than the notes it was made from,
# and is no evidence of anything. It stays readable by path, and the
# decision and the brief next to it stay searchable (ADR 0015).
_NOT_SEARCHABLE = ["squad/committee/*/synthesis-*.md"]
_SEARCH_LIMIT = 8  # results a search or a tag listing returns, best first


def _findable(role: Role, notes: list[Note]) -> list[Note]:
    return [
        n for n in notes if _path_allowed(n.path, role.permissions.read) and not _matches(n.path, _NOT_SEARCHABLE)
    ]


def _search_notes(role: Role, kb: KnowledgeBase, query: str) -> list[Note]:
    return _findable(role, kb.search(query))


def _list_by_tag(role: Role, kb: KnowledgeBase, tag: str) -> list[Note]:
    return _findable(role, kb.list_by_tag(tag))


def _read_note(role: Role, kb: KnowledgeBase, path: str) -> Note:
    normalized = _normalize_path(path)
    if normalized is None:
        raise ModelRetry(f"not permitted to read '{path}'")
    try:
        note = kb.read(normalized)
    except (OSError, ValueError):
        # The knowledge base may resolve a bare name or [[wikilink]] to a real path,
        # so suggest real paths the role can read instead of letting the model guess again.
        similar = [n.path for n in _search_notes(role, kb, PurePosixPath(normalized).name)][:5]
        hint = f" Did you mean: {', '.join(similar)}?" if similar else " Use search_notes to find its path."
        raise ModelRetry(f"note '{normalized}' does not exist or cannot be read.{hint}") from None
    # Checked on the resolved path: a bare name may resolve into a folder the role can't read.
    if not _path_allowed(note.path, role.permissions.read):
        raise ModelRetry(f"not permitted to read '{path}'")
    return note


def _write_note(role: Role, kb: KnowledgeBase, path: str, content: str, *, approved: bool) -> str:
    normalized = _normalize_path(path)
    if normalized is None:
        raise ModelRetry(f"invalid path '{path}'")
    if _matches(normalized, role.permissions.write):
        kb.write(normalized, content)
        return f"wrote '{normalized}'"
    if _matches(normalized, role.permissions.write_with_approval):
        if not approved:
            raise ApprovalRequired(metadata={"path": normalized})
        kb.write(normalized, content)
        return f"wrote '{normalized}' (approved)"
    raise ModelRetry(f"not permitted to write to '{normalized}'")


_NOTE_TOOL_RETRIES = 3  # a wrong path guess shouldn't end the whole turn
_HX_OUTPUT_RETRIES = 3  # a mis-cited source shouldn't end the whole conversation


def _register_note_tools(agent: Agent[KnowledgeBase, Any], role: Role) -> None:
    """Register only the note tools listed in `role.tools`, scoped to `role.permissions`."""

    if "search_notes" in role.tools:

        @agent.tool(retries=_NOTE_TOOL_RETRIES)
        def search_notes(ctx: RunContext[KnowledgeBase], query: str) -> list[NoteExcerpt]:
            """Search the knowledge base by keywords. Returns the 8 best matches, best first, as
            excerpts around what matched, not whole notes: call read_note on a note before you
            rely on it or cite it. Use a narrower query to reach other notes."""
            return [excerpt(note, query) for note in _search_notes(role, ctx.deps, query)[:_SEARCH_LIMIT]]

    if "list_by_tag" in role.tools:

        @agent.tool(retries=_NOTE_TOOL_RETRIES)
        def list_by_tag(ctx: RunContext[KnowledgeBase], tag: str) -> list[NoteExcerpt]:
            """List up to 8 notes carrying `tag`, each as the beginning of the note, not the whole
            note: call read_note on a note before you rely on it or cite it."""
            return [excerpt(note, limit=1) for note in _list_by_tag(role, ctx.deps, tag)[:_SEARCH_LIMIT]]

    if "read_note" in role.tools:

        @agent.tool(retries=_NOTE_TOOL_RETRIES)
        def read_note(ctx: RunContext[KnowledgeBase], path: str) -> Note:
            """Read a single note by its vault-relative path, including folder and `.md`
            (e.g. `docs/x.md`), as returned by search_notes. Obsidian `[[wikilinks]]` also work."""
            return _read_note(role, ctx.deps, path)

    if "write_note" in role.tools:

        @agent.tool(retries=_NOTE_TOOL_RETRIES)
        def write_note(ctx: RunContext[KnowledgeBase], path: str, content: str) -> str:
            """Write a note by its path. Some paths require human approval first.

            A `.md` note is for a person to read: give it one `#` title, `##` sections,
            short paragraphs and lists. Never write raw JSON as its content."""
            return _write_note(role, ctx.deps, path, content, approved=ctx.tool_call_approved)


# A model often cites a section along with the note: `docs/x.md (§1 and §6)`,
# `docs/x.md#Goals`, `docs/x.md, section 2`. The note is what must exist, so
# whatever follows the `.md` is dropped.
_SECTION_SUFFIX_RE = re.compile(r"(?<=\.md)[\s(#§,;:].*$", re.DOTALL)


def _clean_source(kb: KnowledgeBase, source: str) -> str:
    """The path of the note `source` cites; raises `ModelRetry` when no such note exists."""
    for candidate in dict.fromkeys([source, _SECTION_SUFFIX_RE.sub("", source.strip())]):
        try:
            return kb.read(candidate).path
        except (OSError, ValueError):
            continue
    raise ModelRetry(
        f"source '{source}' does not exist in the knowledge base: cite the note's exact path only "
        "(e.g. `docs/x.md`), with no section or page"
    )


def _sources_exist(kb: KnowledgeBase, output: HXAnswer) -> HXAnswer:
    findings = [
        finding.model_copy(update={"sources": [_clean_source(kb, source) for source in finding.sources]})
        for finding in output.findings
    ]
    return output if findings == output.findings else output.model_copy(update={"findings": findings})


def _register_source_validator(agent: Agent[KnowledgeBase, HXAnswer]) -> None:
    @agent.output_validator
    def validate_sources(ctx: RunContext[KnowledgeBase], output: HXAnswer) -> HXAnswer:
        return _sources_exist(ctx.deps, output)


def _check_triage(triage: Triage) -> Triage:
    """A `Triage` may only name PMs of the committee; each one is heard once."""
    unknown = sorted(set(triage.roles) - set(COMMITTEE_ROLES))
    if unknown:
        raise ModelRetry(f"{unknown} give no opinion: choose among {list(COMMITTEE_ROLES)}")
    return triage.model_copy(update={"roles": list(dict.fromkeys(triage.roles))})


def _register_triage_validator(agent: Agent[KnowledgeBase, Any]) -> None:
    @agent.output_validator
    def validate_triage(ctx: RunContext[KnowledgeBase], output: Any) -> Any:
        return _check_triage(output) if isinstance(output, Triage) else output


def _register_opinion_source_validator(agent: Agent[KnowledgeBase, OpinionDraft]) -> None:
    """Hold a PM's opinion to the same rule as HX: every source it cites is a note that exists."""

    @agent.output_validator
    def validate_sources(ctx: RunContext[KnowledgeBase], output: OpinionDraft) -> OpinionDraft:
        return output.model_copy(update={"sources": [_clean_source(ctx.deps, source) for source in output.sources]})


async def _consult_hx(
    hx_agent: Agent[KnowledgeBase, HXAnswer],
    kb: KnowledgeBase,
    usage: Any,
    question: str,
    *,
    tool_call_id: str | None = None,
    sink: SpanSink | None = None,
) -> HXAnswer:
    # Nested calls must use `run`, not `run_sync`: pydantic_ai forbids a nested
    # sync run inside a tool, since it could deadlock the outer run's event loop.
    # No message history is passed: every consultation is a fresh, stateless run.
    result = await hx_agent.run(question, deps=kb, usage=usage)
    # The question is the caller's, word for word: a gap is later reported
    # with the question that surfaced it (ADR 0013).
    answer = result.output.model_copy(update={"question": question})
    # `sink` (ADR 0006) is how the outer run's span extraction later finds
    # HX's own spans: they never appear in the caller's `all_messages()`.
    if sink is not None:
        sink.hx_answers.append(answer)
        if tool_call_id is not None:
            sink.nested_runs[tool_call_id] = ("hx", result.all_messages())
    return answer


def _register_consult_hx(
    caller_agent: Agent[KnowledgeBase, Any],
    caller_role: Role,
    hx_agent: Agent[KnowledgeBase, Any],
) -> None:
    if "consult_hx" not in caller_role.tools:
        return

    @caller_agent.tool
    async def consult_hx(ctx: RunContext[KnowledgeBase], question: str) -> HXAnswer:
        """Ask HX a question about users; returns cited findings, each classified as evidence, assumption or gap."""
        return await _consult_hx(
            hx_agent, ctx.deps, ctx.usage, question, tool_call_id=ctx.tool_call_id, sink=HX_SINK.get()
        )


async def _consult_pm_marketing(
    marketing_agent: Agent[KnowledgeBase, MarketingGuidance],
    kb: KnowledgeBase,
    usage: Any,
    question: str,
    *,
    tool_call_id: str | None = None,
    sink: SpanSink | None = None,
) -> MarketingGuidance:
    # Like `_consult_hx`: a nested, stateless run, collected through `sink`.
    result = await marketing_agent.run(question, deps=kb, usage=usage)
    if sink is not None and tool_call_id is not None:
        sink.nested_runs[tool_call_id] = ("pm_marketing", result.all_messages())
    # The question is the caller's, word for word: the model does not get to rephrase it.
    return result.output.model_copy(update={"question": question})


def _register_marketing_source_validator(agent: Agent[KnowledgeBase, MarketingGuidance]) -> None:
    @agent.output_validator
    def validate_sources(ctx: RunContext[KnowledgeBase], output: MarketingGuidance) -> MarketingGuidance:
        return output.model_copy(update={"sources": [_clean_source(ctx.deps, source) for source in output.sources]})


def _register_consult_pm_marketing(
    caller_agent: Agent[KnowledgeBase, Any],
    caller_role: Role,
    marketing_agent: Agent[KnowledgeBase, Any],
    on_unanswered: Callable[[str], None] | None = None,
) -> None:
    """Register `consult_pm_marketing` when `caller_role` declares it.

    `on_unanswered` is told each question the PM Marketing could not answer
    from the knowledge base: those are the only ones a caller may take to
    the founder (ADR 0012).
    """
    if "consult_pm_marketing" not in caller_role.tools:
        return

    @caller_agent.tool
    async def consult_pm_marketing(ctx: RunContext[KnowledgeBase], question: str) -> MarketingGuidance:
        """Ask the PM Marketing a positioning, tone, brand or naming question. It answers from the
        knowledge base, with sources, or says the knowledge base does not settle it."""
        guidance = await _consult_pm_marketing(
            marketing_agent, ctx.deps, ctx.usage, question, tool_call_id=ctx.tool_call_id, sink=HX_SINK.get()
        )
        if not guidance.answered and on_unanswered is not None:
            on_unanswered(question)
        return guidance


@dataclass(frozen=True)
class _DesignRun:
    """What the Designer's output validator checks a `Prototype` against."""

    backlog: Backlog
    design_dir: str  # squad/design/<cycle_id>, where the prototype must be written
    # The brand questions the PM Marketing could not answer in this run: only
    # these may become founder questions with origin="positioning" (ADR 0012).
    unanswered_marketing: list[str] = field(default_factory=list)


# An external reference in an src/href attribute or a CSS url()/@import:
# the prototype must open from disk, offline (ADR 0007).
_EXTERNAL_URL_RE = re.compile(
    r"""(?:\b(?:src|href)\s*=\s*["']?|url\(\s*["']?|@import\s+["']?)\s*(?:https?:)?//""",
    re.IGNORECASE,
)


def _check_prototype(kb: KnowledgeBase, run: _DesignRun, prototype: Prototype) -> Prototype:
    """The deterministic gate on a Designer `Prototype` (ADR 0007), as `ModelRetry`s."""
    errors = design_coverage_errors(run.backlog, prototype)
    if errors:
        raise ModelRetry("The prototype does not match the backlog:\n" + "\n".join(f"- {e}" for e in errors))
    path = _normalize_path(prototype.html_path)
    if path is None or not path.startswith(f"{run.design_dir}/") or not path.endswith(".html"):
        raise ModelRetry(f"html_path must be an .html file under '{run.design_dir}/'")
    try:
        html = kb.read(path).content
    except (OSError, ValueError):
        raise ModelRetry(f"'{path}' does not exist: write the prototype there before returning it") from None
    if _EXTERNAL_URL_RE.search(html):
        raise ModelRetry(f"'{path}' references an external URL: inline everything so it opens offline")
    for question in prototype.founder_questions:
        if question.origin == "positioning" and question.marketing_question not in run.unanswered_marketing:
            raise ModelRetry(
                f"founder question '{question.question}' is about positioning, but the PM Marketing was not asked "
                f"'{question.marketing_question}' or did answer it. Ask consult_pm_marketing first, and take to the "
                "founder only what it could not answer, with marketing_question set to the exact question you "
                f"asked. Unanswered so far: {run.unanswered_marketing}"
            )
    return prototype


def _check_content_pack(kb: KnowledgeBase, content_dir: str, pack: ContentPack) -> ContentPack:
    """The deterministic gate on a `ContentPack`: every piece is a file written under `content_dir`."""
    pieces = []
    for piece in pack.pieces:
        path = _normalize_path(piece.path)
        if path is None or not path.startswith(f"{content_dir}/"):
            raise ModelRetry(f"'{piece.path}' must be a file under '{content_dir}/'")
        try:
            kb.read(path)
        except (OSError, ValueError):
            raise ModelRetry(f"'{path}' does not exist: write the piece there before returning it") from None
        pieces.append(piece.model_copy(update={"path": path}))
    return pack.model_copy(update={"pieces": pieces})


def _register_content_validator(agent: Agent[KnowledgeBase, Any], content_box: list[str | None]) -> None:
    @agent.output_validator
    def validate_content(ctx: RunContext[KnowledgeBase], output: ContentPack) -> ContentPack:
        content_dir = content_box[0]
        assert content_dir is not None  # ProductSquad.produce_content sets it for every run
        return _check_content_pack(ctx.deps, content_dir, output)


def _register_prototype_validator(agent: Agent[KnowledgeBase, Any], design_box: list[_DesignRun | None]) -> None:
    @agent.output_validator
    def validate_prototype(ctx: RunContext[KnowledgeBase], output: Any) -> Any:
        if not isinstance(output, Prototype):
            return output  # a SendBack or a DeferredToolRequests has nothing to check
        run = design_box[0]
        assert run is not None  # ProductSquad._run_designer sets it for every designer run
        return _check_prototype(ctx.deps, run, output)


_CONTEXT_HEADING: dict[Language, str] = {"en": "Product context", "pt-BR": "Contexto do produto"}


def _with_context(instructions: str, context: str, language: Language) -> str:
    return f"{instructions}\n\n## {_CONTEXT_HEADING[language]}\n{context}"


def _skill_kwargs(build_role_skills: Any, all_skills_dirs: list[Path] | None, role: Role) -> dict[str, list[Any]]:
    """`capabilities=`/`toolsets=` kwargs exposing `role`'s skills, or `{}` when skills are off."""
    if build_role_skills is None:
        return {}
    capability, toolset = build_role_skills(role, all_skills_dirs)
    kwargs: dict[str, list[Any]] = {}
    if capability is not None:
        kwargs["capabilities"] = [capability]
    if toolset is not None:
        kwargs["toolsets"] = [toolset]
    return kwargs


@dataclass(frozen=True)
class _Agents:
    """Every agent of the squad, with the per-run slots their validators read."""

    facilitator: Agent  # the conversation
    triager: Agent  # the Facilitator closing that conversation into a Triage
    synthesizer: Agent  # the Facilitator consolidating opinions: no tools at all
    hx: Agent
    po: Agent
    designer: Agent
    pms: dict[str, Agent]  # the committee: one opinion agent per PM
    marketing: Agent  # the PM Marketing answering a brand question
    social: Agent
    design_box: list[_DesignRun | None]
    content_box: list[str | None]


def _build_agents(
    squad: Squad,
    model: Any,
    models: Mapping[str, Any],
    context: str,
    language: Language,
    skills_dirs: list[Path] | None,
) -> _Agents:
    # Imported lazily and only when skills are actually requested, so the `ai`
    # extra alone (skills_dirs=None, the default) never needs the `skills`
    # extra installed.
    build_role_skills: Any = None
    all_skills_dirs: list[Path] | None = None
    if skills_dirs is not None:
        from pydantic_squads.product.skills_integration import LIBRARY_SKILLS_DIR, build_role_skills

        all_skills_dirs = [LIBRARY_SKILLS_DIR, *skills_dirs]

    # "claude-code" / "claude-code:<model>" runs on the local Claude Code login (ADR 0008).
    default_model = resolve_model(model)

    def model_for(role_id: str) -> Any:
        """The model `role_id` runs on: its own from `models`, or the squad's."""
        return resolve_model(models[role_id]) if role_id in models else default_model

    facilitator_prompt = _with_context(squad.instructions_for("facilitator"), context, language)
    facilitator = Agent(
        model_for("facilitator"),
        deps_type=KnowledgeBase,
        output_type=[str, DeferredToolRequests],
        system_prompt=facilitator_prompt,
        **_skill_kwargs(build_role_skills, all_skills_dirs, squad["facilitator"]),
    )
    _register_note_tools(facilitator, squad["facilitator"])

    # The same role, tools and conversation, closing it into a Triage. A
    # separate agent because pydantic_ai does not allow a per-run output
    # type on an agent that has output validators.
    triager = Agent(
        model_for("facilitator"),
        deps_type=KnowledgeBase,
        output_type=[Triage, DeferredToolRequests],
        retries={"output": _HX_OUTPUT_RETRIES},
        system_prompt=facilitator_prompt,
        **_skill_kwargs(build_role_skills, all_skills_dirs, squad["facilitator"]),
    )
    _register_note_tools(triager, squad["facilitator"])
    _register_triage_validator(triager)

    # The same role consolidating the PMs' opinions. It gets no tool: it
    # cannot consult anyone, write anything, or call a PM (ADR 0013).
    synthesizer = Agent(
        model_for("facilitator"),
        deps_type=committee.SynthesisDeps,
        output_type=SynthesisDraft,
        retries={"output": _HX_OUTPUT_RETRIES},
        system_prompt=facilitator_prompt,
    )

    @synthesizer.output_validator
    def validate_synthesis(ctx: RunContext[committee.SynthesisDeps], output: SynthesisDraft) -> SynthesisDraft:
        return committee.check_synthesis(ctx.deps, output)

    hx = Agent(
        model_for("hx"),
        deps_type=KnowledgeBase,
        output_type=HXAnswer,  # no DeferredToolRequests: HX is read-only (ADR 0004, ADR 0010)
        retries={"output": _HX_OUTPUT_RETRIES},
        system_prompt=_with_context(squad.instructions_for("hx"), context, language),
        **_skill_kwargs(build_role_skills, all_skills_dirs, squad["hx"]),
    )
    _register_note_tools(hx, squad["hx"])
    _register_source_validator(hx)

    po = Agent(
        model_for("product_owner"),
        deps_type=KnowledgeBase,
        output_type=[Backlog, BriefRejection],  # the PO rejects a brief, it never asks back (ADR 0011)
        system_prompt=_with_context(squad.instructions_for("product_owner"), context, language),
        **_skill_kwargs(build_role_skills, all_skills_dirs, squad["product_owner"]),
    )
    _register_note_tools(po, squad["product_owner"])

    # Top-level, like the Product Owner, so a design-system write can pause
    # for the founder's approval (ADR 0004, ADR 0007).
    designer = Agent(
        model_for("designer"),
        deps_type=KnowledgeBase,
        output_type=[Prototype, SendBack, DeferredToolRequests],
        system_prompt=_with_context(squad.instructions_for("designer"), context, language),
        **_skill_kwargs(build_role_skills, all_skills_dirs, squad["designer"]),
    )
    _register_note_tools(designer, squad["designer"])
    design_box: list[_DesignRun | None] = [None]
    _register_prototype_validator(designer, design_box)

    _register_consult_hx(facilitator, squad["facilitator"], hx)
    _register_consult_hx(triager, squad["facilitator"], hx)
    _register_consult_hx(designer, squad["designer"], hx)

    # The PM Marketing as a query tool, like HX: a fresh run per question,
    # answering from the knowledge base only. It reads notes but does not
    # consult HX here, so a consultation is never nested two levels deep.
    marketing_role = squad["pm_marketing"]
    marketing = Agent(
        model_for("pm_marketing"),
        deps_type=KnowledgeBase,
        output_type=MarketingGuidance,
        retries={"output": _HX_OUTPUT_RETRIES},
        system_prompt=_with_context(squad.instructions_for("pm_marketing"), context, language),
        **_skill_kwargs(build_role_skills, all_skills_dirs, marketing_role),
    )
    _register_note_tools(
        marketing, marketing_role.model_copy(update={"tools": ["search_notes", "read_note"]})
    )
    _register_marketing_source_validator(marketing)

    def note_unanswered(question: str) -> None:
        run = design_box[0]
        assert run is not None  # the Designer only calls tools inside a run
        run.unanswered_marketing.append(question)

    _register_consult_pm_marketing(designer, squad["designer"], marketing, note_unanswered)

    social = Agent(
        model_for("social_media"),
        deps_type=KnowledgeBase,
        output_type=ContentPack,
        retries={"output": _HX_OUTPUT_RETRIES},
        system_prompt=_with_context(squad.instructions_for("social_media"), context, language),
        **_skill_kwargs(build_role_skills, all_skills_dirs, squad["social_media"]),
    )
    _register_note_tools(social, squad["social_media"])
    content_box: list[str | None] = [None]
    _register_content_validator(social, content_box)
    _register_consult_pm_marketing(social, squad["social_media"], marketing)

    # One agent per PM of the committee. An opinion run is isolated and may
    # overlap others; the PMs' roles declare no write tool, so it only reads
    # and consults HX.
    pms: dict[str, Agent] = {}
    for role_id in COMMITTEE_ROLES:
        role = squad[role_id]
        pm = Agent(
            model_for(role_id),
            deps_type=KnowledgeBase,
            output_type=OpinionDraft,
            retries={"output": _HX_OUTPUT_RETRIES},
            system_prompt=_with_context(squad.instructions_for(role_id), context, language),
            **_skill_kwargs(build_role_skills, all_skills_dirs, role),
        )
        _register_note_tools(pm, role)
        _register_opinion_source_validator(pm)
        _register_consult_hx(pm, role, hx)
        pms[role_id] = pm
    return _Agents(facilitator, triager, synthesizer, hx, po, designer, pms, marketing, social, design_box, content_box)


def _resolution_spans(
    deferred_tool_results: DeferredToolResults, agent: str, started_at: datetime
) -> list[Span]:
    """One zero-duration span per approval/denial resolved by a `deferred_tool_results` call.

    A tool call's own span was recorded as `awaiting_approval` on the turn
    that deferred it; extracting spans from just this turn's `new_messages()`
    never sees that original tool call again, so the resolution needs its
    own record to show up in a trace (ADR 0006).
    """
    spans = []
    for tool_call_id, resolution in (deferred_tool_results.approvals or {}).items():
        approved = resolution is True or getattr(resolution, "kind", None) == "tool-approved"
        spans.append(
            Span(
                span_id=uuid.uuid4().hex,
                agent=agent,
                operation="approval_resolution",
                tool_call_id=tool_call_id,
                started_at=started_at,
                duration_ms=0.0,
                status="ok" if approved else "error",
                detail="approved" if approved else "denied",
            )
        )
    return spans


def _design_prompt(run: _DesignRun, design_system_empty: bool) -> str:
    parts = [
        "Design every story in this backlog that has needs_design=true.",
        f"Backlog:\n{run.backlog.model_dump_json(indent=2)}",
        f"Write the prototype as one self-contained .html file under '{run.design_dir}/' "
        "and set html_path to it.",
    ]
    if design_system_empty:
        parts.append(
            "design-system/ is empty. Propose an initial design system (tokens for color, typography, "
            "spacing and radius, plus base components) grounded in what HX knows about the users, and "
            "write it under design-system/: those writes need the founder's approval. Take anything that "
            "depends on positioning, tone or brand to the PM Marketing first. What it cannot answer, and "
            "every HX gap, becomes a founder question with your suggested default."
        )
    return "\n\n".join(parts)


def _answers_prompt(prototype: Prototype, answers: dict[str, str]) -> str:
    lines = []
    for q in prototype.founder_questions:
        if q.question in answers:
            lines.append(f"- {q.question}\n  Answer: {answers[q.question]}")
        else:
            lines.append(f"- {q.question}\n  Unanswered: keep your suggested default ({q.suggested_default}).")
    return (
        "Revise your previous prototype with the founder's answers.\n"
        f"Previous prototype:\n{prototype.model_dump_json(indent=2)}\n"
        "Founder's answers:\n" + "\n".join(lines)
    )


def _content_prompt(brief: Brief, content_dir: str) -> str:
    return (
        "Write the content this approved brief calls for: the landing-page copy and the posts.\n"
        f"Brief:\n{brief.model_dump_json(indent=2)}\n\n"
        f"Write each piece as its own file under '{content_dir}/' and list it in your ContentPack with "
        "that path. Take any positioning, tone, brand or naming doubt to the PM Marketing; what it cannot "
        "answer goes in open_questions."
    )


# A model left to itself names the PMs as it would in prose ("PM de Growth"),
# and the triage is retried: the ids are spelled out for it.
_TRIAGE_ROLES = (
    "In `roles`, name each PM by its role id, exactly as written here and never by its display name: "
    + ", ".join(f"`{role_id}`" for role_id in COMMITTEE_ROLES)
    + "."
)

_CLOSE_PROMPT = (
    "The conversation is over. Close it into a Triage: the request as someone who was not here could "
    "act on it, the PMs that should give an opinion on it, and why those. Give no opinion yourself.\n"
    + _TRIAGE_ROLES
)


def _triage_prompt(request: str) -> str:
    return (
        "Triage the request below: restate it so someone with no other context could act on it, name "
        "the PMs that should give an opinion on it, and say why those. Give no opinion yourself.\n"
        f"{_TRIAGE_ROLES}\n\n"
        f"Request:\n{request}"
    )


@dataclass
class _Review:
    """The round the human is deciding on: what the PMs said, and the current synthesis of it."""

    opinions: list[Opinion]
    rebuttals: list[Opinion]
    gaps: list[KnowledgeGap]  # as HX reported them: each synthesis groups these anew
    synthesis: Synthesis
    request_span_id: str  # the round's root span: later steps of the same request hang under it
    version: int = 1


@dataclass
class _RoundTrace:
    """The span ids of a round in progress, kept while a triage waits for approval."""

    request_id: str
    triage_id: str
    triage_runs: list[Span] = field(default_factory=list)


def _step_span(operation: str, children: list[Span], span_id: str, parent_span_id: str | None) -> Span:
    """A `"squad"` span for one step of a request, as long as the spans inside it (ADR 0014)."""
    started_at = min(child.started_at for child in children)
    ended_at = max(child.started_at + timedelta(milliseconds=child.duration_ms) for child in children)
    return Span(
        span_id=span_id,
        parent_span_id=parent_span_id,
        agent="squad",
        operation=operation,
        started_at=started_at,
        duration_ms=(ended_at - started_at).total_seconds() * 1000,
        status="ok",
    )


class ProductSquad:
    """A running instance of the product squad, backed by one knowledge base.

    `context` is free text describing the product (audience, domain, current
    focus); it's appended to every agent's instructions (ADR 0003) so
    they don't have to rediscover it from the knowledge base every time.

    `chat()` talks to the Facilitator, the squad's only conversational role
    (ADR 0013). It makes the request clear and may consult HX; it gives no
    opinion and cannot call a PM.

    `close_request()` closes that conversation: the Facilitator triages it
    (which PMs to hear), those PMs each give an `Opinion` in parallel and in
    isolation, and the Facilitator consolidates them into a `Synthesis`.
    When the PMs diverge, the ones cited reply once and the synthesis is
    redone; there is never a second reply. `review(request)` does the same
    for a request given directly, with no conversation before it. The
    `Synthesis` carries the PMs' opinions whole, the gaps HX reported, and a
    proposed brief, and is written to
    `squad/committee/<cycle_id>/synthesis-<n>.md`.

    The human then decides, once. `approve()` stamps a `HumanDecision` on
    the proposed brief and returns the `Brief`, written to
    `squad/briefs/<brief_id>.md`, without calling a model. `adjust(notes)`
    redoes only the synthesis and returns to the same gate. `reject(reason)`
    ends the request with no brief. After `approve()` or `reject()` the next
    `chat()` or `review()` starts a new request, with a new `cycle_id`.

    `submit_brief()` is the Product Owner's only door (ADR 0011). It takes a
    `Brief`: problem, hypothesis, success metric, acceptance criteria, owner
    roles and an approved `HumanDecision`. A brief with a field missing, or
    without an approved decision, comes back as a `BriefRejection` naming
    those fields, without the Product Owner's model ever being called. A
    complete brief goes to the Product Owner once; it answers with a
    `Backlog`, or with a `BriefRejection` of its own when the brief is still
    too ambiguous to become stories. Nothing is revised or resubmitted
    automatically: the caller fixes the brief and submits it again.

    `chat()`, `close_request()`, `review()` and `design()` may return a
    `DeferredToolRequests` when a tool needs human approval (e.g. writing to
    a `write_with_approval` path). Resolve it with
    `DeferredToolRequests.build_results(...)` and pass the result back in as
    `deferred_tool_results` on the next call of the same method.

    `skills_dirs` adds skill-library directories on top of the library's own
    (`pydantic_squads.product.skills`); pass it to give a role access to
    project-specific skills, or omit it to skip skill support entirely
    (needs the `skills` extra only when this is not `None`). Each agent only
    ever sees the skills listed in its own `Role.skills`. See
    `pydantic_squads.product.skills_integration` and ADR 0005.

    HX is a read-only query tool: each `consult_hx` call is a fresh run with
    no memory of the previous one, so callers can overlap. `kb` is wrapped in
    a `SerializedKnowledgeBase`, so every write goes through one writer at a
    time (ADR 0010).

    `usage_limits` (a `pydantic_ai.UsageLimits`) is passed to every agent run
    in this squad; `None` (the default) keeps today's unlimited behavior.

    `trace_dir`, when set, turns on observability (ADR 0006): every call
    records spans (agent, model/tool calls, tokens, cost, status — with
    HX's nested `consult_hx` run attributed as child spans) to
    `{trace_dir}/{cycle_id}.jsonl`, one file per cycle. A stable `cycle_id`
    is generated for the whole request, from the conversation to the
    backlog, regardless of whether `trace_dir` is set, since it's also
    written into the frontmatter of the synthesis and brief notes. Inspect a
    trace with the `pydantic-squads trace <cycle_id>` CLI (`observability`
    extra), or call `resume(cycle_id)` on a fresh `ProductSquad` to reload a
    past conversation and continue it with `chat()`. A synthesis waiting at
    the gate is kept in memory only: after a restart, call
    `close_request()` again.

    `models` maps a role id to the model that role runs on, for the roles
    that should not use `model`: `models={"hx": "claude-code:haiku"}` runs
    HX on a cheaper model and everyone else on `model` (ADR 0016).

    `model` is any Pydantic AI model or model string (e.g.
    `"anthropic:claude-sonnet-4-5"`, billed to an API key), or
    `"claude-code"` / `"claude-code:<model>"` to run every agent on the
    local Claude Code CLI and its logged-in account — for your own local
    use only (`pydantic_squads.product.claude_code`, ADR 0008).

    `design()` hands an approved `Backlog` to the Designer (ADR 0007), which
    returns a `Prototype`, a `SendBack` for the founder, or a
    `DeferredToolRequests` when it wants to write to `design-system/**`. The
    Designer takes brand questions to the PM Marketing, and only what that
    cannot answer from the knowledge base reaches the founder (ADR 0012).

    `produce_content()` hands an approved `Brief` to the Social Media role,
    which writes landing-page copy and posts under
    `squad/content/<cycle_id>/` and returns a `ContentPack`.
    """

    def __init__(
        self,
        kb: KnowledgeBase,
        model: Any,
        context: str,
        language: Language = "en",
        skills_dirs: list[Path] | None = None,
        usage_limits: UsageLimits | None = None,
        trace_dir: Path | str | None = None,
        models: Mapping[str, Any] | None = None,
    ) -> None:
        # Every write, by an agent's tool or by the squad itself, goes through one writer (ADR 0010).
        self.kb: KnowledgeBase = SerializedKnowledgeBase.wrap(kb)
        self._language: Language = language
        squad = build_product_squad(language)
        models = dict(models or {})
        unknown = sorted(set(models) - {role.id for role in squad.roles})
        if unknown:
            raise ValueError(f"models names roles the squad does not have: {unknown}")
        agents = _build_agents(squad, model, models, context, language, skills_dirs)
        self._facilitator, self._triager, self._synthesizer = agents.facilitator, agents.triager, agents.synthesizer
        self._hx, self._po, self._designer = agents.hx, agents.po, agents.designer
        self._pms, self._marketing, self._social = agents.pms, agents.marketing, agents.social
        self._design_box, self._content_box = agents.design_box, agents.content_box
        self._history: list[ModelMessage] = []
        self._usage_limits = usage_limits
        self._trace_dir = Path(trace_dir) if trace_dir is not None else None
        self._cycle_id: str | None = None
        self._recorder: CycleRecorder | None = None
        self._spans: list[Span] = []  # the current cycle's spans, kept whether or not there is a trace_dir
        self._round_trace: _RoundTrace | None = None
        self._review: _Review | None = None
        # What HX answered the Facilitator in this request: the PMs start from it (ADR 0016).
        self._hx_answers: list[HXAnswer] = []
        self._request_closed = False  # set by approve()/reject(): the next chat() starts a new request
        self._pending_design: _DesignRun | None = None
        self._designer_history: list[ModelMessage] = []
        self._last_prototype: Prototype | None = None

    def chat(
        self, message: str | None = None, *, deferred_tool_results: DeferredToolResults | None = None
    ) -> str | DeferredToolRequests:
        """Send a message to the Facilitator and return its reply.

        Omit `message` when resuming a call that returned a
        `DeferredToolRequests` — pass its resolution as `deferred_tool_results`
        instead of a new message.
        """
        return self._run_facilitator(message, deferred_tool_results=deferred_tool_results)

    def close_request(
        self, *, deferred_tool_results: DeferredToolResults | None = None
    ) -> Synthesis | DeferredToolRequests:
        """Close the conversation as a request and take it to the committee.

        The Facilitator triages the conversation so far, the PMs it picks
        give their opinions, and the `Synthesis` comes back for the human to
        `approve()`, `adjust()` or `reject()`.
        """
        prompt = None if deferred_tool_results else _CLOSE_PROMPT
        return self._triage_and_review(prompt, deferred_tool_results)

    def review(
        self, request: str | None = None, *, deferred_tool_results: DeferredToolResults | None = None
    ) -> Synthesis | DeferredToolRequests:
        """Take `request` to the committee directly, with no conversation before it.

        Same as `close_request()` from the triage on. Omit `request` only
        when resuming a call that returned a `DeferredToolRequests`.
        """
        if deferred_tool_results is not None:
            return self._triage_and_review(None, deferred_tool_results)
        if request is None:
            raise ValueError("review() needs a request unless resuming a deferred triage")
        return self._triage_and_review(_triage_prompt(request), None)

    def _triage_and_review(
        self, prompt: str | None, deferred_tool_results: DeferredToolResults | None
    ) -> Synthesis | DeferredToolRequests:
        if deferred_tool_results is None or self._round_trace is None:
            self._round_trace = _RoundTrace(request_id=uuid.uuid4().hex, triage_id=uuid.uuid4().hex)
        trace = self._round_trace
        triage = self._run_facilitator(
            prompt, agent=self._triager, deferred_tool_results=deferred_tool_results, trace=trace
        )
        if isinstance(triage, DeferredToolRequests):
            return triage
        agents = {role_id: self._pms[role_id] for role_id in triage.roles}
        round_ = asyncio.run(
            committee.run_round(
                agents,
                self._synthesizer,
                self.kb,
                triage.request,
                evidence=self._hx_answers,
                usage_limits=self._usage_limits,
            )
        )

        # The trace mirrors the round: a request span, and under it one span
        # per step with that step's agent runs inside (ADR 0014).
        steps = [_step_span("triage", trace.triage_runs, trace.triage_id, trace.request_id)]

        def step(operation: str, record: Callable[[str], list[Span]]) -> None:
            step_id = uuid.uuid4().hex
            steps.append(_step_span(operation, record(step_id), step_id, trace.request_id))

        def pm_runs(runs: list[committee.OpinionRun]) -> Callable[[str], list[Span]]:
            return lambda step_id: [
                self._record_run(
                    run.opinion.role, run.messages, run.sink, run.duration_ms, "Opinion", parent_span_id=step_id
                )
                for run in runs
            ]

        def synthesis_run(run: committee.SynthesisRun) -> Callable[[str], list[Span]]:
            return lambda step_id: [
                self._record_run(
                    "facilitator", run.messages, SpanSink(), run.duration_ms, "Synthesis", parent_span_id=step_id
                )
            ]

        first, *second = round_.syntheses
        step("fan_out", pm_runs(round_.opinions))
        step("synthesis", synthesis_run(first))
        if round_.rebuttals:
            step("rebuttal", pm_runs(round_.rebuttals))
        for run in second:
            step("synthesis", synthesis_run(run))
        self._emit([_step_span("request", steps, trace.request_id, None), *steps])
        self._round_trace = None

        synthesis = round_.synthesis
        self._review = _Review(
            opinions=synthesis.opinions,
            rebuttals=synthesis.rebuttals,
            gaps=synthesis.raw_gaps,
            synthesis=synthesis,
            request_span_id=trace.request_id,
        )
        self._write_synthesis_note()
        return synthesis

    @property
    def pending_synthesis(self) -> Synthesis | None:
        """The synthesis waiting for the human's decision, or `None` when there is none."""
        return self._review.synthesis if self._review is not None else None

    def _pending_review(self, action: str) -> _Review:
        if self._review is None:
            raise ValueError(f"{action}() needs a synthesis to decide on: call close_request() or review() first")
        return self._review

    def adjust(self, notes: str) -> Synthesis:
        """Redo only the synthesis with the human's `notes`, and return to the same gate.

        No PM runs again: the new synthesis is made from the same opinions,
        which it still carries whole.
        """
        review = self._pending_review("adjust")
        if not notes.strip():
            raise ValueError("adjust() needs notes saying what to change")
        run = asyncio.run(
            committee.synthesize(
                self._synthesizer,
                review.synthesis.request,
                review.opinions,
                review.rebuttals,
                review.gaps,
                previous=SynthesisDraft(**review.synthesis.model_dump(include=set(SynthesisDraft.model_fields))),
                notes=notes,
                usage_limits=self._usage_limits,
            )
        )
        step_id = uuid.uuid4().hex
        run_span = self._record_run(
            "facilitator", run.messages, SpanSink(), run.duration_ms, "Synthesis", parent_span_id=step_id
        )
        self._emit([_step_span("adjust", [run_span], step_id, review.request_span_id)])
        review.synthesis = committee.build_synthesis(
            review.synthesis.request, run.draft, review.opinions, review.rebuttals, review.gaps
        )
        review.version += 1
        self._write_synthesis_note()
        return review.synthesis

    def approve(self, notes: str = "") -> Brief:
        """Approve the pending synthesis: its proposed brief becomes a `Brief`.

        The `HumanDecision` is stamped here, by code: no model is called.
        The brief is written to `squad/briefs/<brief_id>.md` for a person to
        read, with the same brief as data in `<brief_id>.json` next to it, and
        is what `submit_brief()` and `produce_content()` take.
        """
        review = self._pending_review("approve")
        assert self._cycle_id is not None  # a pending review always belongs to a cycle
        decision = HumanDecision(verdict="approved", notes=notes, decided_at=datetime.now(timezone.utc))
        brief = Brief(**review.synthesis.proposed_brief.model_dump(), human_decision=decision)
        record = BriefRecord(
            brief_id=uuid.uuid4().hex, cycle_id=self._cycle_id, brief=brief, created_at=decision.decided_at
        )
        self.kb.write(f"squad/briefs/{record.brief_id}.json", record.model_dump_json(indent=2))
        self.kb.write(f"squad/briefs/{record.brief_id}.md", brief_note(record, self._language))
        self._decide(decision, review, brief_id=record.brief_id)
        return brief

    def reject(self, reason: str) -> HumanDecision:
        """Reject the pending synthesis: the request ends with no brief."""
        review = self._pending_review("reject")
        decision = HumanDecision(verdict="rejected", notes=reason, decided_at=datetime.now(timezone.utc))
        self._decide(decision, review)
        return decision

    def _decide(self, decision: HumanDecision, review: _Review, *, brief_id: str | None = None) -> None:
        assert self._cycle_id is not None  # a pending review always belongs to a cycle
        note = decision_note(
            decision,
            self._cycle_id,
            f"squad/committee/{self._cycle_id}/synthesis-{review.version}.md",
            f"squad/briefs/{brief_id}.md" if brief_id is not None else None,
            self._language,
        )
        self.kb.write(f"squad/committee/{self._cycle_id}/decision.md", note)
        self._emit(
            [
                Span(
                    span_id=uuid.uuid4().hex,
                    parent_span_id=review.request_span_id,
                    agent="squad",
                    operation="human_decision",
                    started_at=decision.decided_at,
                    duration_ms=0.0,
                    status="ok" if decision.verdict == "approved" else "error",
                    detail=decision.verdict,
                )
            ]
        )
        self._review = None
        self._request_closed = True

    def _write_synthesis_note(self) -> None:
        assert self._review is not None and self._cycle_id is not None  # set by the round that just ran
        self.kb.write(
            f"squad/committee/{self._cycle_id}/synthesis-{self._review.version}.md",
            synthesis_note(self._review.synthesis, self._cycle_id, self._review.version, self._language),
        )

    def submit_brief(self, brief: Brief | BriefDraft | Mapping[str, Any]) -> Backlog | BriefRejection:
        """Hand a human-approved `Brief` to the Product Owner: its only door (ADR 0011).

        `brief` is validated first (`validate_brief`). If a field is missing
        or the human decision is not an approval, the `BriefRejection` naming
        those fields is returned and the Product Owner's model is never
        called. Otherwise the Product Owner runs once and returns a
        `Backlog`, or its own `BriefRejection` when the brief is too
        ambiguous to become stories.
        """
        checked = validate_brief(brief)
        if isinstance(checked, BriefRejection):
            self._record_invalid_brief(checked, "product_owner")
            return checked
        return self._run_po(checked.model_dump_json())

    def produce_content(self, brief: Brief | BriefDraft | Mapping[str, Any]) -> ContentPack | BriefRejection:
        """Hand a human-approved `Brief` to the Social Media role (ADR 0012).

        Like `submit_brief()`, it only works from an approved brief:
        anything else comes back as a `BriefRejection` without a model call.
        Otherwise Social Media writes each piece under
        `squad/content/<cycle_id>/`, consulting the PM Marketing on brand,
        and returns the `ContentPack` listing them. Nothing is published.
        """
        checked = validate_brief(brief)
        if isinstance(checked, BriefRejection):
            self._record_invalid_brief(checked, "social_media")
            return checked
        self._ensure_cycle()
        content_dir = f"squad/content/{self._cycle_id}"
        sink = SpanSink()
        sink_token = HX_SINK.set(sink)
        self._content_box[0] = content_dir
        started = time.monotonic()
        try:
            result = self._social.run_sync(
                _content_prompt(checked, content_dir), deps=self.kb, usage_limits=self._usage_limits
            )
        finally:
            HX_SINK.reset(sink_token)
            self._content_box[0] = None
        duration_ms = (time.monotonic() - started) * 1000
        self._record_run("social_media", result.new_messages(), sink, duration_ms, "ContentPack")
        return result.output

    def design(
        self,
        backlog: Backlog | None = None,
        *,
        answers: dict[str, str] | None = None,
        deferred_tool_results: DeferredToolResults | None = None,
    ) -> Prototype | SendBack | DeferredToolRequests | None:
        """Hand an approved `Backlog` to the Designer.

        Returns `None` without running the Designer when no story has
        `needs_design=True`: there is nothing to prototype. Otherwise returns
        the `Prototype` (its HTML is in `squad/design/<cycle_id>/`, and its
        founder questions in `questions.md` next to it), or a `SendBack` when
        a story is too ambiguous to design — returned to the founder, never
        sent to the Product Owner automatically.

        A write to `design-system/**` returns a `DeferredToolRequests`: pass
        its resolution back as `deferred_tool_results`, without `backlog`, to
        resume that same run.

        `answers` maps the previous `Prototype`'s founder questions to the
        founder's answers, for a revision round: `design(backlog,
        answers=...)`. An unanswered question keeps the Designer's suggested
        default.
        """
        if deferred_tool_results is not None:
            if self._pending_design is None:
                raise ValueError("design() got deferred_tool_results but no design run is waiting for approval")
            return self._run_designer(None, self._pending_design, deferred_tool_results=deferred_tool_results)
        if backlog is None:
            raise ValueError("design() needs a Backlog unless resuming a deferred design run")
        if answers is not None:
            if self._last_prototype is None:
                raise ValueError("design(answers=...) needs a previous Prototype to revise")
            asked = {q.question for q in self._last_prototype.founder_questions}
            unknown = sorted(set(answers) - asked)
            if unknown:
                raise ValueError(f"answers to questions the Designer did not ask: {unknown}")
        if not any(story.needs_design for story in backlog.stories):
            return None

        self._ensure_cycle()
        run = _DesignRun(backlog=backlog, design_dir=f"squad/design/{self._cycle_id}")
        prompt = _design_prompt(run, design_system_empty=self._design_system_empty())
        if answers is not None:
            assert self._last_prototype is not None  # checked above
            prompt += "\n\n" + _answers_prompt(self._last_prototype, answers)
            # A brand question the founder left open is still one the PM
            # Marketing could not answer: the revision may carry it over.
            run.unanswered_marketing.extend(
                q.marketing_question for q in self._last_prototype.founder_questions if q.marketing_question
            )
        return self._run_designer(prompt, run)

    def _design_system_empty(self) -> bool:
        return not any(note.path.startswith("design-system/") for note in self.kb.search("design-system/"))

    def _run_designer(
        self, prompt: str | None, run: _DesignRun, *, deferred_tool_results: DeferredToolResults | None = None
    ) -> Prototype | SendBack | DeferredToolRequests:
        assert self._cycle_id is not None  # design() ensured the cycle before building `run`
        sink = SpanSink()
        sink_token = HX_SINK.set(sink)
        self._design_box[0] = run
        started = time.monotonic()
        try:
            result = self._designer.run_sync(
                prompt,
                deps=self.kb,
                message_history=self._designer_history if deferred_tool_results is not None else [],
                deferred_tool_results=deferred_tool_results,
                usage_limits=self._usage_limits,
            )
        finally:
            HX_SINK.reset(sink_token)
            self._design_box[0] = None
        duration_ms = (time.monotonic() - started) * 1000
        self._record_run(
            "designer",
            result.new_messages(),
            sink,
            duration_ms,
            type(result.output).__name__,
            deferred_tool_results=deferred_tool_results,
        )
        output = result.output
        if isinstance(output, DeferredToolRequests):
            # Kept in memory only: after a restart, call design() again (ADR 0007).
            self._pending_design = run
            self._designer_history = result.all_messages()
            return output
        self._pending_design = None
        self._designer_history = []
        if isinstance(output, Prototype):
            self._last_prototype = output
            self.kb.write(f"{run.design_dir}/questions.md", founder_questions_note(output, self._cycle_id, self._language))
        return output

    @property
    def cycle_id(self) -> str | None:
        """The current cycle's id, or `None` until the first call starts a cycle.

        It names the cycle's trace file (`{trace_dir}/<cycle_id>.jsonl`), is
        what `resume()` takes, and is in the frontmatter of the cycle's
        synthesis and brief notes (ADR 0006, ADR 0013).
        """
        return self._cycle_id

    def resume(self, cycle_id: str) -> None:
        """Reload a past cycle's conversation from `trace_dir` and continue with `chat()`.

        Needs `trace_dir` to have been set on `__init__`. Restores the
        conversation, the `cycle_id` and the cycle's spans (so `gantt()`
        shows the whole cycle) — it never calls the model.
        """
        if self._trace_dir is None:
            raise ValueError("resume() needs trace_dir to be set")
        _header, spans, snapshot = load_cycle(self._trace_dir, cycle_id)
        self._history = deserialize_history(snapshot.message_history_json)
        self._spans = list(spans)
        self._cycle_id = cycle_id
        self._recorder = CycleRecorder(self._trace_dir, cycle_id)

    @property
    def spans(self) -> list[Span]:
        """The current cycle's spans so far, whether or not there is a `trace_dir`."""
        return list(self._spans)

    def gantt(self, **kwargs: Any) -> TerminalGantt:
        """A Gantt chart of the current cycle, from memory: no `trace_dir` needed.

        Each role's runs are on its own rows, so the PMs' opinions show as
        overlapping bars under the request's `fan_out` step. `kwargs` go to
        `TerminalGantt` (`width`, `use_colors`, `collapse_gaps_ms`). Call
        `.print()` or `.render()` on the result.
        """
        return TerminalGantt.from_records((span.model_dump(mode="json") for span in self._spans), **kwargs)

    def _emit(self, spans: list[Span]) -> None:
        """Add `spans` to the current cycle: in memory always, and to the trace file when there is one."""
        self._spans.extend(spans)
        if self._recorder is not None:
            self._recorder.record_spans(spans)
            self._recorder.record_snapshot(serialize_history(self._history))

    def _ensure_cycle(self) -> None:
        if self._cycle_id is None:
            self._cycle_id = uuid.uuid4().hex
        if self._trace_dir is not None and self._recorder is None:
            self._recorder = CycleRecorder(self._trace_dir, self._cycle_id)
            self._recorder.start()

    def _run_facilitator(
        self,
        prompt: str | None,
        *,
        agent: Agent | None = None,
        deferred_tool_results: DeferredToolResults | None = None,
        trace: _RoundTrace | None = None,
    ) -> Any:
        """One turn of the Facilitator's conversation, on `agent` (the conversational one by default).

        With `trace`, the run is a triage: its span goes under the round's
        `triage` step.
        """
        if self._request_closed and deferred_tool_results is None:
            # The last request was decided: this message starts a new one.
            self._history = []
            self._spans = []
            self._hx_answers = []
            self._cycle_id = None
            self._recorder = None
            self._request_closed = False
        self._ensure_cycle()
        sink = SpanSink()
        sink_token = HX_SINK.set(sink)
        started = time.monotonic()
        try:
            result = (agent or self._facilitator).run_sync(
                prompt,
                deps=self.kb,
                message_history=self._history,
                deferred_tool_results=deferred_tool_results,
                usage_limits=self._usage_limits,
            )
        finally:
            HX_SINK.reset(sink_token)
        duration_ms = (time.monotonic() - started) * 1000
        new_messages = result.new_messages()
        self._history = result.all_messages()
        self._hx_answers.extend(sink.hx_answers)
        run_span = self._record_run(
            "facilitator",
            new_messages,
            sink,
            duration_ms,
            type(result.output).__name__,
            deferred_tool_results=deferred_tool_results,
            parent_span_id=trace.triage_id if trace is not None else None,
        )
        if trace is not None:
            trace.triage_runs.append(run_span)
        return result.output

    def _run_po(self, prompt: str) -> Any:
        self._ensure_cycle()
        started = time.monotonic()
        result = self._po.run_sync(prompt, deps=self.kb, usage_limits=self._usage_limits)
        duration_ms = (time.monotonic() - started) * 1000
        self._record_run(
            "product_owner", result.new_messages(), SpanSink(), duration_ms, type(result.output).__name__
        )
        return result.output

    def _record_run(
        self,
        agent: str,
        messages: list[ModelMessage],
        sink: SpanSink,
        wall_clock_ms: float,
        output_type_name: str,
        *,
        deferred_tool_results: DeferredToolResults | None = None,
        parent_span_id: str | None = None,
    ) -> Span:
        """Add one agent run's spans to the cycle and return the run's own span."""
        # `messages` is this call's own `new_messages()`, not the cumulative
        # history — extracting from the full history every call would
        # re-record every prior turn's spans again on each new call.
        started_at = messages[0].timestamp if messages else datetime.now(timezone.utc)
        inner_spans = merge_nested_spans(extract_spans(messages, agent=agent, output_type=output_type_name), sink)
        if deferred_tool_results is not None:
            inner_spans = [*_resolution_spans(deferred_tool_results, agent, started_at), *inner_spans]
        run_span_id = uuid.uuid4().hex
        run_span = Span(
            span_id=run_span_id,
            parent_span_id=parent_span_id,
            agent=agent,
            operation="agent_run",
            started_at=started_at,
            duration_ms=wall_clock_ms,
            status="ok",
        )
        nested = [
            span.model_copy(update={"parent_span_id": run_span_id}) if span.parent_span_id is None else span
            for span in inner_spans
        ]
        self._emit([run_span, *nested])
        return run_span

    def _record_invalid_brief(self, rejection: BriefRejection, agent: str) -> None:
        # No model ran, so there are no messages to extract spans from: the
        # rejection gets a span of its own, or the trace would not show it.
        self._ensure_cycle()
        self._emit(
            [
                Span(
                    span_id=uuid.uuid4().hex,
                    agent=agent,
                    operation="brief_validation",
                    started_at=datetime.now(timezone.utc),
                    duration_ms=0.0,
                    status="error",
                    detail=rejection.reason,
                    output_type="BriefRejection",
                )
            ]
        )
