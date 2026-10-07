"""Assemble the product squad into runnable Pydantic AI agents.

Needs the optional `ai` extra (`pydantic-ai-slim`). The rest of
`pydantic_squads.product` stays dependency-free (ADR 0001); nothing else in
this package imports this module, so it works without `pydantic_ai` installed.
"""

import fnmatch
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
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
from pydantic_squads.product.claude_code import resolve_model
from pydantic_squads.product.contracts import (
    Backlog,
    Bet,
    BetRecord,
    HXAnswer,
    Prototype,
    Revision,
    SendBack,
    Span,
    design_coverage_errors,
)
from pydantic_squads.product.knowledge import KnowledgeBase, Note, format_note
from pydantic_squads.product.observability import (
    CycleRecorder,
    SpanSink,
    deserialize_history,
    extract_spans,
    load_cycle,
    merge_nested_spans,
    serialize_history,
)
from pydantic_squads.product.squad import Language, build_product_squad


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


def _search_notes(role: Role, kb: KnowledgeBase, query: str) -> list[Note]:
    return [n for n in kb.search(query) if _path_allowed(n.path, role.permissions.read)]


def _list_by_tag(role: Role, kb: KnowledgeBase, tag: str) -> list[Note]:
    return [n for n in kb.list_by_tag(tag) if _path_allowed(n.path, role.permissions.read)]


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


def _register_note_tools(agent: Agent[KnowledgeBase, Any], role: Role) -> None:
    """Register only the note tools listed in `role.tools`, scoped to `role.permissions`."""

    if "search_notes" in role.tools:

        @agent.tool(retries=_NOTE_TOOL_RETRIES)
        def search_notes(ctx: RunContext[KnowledgeBase], query: str) -> list[Note]:
            """Search the knowledge base by keywords; notes matching more of them come first."""
            return _search_notes(role, ctx.deps, query)

    if "list_by_tag" in role.tools:

        @agent.tool(retries=_NOTE_TOOL_RETRIES)
        def list_by_tag(ctx: RunContext[KnowledgeBase], tag: str) -> list[Note]:
            """List notes carrying `tag`."""
            return _list_by_tag(role, ctx.deps, tag)

    if "read_note" in role.tools:

        @agent.tool(retries=_NOTE_TOOL_RETRIES)
        def read_note(ctx: RunContext[KnowledgeBase], path: str) -> Note:
            """Read a single note by its vault-relative path, including folder and `.md`
            (e.g. `docs/x.md`), as returned by search_notes. Obsidian `[[wikilinks]]` also work."""
            return _read_note(role, ctx.deps, path)

    if "write_note" in role.tools:

        @agent.tool(retries=_NOTE_TOOL_RETRIES)
        def write_note(ctx: RunContext[KnowledgeBase], path: str, content: str) -> str:
            """Write a note by its path. Some paths require human approval first."""
            return _write_note(role, ctx.deps, path, content, approved=ctx.tool_call_approved)


def _sources_exist(kb: KnowledgeBase, output: HXAnswer) -> HXAnswer:
    for finding in output.findings:
        for source in finding.sources:
            try:
                kb.read(source)
            except (OSError, ValueError):
                raise ModelRetry(f"source '{source}' does not exist in the knowledge base") from None
    return output


def _register_source_validator(agent: Agent[KnowledgeBase, HXAnswer]) -> None:
    @agent.output_validator
    def validate_sources(ctx: RunContext[KnowledgeBase], output: HXAnswer) -> HXAnswer:
        return _sources_exist(ctx.deps, output)


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
    result = await hx_agent.run(question, deps=kb, usage=usage)
    # `sink` (ADR 0006) is how the outer run's span extraction later finds
    # HX's own spans: they never appear in the Growth PM's `all_messages()`.
    if sink is not None and tool_call_id is not None:
        sink.nested_runs[tool_call_id] = ("hx", result.all_messages())
    return result.output


