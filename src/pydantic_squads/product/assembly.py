"""Assemble the product squad into runnable Pydantic AI agents.

Needs the optional `ai` extra (`pydantic-ai`). The rest of
`pydantic_squads.product` stays dependency-free (ADR 0001); nothing else in
this package imports this module, so it works without `pydantic_ai` installed.
"""

import fnmatch
from pathlib import PurePosixPath
from typing import Any

from pydantic_ai import (
    Agent,
    ApprovalRequired,
    DeferredToolRequests,
    DeferredToolResults,
    ModelRetry,
    RunContext,
)
from pydantic_ai.messages import ModelMessage

from pydantic_squads import Role, Squad
from pydantic_squads.product.contracts import Backlog, Bet, HXAnswer, SendBack
from pydantic_squads.product.knowledge import KnowledgeBase, Note
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
    if normalized is None or not _matches(normalized, role.permissions.read):
        raise ModelRetry(f"not permitted to read '{path}'")
    return kb.read(normalized)


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


def _register_note_tools(agent: Agent[KnowledgeBase, Any], role: Role) -> None:
    """Register search/read/list_by_tag/write tools scoped to `role.permissions`."""

    @agent.tool
    def search_notes(ctx: RunContext[KnowledgeBase], query: str) -> list[Note]:
        """Search the knowledge base for notes matching `query`."""
        return _search_notes(role, ctx.deps, query)

    @agent.tool
    def list_by_tag(ctx: RunContext[KnowledgeBase], tag: str) -> list[Note]:
        """List notes carrying `tag`."""
        return _list_by_tag(role, ctx.deps, tag)

    @agent.tool
    def read_note(ctx: RunContext[KnowledgeBase], path: str) -> Note:
        """Read a single note by its path."""
        return _read_note(role, ctx.deps, path)

    @agent.tool
    def write_note(ctx: RunContext[KnowledgeBase], path: str, content: str) -> str:
        """Write a note by its path. Some paths require human approval first."""
        return _write_note(role, ctx.deps, path, content, approved=ctx.tool_call_approved)


def _sources_exist(kb: KnowledgeBase, output: HXAnswer | DeferredToolRequests) -> HXAnswer | DeferredToolRequests:
    if isinstance(output, DeferredToolRequests):
        return output
    for finding in output.findings:
        for source in finding.sources:
            try:
                kb.read(source)
            except (FileNotFoundError, OSError, ValueError):
                raise ModelRetry(f"source '{source}' does not exist in the knowledge base") from None
    return output


def _register_source_validator(agent: Agent[KnowledgeBase, Any]) -> None:
    @agent.output_validator
    def validate_sources(ctx: RunContext[KnowledgeBase], output: HXAnswer | DeferredToolRequests):
        return _sources_exist(ctx.deps, output)


async def _consult_hx(hx_agent: Agent[KnowledgeBase, Any], kb: KnowledgeBase, usage: Any, question: str) -> HXAnswer:
    # Nested calls must use `run`, not `run_sync`: pydantic_ai forbids a nested
    # sync run inside a tool, since it could deadlock the outer run's event loop.
    result = await hx_agent.run(question, deps=kb, usage=usage)
    if isinstance(result.output, DeferredToolRequests):
        raise ModelRetry(
            "HX needs a human's direct approval to update an assumption; ask the founder to consult HX directly"
        )
    return result.output


def _register_consult_hx(pm_agent: Agent[KnowledgeBase, Any], hx_agent: Agent[KnowledgeBase, Any]) -> None:
    @pm_agent.tool
    async def consult_hx(ctx: RunContext[KnowledgeBase], question: str) -> HXAnswer:
        """Ask HX a question about users; returns cited findings, each classified as evidence, assumption or gap."""
        return await _consult_hx(hx_agent, ctx.deps, ctx.usage, question)


