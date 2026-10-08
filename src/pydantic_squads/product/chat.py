"""The product squad as a terminal session: the `pydantic-squads chat` command (ADR 0017).

Needs the `ai` extra (it runs a `ProductSquad`) and the `observability`
extra (`rich`, to render it). `pydantic_squads.cli` imports this module
lazily, so the CLI itself needs neither.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolDenied
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from pydantic_squads.cli import report_from_spans
from pydantic_squads.product.assembly import ProductSquad
from pydantic_squads.product.contracts import (
    Backlog,
    Brief,
    BriefRejection,
    ContentPack,
    Prototype,
    SendBack,
    Synthesis,
)

HELP = """\
| Command | What it does |
|---|---|
| *(any text)* | Talk to the Facilitator until the request is clear |
| `/close` | Close the conversation and take the request to the committee of PMs |
| `/review TEXT` | Take TEXT to the committee directly, with no conversation |
| `/approve [NOTES]` | Approve the synthesis: its proposed brief becomes the Brief |
| `/adjust NOTES` | Redo the synthesis only, with your notes |
| `/reject REASON` | End the request with no Brief |
| `/submit` | Hand the approved Brief to the Product Owner |
| `/content` | Have Social Media write the content of the approved Brief |
| `/design` | Hand the Backlog to the Designer |
| `/gantt` | Draw the current cycle, followed by its cost |
| `/cost` | Only the cost: model, calls, tokens and estimated USD per agent |
| `/resume CYCLE_ID` | Continue the conversation of an earlier cycle |
| `/help` | Show this table |
| `/quit` | Leave, showing the cost |
"""


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) or "- none"


def synthesis_markdown(synthesis: Synthesis) -> str:
    """A `Synthesis` as the human reads it at the gate."""
    brief = synthesis.proposed_brief
    divergences = "\n\n".join(
        f"**{d.topic}**\n" + "\n".join(f"- _{role}_: {position}" for role, position in d.positions.items())
        for d in synthesis.divergences
    )
    gaps = "\n".join(f"- {g.gap} _(asked by {', '.join(g.asked_by)})_" for g in synthesis.gaps)
    opinions = "\n\n".join(
        f"**{o.role}**{label} _({o.confidence} confidence)_: {o.recommendation}"
        for label, group in (("", synthesis.opinions), (" (reply)", synthesis.rebuttals))
        for o in group
    )
    return "\n\n".join(
        [
            synthesis.summary,
            f"### Divergences\n\n{divergences or 'None.'}",
            f"### What we don't know\n\n{gaps or 'HX reported no gap.'}",
            f"### Questions for you\n\n{_bullets(synthesis.questions_for_human)}",
            f"### Opinions\n\n{opinions}",
            "### Proposed brief\n\n"
            f"**Problem:** {brief.problem}\n\n"
            f"**Hypothesis:** {brief.hypothesis}\n\n"
            f"**Success metric:** {brief.success_metric}\n\n"
            f"**Acceptance criteria**\n{_bullets(brief.acceptance_criteria)}\n\n"
            f"**Owner roles:** {', '.join(brief.owner_roles)}",
        ]
    )


class ChatSession:
    """One terminal session with a product squad.

    `make_squad` builds the squad, and builds a fresh one for `/resume`.
    `ask` reads a line from the human (`console.input` by default); a test
    passes its own. The session only remembers what the next command needs:
    the approved `Brief` and the `Backlog`.
    """

    def __init__(
        self,
        make_squad: Callable[[], ProductSquad],
        *,
        console: Console | None = None,
        ask: Callable[[str], str] | None = None,
    ) -> None:
        self.make_squad = make_squad
        self.squad = make_squad()
        self.console = console or Console()
        self.ask = ask or self.console.input
        self.brief: Brief | None = None
        self.backlog: Backlog | None = None
        self._commands: dict[str, Callable[[str], None]] = {
            "/close": self._close,
            "/review": self._review,
            "/approve": self._approve,
            "/adjust": self._adjust,
            "/reject": self._reject,
            "/submit": self._submit,
            "/content": self._content,
            "/design": self._design,
            "/gantt": self._gantt,
            "/cost": self._cost,
            "/resume": self._resume,
            "/help": lambda _rest: self.console.print(Markdown(HELP)),
        }

    def run(self) -> None:
        """Read lines until `/quit` or the end of input, then show the cost."""
        self.console.print(Panel(Markdown(HELP), title="pydantic-squads chat"))
        while True:
            try:
                line = self.ask("\n> ")
            except (EOFError, KeyboardInterrupt):
                break
            if not self.handle(line):
                break
        self._cost("")
        if self.squad.cycle_id is not None:
            self.console.print(f"Cycle: {self.squad.cycle_id}")

    def handle(self, line: str) -> bool:
        """Run one line of input. Returns `False` when the session should end."""
        command, _, rest = line.strip().partition(" ")
        if command == "/quit":
            return False
        try:
            if command in self._commands:
                self._commands[command](rest.strip())
            elif command.startswith("/"):
                self.console.print(f"Unknown command {command}. See /help.")
            elif command:
                reply = self._resolve(self.squad.chat, line)
                self.console.print(Panel(Markdown(reply), title="Facilitator"))
        except ValueError as error:  # a command out of order, such as /approve with nothing to approve
            self.console.print(f"Cannot do that now: {error}")
        except Exception as error:  # a model or network failure must not end the session
            self.console.print(f"Error: {type(error).__name__}: {error}")
        return True

    def _resolve(self, call: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Call `call`; while it asks to write somewhere that needs approval, ask the human and resume."""
        result = call(*args, **kwargs)
        while isinstance(result, DeferredToolRequests):
            approvals: dict[str, bool | ToolDenied] = {}
            for request in result.approvals:
                arguments = request.args_as_dict()
                body = str(arguments.get("content", json.dumps(arguments, ensure_ascii=False, indent=2)))
                self.console.print(Panel(body, title=f"Approval needed: {request.tool_name} {arguments.get('path', '')}"))
                if self.ask("Approve? [y/N] ").strip().lower() in ("y", "yes"):
                    approvals[request.tool_call_id] = True
                else:
                    reason = self.ask("Reason (optional): ").strip()
                    approvals[request.tool_call_id] = ToolDenied(reason or "The human denied this write.")
            result = call(deferred_tool_results=DeferredToolResults(approvals=approvals))
        return result

    def _show_synthesis(self, synthesis: Synthesis) -> None:
        self.console.print(Panel(Markdown(synthesis_markdown(synthesis)), title="Synthesis"))
        self.console.print(f"Full note, with each opinion's risks and sources: squad/committee/{self.squad.cycle_id}/")
        self.console.print("Decide: /approve [NOTES], /adjust NOTES or /reject REASON.", markup=False)

    def _close(self, _rest: str) -> None:
        self._show_synthesis(self._resolve(self.squad.close_request))

    def _review(self, request: str) -> None:
        if not request:
            self.console.print("Usage: /review TEXT")
            return
        self._show_synthesis(self._resolve(self.squad.review, request))

    def _adjust(self, notes: str) -> None:
        self._show_synthesis(self.squad.adjust(notes))

    def _approve(self, notes: str) -> None:
        self.brief, self.backlog = self.squad.approve(notes), None
        self.console.print("Approved. The brief is in squad/briefs/. Next: /submit or /content.")

    def _reject(self, reason: str) -> None:
        self.squad.reject(reason)
        self.console.print("Rejected. No brief was created; your next message starts a new request.")

    def _approved_brief(self) -> Brief | None:
        if self.brief is None:
            self.console.print("There is no approved brief yet: /close (or /review), then /approve.")
        return self.brief

    def _submit(self, _rest: str) -> None:
        if (brief := self._approved_brief()) is None:
            return
        outcome = self.squad.submit_brief(brief)
        if isinstance(outcome, BriefRejection):
            body = f"**Reason:** {outcome.reason}\n\n**Fields to fix**\n{_bullets(outcome.missing_fields)}"
            self.console.print(Panel(Markdown(body), title="Brief rejected by the Product Owner"))
            return
        self.backlog = outcome
        stories = "\n\n".join(
            f"**{story.title}** _({'needs design' if story.needs_design else 'no design'})_\n"
            + _bullets(story.acceptance_criteria)
            for story in outcome.stories
        )
        self.console.print(Panel(Markdown(stories), title="Backlog"))
        self.console.print("Next: /design.")

    def _content(self, _rest: str) -> None:
        if (brief := self._approved_brief()) is None:
            return
        pack = self.squad.produce_content(brief)
        assert isinstance(pack, ContentPack)  # the brief was approved by this session, so it validates
        pieces = "\n".join(f"- **{p.title}** ({p.kind}, {p.channel}): `{p.path}`" for p in pack.pieces)
        questions = f"\n\n**Open questions**\n{_bullets(pack.open_questions)}" if pack.open_questions else ""
        self.console.print(Panel(Markdown(pieces + questions), title="Content"))

    def _design(self, _rest: str) -> None:
        if self.backlog is None:
            self.console.print("There is no backlog yet: /submit first.")
            return
        result = self._resolve(self.squad.design, self.backlog)
        while True:
            if result is None:
                self.console.print("No story in the backlog needs design.")
                return
            if isinstance(result, SendBack):
                body = f"**Reason:** {result.reason}\n\n**Questions**\n{_bullets(result.questions)}"
                self.console.print(Panel(Markdown(body), title="Sent back by the Designer"))
                return
            answers = self._show_prototype(result)
            if not answers:
                return
            result = self._resolve(self.squad.design, self.backlog, answers=answers)

    def _show_prototype(self, prototype: Prototype) -> dict[str, str]:
        """Show the prototype and collect the human's answers to its questions (none keeps the defaults)."""
        screens = "\n".join(f"- **{s.name}**: {s.purpose}" for s in prototype.screens)
        self.console.print(Panel(Markdown(f"**File:** `{prototype.html_path}`\n\n{screens}"), title="Prototype"))
        answers: dict[str, str] = {}
        for number, question in enumerate(prototype.founder_questions, 1):
            self.console.print(f"{number}. {question.question}\n   {question.context}", markup=False)
            answer = self.ask(f"   Answer (Enter keeps: {question.suggested_default}): ").strip()
            if answer:
                answers[question.question] = answer
        return answers

    def _gantt(self, _rest: str) -> None:
        self.console.print(Text.from_ansi(self.squad.gantt(collapse_gaps_ms=2000).render()))
        self._cost("")

    def _cost(self, _rest: str) -> None:
        spans = self.squad.spans
        if not spans:
            self.console.print("Nothing has run yet.")
            return
        metrics = sorted(report_from_spans(str(self.squad.cycle_id), spans).agent_metrics, key=lambda m: -m.cost_usd)
        table = Table(title="Cost of the current cycle")
        for column in ("Agent", "Model", "Calls", "Retried", "Input tokens", "Output tokens", "USD"):
            table.add_column(column, justify="left" if column in ("Agent", "Model") else "right")
        for m in metrics:
            table.add_row(
                m.agent,
                ", ".join(m.models) or "-",
                str(m.calls),
                str(m.retried),
                f"{m.input_tokens:,}",
                f"{m.output_tokens:,}",
                f"{m.cost_usd:.2f}",
            )
        table.add_row(
            "total",
            "",
            str(sum(m.calls for m in metrics)),
            str(sum(m.retried for m in metrics)),
            f"{sum(m.input_tokens for m in metrics):,}",
            f"{sum(m.output_tokens for m in metrics):,}",
            f"{sum(m.cost_usd for m in metrics):.2f}",
        )
        self.console.print(table)
        self.console.print("USD is an estimate at API list prices. On a Claude Code login it is not what you pay.")

    def _resume(self, cycle_id: str) -> None:
        if not cycle_id:
            self.console.print("Usage: /resume CYCLE_ID")
            return
        squad = self.make_squad()
        try:
            squad.resume(cycle_id)
        except FileNotFoundError:
            self.console.print(f"No trace found for cycle {cycle_id}.")
            return
        self.squad, self.brief, self.backlog = squad, None, None
        self.console.print(
            f"Conversation of cycle {cycle_id} resumed. A pending synthesis, the brief and the backlog "
            "are not restored: /close again if you need them."
        )