def _register_consult_hx(
    caller_agent: Agent[KnowledgeBase, Any],
    caller_role: Role,
    hx_agent: Agent[KnowledgeBase, Any],
    sink_box: list[SpanSink | None],
) -> None:
    if "consult_hx" not in caller_role.tools:
        return

    @caller_agent.tool
    async def consult_hx(ctx: RunContext[KnowledgeBase], question: str) -> HXAnswer:
        """Ask HX a question about users; returns cited findings, each classified as evidence, assumption or gap."""
        return await _consult_hx(
            hx_agent, ctx.deps, ctx.usage, question, tool_call_id=ctx.tool_call_id, sink=sink_box[0]
        )


@dataclass(frozen=True)
class _DesignRun:
    """What the Designer's output validator checks a `Prototype` against."""

    backlog: Backlog
    design_dir: str  # squad/design/<cycle_id>, where the prototype must be written


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
    return prototype


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


def _build_agents(
    squad: Squad, model: Any, context: str, language: Language, skills_dirs: list[Path] | None
) -> tuple[Agent, Agent, Agent, Agent, list[SpanSink | None], list[_DesignRun | None]]:
    # Imported lazily and only when skills are actually requested, so the `ai`
    # extra alone (skills_dirs=None, the default) never needs the `skills`
    # extra installed.
    build_role_skills: Any = None
    all_skills_dirs: list[Path] | None = None
    if skills_dirs is not None:
        from pydantic_squads.product.skills_integration import LIBRARY_SKILLS_DIR, build_role_skills

        all_skills_dirs = [LIBRARY_SKILLS_DIR, *skills_dirs]

    # "claude-code" / "claude-code:<model>" runs on the local Claude Code login (ADR 0008).
    model = resolve_model(model)

    growth_pm = Agent(
        model,
        deps_type=KnowledgeBase,
        output_type=[str, DeferredToolRequests],
        system_prompt=_with_context(squad.instructions_for("growth_pm"), context, language),
        **_skill_kwargs(build_role_skills, all_skills_dirs, squad["growth_pm"]),
    )
    _register_note_tools(growth_pm, squad["growth_pm"])

    hx = Agent(
        model,
        deps_type=KnowledgeBase,
        output_type=HXAnswer,  # no DeferredToolRequests: HX cannot request write approval (ADR 0004)
        system_prompt=_with_context(squad.instructions_for("hx"), context, language),
        **_skill_kwargs(build_role_skills, all_skills_dirs, squad["hx"]),
    )
    _register_note_tools(hx, squad["hx"])
    _register_source_validator(hx)

    po = Agent(
        model,
        deps_type=KnowledgeBase,
        output_type=[Backlog, SendBack],
        system_prompt=_with_context(squad.instructions_for("product_owner"), context, language),
        **_skill_kwargs(build_role_skills, all_skills_dirs, squad["product_owner"]),
    )
    _register_note_tools(po, squad["product_owner"])

    # Top-level, like the Product Owner, so a design-system write can pause
    # for the founder's approval (ADR 0004, ADR 0007).
    designer = Agent(
        model,
        deps_type=KnowledgeBase,
        output_type=[Prototype, SendBack, DeferredToolRequests],
        system_prompt=_with_context(squad.instructions_for("designer"), context, language),
        **_skill_kwargs(build_role_skills, all_skills_dirs, squad["designer"]),
    )
    _register_note_tools(designer, squad["designer"])
    design_box: list[_DesignRun | None] = [None]
    _register_prototype_validator(designer, design_box)

    sink_box: list[SpanSink | None] = [None]
    _register_consult_hx(growth_pm, squad["growth_pm"], hx, sink_box)
    _register_consult_hx(designer, squad["designer"], hx, sink_box)
    return growth_pm, hx, po, designer, sink_box, design_box


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
            "write it under design-system/: those writes need the founder's approval. Anything that "
            "depends on positioning, tone, brand or an HX gap becomes a founder question with your "
            "suggested default."
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