def _build_agents(squad: Squad, model: Any) -> tuple[Agent, Agent, Agent]:
    growth_pm = Agent(
        model,
        deps_type=KnowledgeBase,
        output_type=[str, DeferredToolRequests],
        system_prompt=squad.instructions_for("growth_pm"),
    )
    _register_note_tools(growth_pm, squad["growth_pm"])

    hx = Agent(
        model,
        deps_type=KnowledgeBase,
        output_type=[HXAnswer, DeferredToolRequests],
        system_prompt=squad.instructions_for("hx"),
    )
    _register_note_tools(hx, squad["hx"])
    _register_source_validator(hx)

    po = Agent(
        model,
        deps_type=KnowledgeBase,
        output_type=[Backlog, SendBack],
        system_prompt=squad.instructions_for("product_owner"),
    )
    _register_note_tools(po, squad["product_owner"])

    _register_consult_hx(growth_pm, hx)
    return growth_pm, hx, po


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

    `chat()` talks to the Growth PM. `close_bet()` asks it to turn the
    conversation so far into a `Bet`, for the founder to review outside this
    class; only a `Bet` the founder actually approved should be passed to
    `submit_bet()`. `submit_bet()` hands it to the Product Owner and relays a
    `SendBack` back to the Growth PM to revise, up to `max_send_backs` times.

    Any call may return a `DeferredToolRequests` when a tool needs human
    approval (e.g. writing to a `write_with_approval` path). Resolve it with
    `DeferredToolRequests.build_results(...)` and pass the result back in as
    `deferred_tool_results` on the next call of the same method.
    """

    def __init__(
        self,
        kb: KnowledgeBase,
        model: Any,
        language: Language = "en",
        max_send_backs: int = 3,
    ) -> None:
        self.kb = kb
        self.max_send_backs = max_send_backs
        squad = build_product_squad(language)
        self._growth_pm, self._hx, self._po = _build_agents(squad, model)
        self._history: list[ModelMessage] = []

    def chat(
        self, message: str | None = None, *, deferred_tool_results: DeferredToolResults | None = None
    ) -> str | DeferredToolRequests:
        """Send a message to the Growth PM and return its reply.

        Omit `message` when resuming a call that returned a
        `DeferredToolRequests` — pass its resolution as `deferred_tool_results`
        instead of a new message.
        """
        result = self._growth_pm.run_sync(
            message,
            deps=self.kb,
            message_history=self._history,
            deferred_tool_results=deferred_tool_results,
        )
        self._history = result.all_messages()
        return result.output

    def close_bet(
        self, *, deferred_tool_results: DeferredToolResults | None = None
    ) -> Bet | DeferredToolRequests:
        """Ask the Growth PM to close the conversation so far into a `Bet`."""
        prompt = None if deferred_tool_results else "Close the current discussion into a Bet."
        result = self._growth_pm.run_sync(
            prompt,
            deps=self.kb,
            message_history=self._history,
            output_type=[Bet, DeferredToolRequests],
            deferred_tool_results=deferred_tool_results,
        )
        self._history = result.all_messages()
        return result.output

    def submit_bet(
        self, bet: Bet, *, deferred_tool_results: DeferredToolResults | None = None
    ) -> Backlog | SendBack | DeferredToolRequests:
        """Hand a founder-approved `Bet` to the Product Owner.

        A `SendBack` is relayed to the Growth PM to revise the bet, up to
        `max_send_backs` times; whatever the last attempt produces is
        returned.
        """
        current = bet
        for attempt in range(self.max_send_backs + 1):
            po_result = self._po.run_sync(current.model_dump_json(), deps=self.kb)
            output = po_result.output
            if isinstance(output, Backlog) or attempt == self.max_send_backs:
                return output
            pm_prompt = None if deferred_tool_results else _send_back_prompt(output)
            pm_result = self._growth_pm.run_sync(
                pm_prompt,
                deps=self.kb,
                message_history=self._history,
                output_type=[Bet, DeferredToolRequests],
                deferred_tool_results=deferred_tool_results,
            )
            deferred_tool_results = None
            self._history = pm_result.all_messages()
            if isinstance(pm_result.output, DeferredToolRequests):
                return pm_result.output
            current = pm_result.output