def _founder_questions_note(prototype: Prototype, cycle_id: str) -> str:
    """The `questions.md` note: every open founder question, for the founder to answer."""
    if not prototype.founder_questions:
        body = "No open questions."
    else:
        sections = []
        for q in prototype.founder_questions:
            section = f"## {q.question}\n\n{q.context}\n\n- Origin: {q.origin}\n"
            if q.hx_question is not None:
                section += f"- Asked HX: {q.hx_question}\n"
            section += f"- Suggested default: {q.suggested_default}\n- Answer:"
            sections.append(section)
        body = "\n\n".join(sections)
    frontmatter: dict[str, str | list[str]] = {
        "cycle_id": cycle_id,
        "schema_version": "1",
        "prototype": prototype.html_path,
    }
    return format_note(frontmatter, f"# Questions for the founder\n\n{body}\n")


def _send_back_prompt(send_back: SendBack) -> str:
    questions = "\n".join(f"- {q}" for q in send_back.questions)
    return (
        "The Product Owner sent the current bet back.\n"
        f"Reason: {send_back.reason}\n"
        f"Questions:\n{questions}\n"
        "Revise the bet to answer these questions."
    )


class ProductSquad:
    """A running instance of the product squad, backed by one knowledge base.

    `context` is free text describing the product (audience, domain, current
    focus); it's appended to all three agents' instructions (ADR 0003) so
    they don't have to rediscover it from the knowledge base every time.

    `chat()` talks to the Growth PM. `close_bet()` asks it to turn the
    conversation so far into a `Bet`, for the founder to review outside this
    class; only a `Bet` the founder actually approved should be passed to
    `submit_bet()`.

    `submit_bet()` hands the bet to the Product Owner exactly once. If the
    Product Owner sends it back, the Growth PM revises it and `submit_bet()`
    returns a `Revision` (the new `Bet` plus the `SendBack` that prompted
    it) instead of resubmitting — a send-back never reaches the Product
    Owner without a human seeing why and approving the revision first. The
    founder reviews `revision.send_back` and `revision.bet`, then calls
    `submit_bet(revision.bet)` to actually resubmit it.

    Any call may return a `DeferredToolRequests` when a tool needs human
    approval (e.g. writing to a `write_with_approval` path). Resolve it with
    `DeferredToolRequests.build_results(...)` and pass the result back in as
    `deferred_tool_results` on the next call of the same method.

    `skills_dirs` adds skill-library directories on top of the library's own
    (`pydantic_squads.product.skills`); pass it to give a role access to
    project-specific skills, or omit it to skip skill support entirely
    (needs the `skills` extra only when this is not `None`). Each agent only
    ever sees the skills listed in its own `Role.skills`. See
    `pydantic_squads.product.skills_integration` and ADR 0005.

    `usage_limits` (a `pydantic_ai.UsageLimits`) is passed to every agent run
    in this squad; `None` (the default) keeps today's unlimited behavior.

    `trace_dir`, when set, turns on observability (ADR 0006): every call
    records spans (agent, model/tool calls, tokens, cost, status — with
    HX's nested `consult_hx` run attributed as child spans) to
    `{trace_dir}/{cycle_id}.jsonl`, one file per cycle. A stable `cycle_id`
    is generated for the whole conversation→Bet→Backlog arc regardless of
    whether `trace_dir` is set, since it's also written into the frontmatter
    of every Bet note (see below). Inspect a trace with the
    `pydantic-squads trace <cycle_id>` CLI (`observability` extra), or call
    `resume(cycle_id)` on a fresh `ProductSquad` to reload a past
    conversation and continue it with `chat()`.

    `close_bet()` and a `submit_bet()` revision both write the closed `Bet`
    to `squad/bets/<bet_version_id>.md` in the knowledge base,
    deterministically (not left to the Growth PM to remember via
    `write_note`), with `cycle_id`, `schema_version` and `bet_version_id` —
    plus `previous_bet_version_id` on a revision — in its frontmatter.

    `model` is any Pydantic AI model or model string (e.g.
    `"anthropic:claude-sonnet-4-5"`, billed to an API key), or
    `"claude-code"` / `"claude-code:<model>"` to run every agent on the
    local Claude Code CLI and its logged-in account — for your own local
    use only (`pydantic_squads.product.claude_code`, ADR 0008).

    `design()` hands an approved `Backlog` to the Designer (ADR 0007), which
    returns a `Prototype`, a `SendBack` for the founder, or a
    `DeferredToolRequests` when it wants to write to `design-system/**`.
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
    ) -> None:
        self.kb = kb
        squad = build_product_squad(language)
        self._growth_pm, self._hx, self._po, self._designer, self._sink_box, self._design_box = _build_agents(
            squad, model, context, language, skills_dirs
        )
        self._history: list[ModelMessage] = []
        self._pending_send_back: SendBack | None = None
        self._usage_limits = usage_limits
        self._trace_dir = Path(trace_dir) if trace_dir is not None else None
        self._cycle_id: str | None = None
        self._recorder: CycleRecorder | None = None
        self._last_bet_version_id: str | None = None
        self._pending_design: _DesignRun | None = None
        self._designer_history: list[ModelMessage] = []
        self._last_prototype: Prototype | None = None

    def chat(
        self, message: str | None = None, *, deferred_tool_results: DeferredToolResults | None = None
    ) -> str | DeferredToolRequests:
        """Send a message to the Growth PM and return its reply.

        Omit `message` when resuming a call that returned a
        `DeferredToolRequests` — pass its resolution as `deferred_tool_results`
        instead of a new message.
        """
        return self._run_pm(message, deferred_tool_results=deferred_tool_results)

    def close_bet(
        self, *, deferred_tool_results: DeferredToolResults | None = None
    ) -> Bet | DeferredToolRequests:
        """Ask the Growth PM to close the conversation so far into a `Bet`."""
        prompt = None if deferred_tool_results else "Close the current discussion into a Bet."
        output = self._run_pm(
            prompt, output_type=[Bet, DeferredToolRequests], deferred_tool_results=deferred_tool_results
        )
        if isinstance(output, Bet):
            self._write_bet_record(output)
        return output

    def submit_bet(
        self, bet: Bet | None = None, *, deferred_tool_results: DeferredToolResults | None = None
    ) -> Backlog | Revision | DeferredToolRequests:
        """Hand a founder-approved `Bet` to the Product Owner, once.

        Returns the `Backlog` on acceptance. On a `SendBack`, asks the
        Growth PM to revise the bet and returns a `Revision` (the new `Bet`
        plus the `SendBack` that prompted it) — it is never resubmitted
        automatically. Call `submit_bet(revision.bet)` once the founder has
        seen `revision.send_back` and approved the revision, to actually
        send it to the Product Owner.

        Omit `bet` only when resuming a previous call whose bet-revision
        step returned a `DeferredToolRequests`; pass its resolution as
        `deferred_tool_results`. That resumes the Growth PM's revision, not
        the Product Owner — a pending send-back is never sent to the
        Product Owner as a side effect of resolving an approval.
        """
        if self._pending_send_back is not None and deferred_tool_results is not None:
            return self._revise_bet(self._pending_send_back, deferred_tool_results=deferred_tool_results)
        if bet is None:
            raise ValueError("submit_bet() needs a Bet unless resuming a deferred bet revision")

        self._pending_send_back = None
        output = self._run_po(bet.model_dump_json())
        if isinstance(output, Backlog):
            return output
        return self._revise_bet(output)

    def _revise_bet(
        self, send_back: SendBack, *, deferred_tool_results: DeferredToolResults | None = None
    ) -> Revision | DeferredToolRequests:
        pm_prompt = None if deferred_tool_results else _send_back_prompt(send_back)
        output = self._run_pm(
            pm_prompt, output_type=[Bet, DeferredToolRequests], deferred_tool_results=deferred_tool_results
        )
        if isinstance(output, DeferredToolRequests):
            self._pending_send_back = send_back
            return output
        self._pending_send_back = None
        self._write_bet_record(output)
        return Revision(bet=output, send_back=send_back)

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
        return self._run_designer(prompt, run)

    def _design_system_empty(self) -> bool:
        return not any(note.path.startswith("design-system/") for note in self.kb.search("design-system/"))

    def _run_designer(
        self, prompt: str | None, run: _DesignRun, *, deferred_tool_results: DeferredToolResults | None = None
    ) -> Prototype | SendBack | DeferredToolRequests:
        assert self._cycle_id is not None  # design() ensured the cycle before building `run`
        sink = SpanSink()
        self._sink_box[0] = sink
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
            self._sink_box[0] = None
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
            self.kb.write(f"{run.design_dir}/questions.md", _founder_questions_note(output, self._cycle_id))
        return output

    @property
    def cycle_id(self) -> str | None:
        """The current cycle's id, or `None` until the first call starts a cycle.

        It names the cycle's trace file (`{trace_dir}/<cycle_id>.jsonl`), is
        what `resume()` takes, and is in the frontmatter of the cycle's Bet
        notes (ADR 0006).
        """
        return self._cycle_id

    def resume(self, cycle_id: str) -> None:
        """Reload a past cycle's conversation from `trace_dir` and continue with `chat()`.

        Needs `trace_dir` to have been set on `__init__`. Restores
        `message_history` and `cycle_id` only — it never calls the model.
        """
        if self._trace_dir is None:
            raise ValueError("resume() needs trace_dir to be set")
        _header, _spans, snapshot = load_cycle(self._trace_dir, cycle_id)
        self._history = deserialize_history(snapshot.message_history_json)
        self._cycle_id = cycle_id
        self._recorder = CycleRecorder(self._trace_dir, cycle_id)

    def _ensure_cycle(self) -> None:
        if self._cycle_id is None:
            self._cycle_id = uuid.uuid4().hex
        if self._trace_dir is not None and self._recorder is None:
            self._recorder = CycleRecorder(self._trace_dir, self._cycle_id)
            self._recorder.start()

    def _run_pm(
        self,
        prompt: str | None,
        *,
        output_type: Any = None,
        deferred_tool_results: DeferredToolResults | None = None,
    ) -> Any:
        self._ensure_cycle()
        sink = SpanSink()
        self._sink_box[0] = sink
        started = time.monotonic()
        kwargs: dict[str, Any] = dict(
            deps=self.kb,
            message_history=self._history,
            deferred_tool_results=deferred_tool_results,
            usage_limits=self._usage_limits,
        )
        if output_type is not None:
            kwargs["output_type"] = output_type
        try:
            result = self._growth_pm.run_sync(prompt, **kwargs)
        finally:
            self._sink_box[0] = None
        duration_ms = (time.monotonic() - started) * 1000
        new_messages = result.new_messages()
        self._history = result.all_messages()
        self._record_run(
            "growth_pm",
            new_messages,
            sink,
            duration_ms,
            type(result.output).__name__,
            deferred_tool_results=deferred_tool_results,
        )
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
    ) -> None:
        # `messages` is this call's own `new_messages()`, not the cumulative
        # history — extracting from the full history every call would
        # re-record every prior turn's spans again on each new call.
        if self._recorder is None:
            return
        started_at = messages[0].timestamp if messages else datetime.now(timezone.utc)
        inner_spans = merge_nested_spans(extract_spans(messages, agent=agent, output_type=output_type_name), sink)
        if deferred_tool_results is not None:
            inner_spans = [*_resolution_spans(deferred_tool_results, agent, started_at), *inner_spans]
        run_span_id = uuid.uuid4().hex
        run_span = Span(
            span_id=run_span_id,
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
        self._recorder.record_spans([run_span, *nested])
        self._recorder.record_snapshot(serialize_history(self._history))

    def _write_bet_record(self, bet: Bet) -> None:
        assert self._cycle_id is not None  # _ensure_cycle() always runs before this
        bet_version_id = uuid.uuid4().hex
        record = BetRecord(
            bet_version_id=bet_version_id,
            previous_bet_version_id=self._last_bet_version_id,
            cycle_id=self._cycle_id,
            bet=bet,
            created_at=datetime.now(timezone.utc),
        )
        frontmatter: dict[str, str | list[str]] = {
            "cycle_id": record.cycle_id,
            "schema_version": str(record.schema_version),
            "bet_version_id": record.bet_version_id,
        }
        if record.previous_bet_version_id is not None:
            frontmatter["previous_bet_version_id"] = record.previous_bet_version_id
        content = format_note(frontmatter, record.bet.model_dump_json(indent=2))
        self.kb.write(f"squad/bets/{bet_version_id}.md", content)
        self._last_bet_version_id = bet_version_id
