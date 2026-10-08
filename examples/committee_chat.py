"""Talk to the product squad in a terminal: the conversation, the committee, and the human gate.

    uv run --extra ai python examples/committee_chat.py PATH/TO/VAULT \\
        --context "B2B tool for small logistics companies" --model claude-code:sonnet

This calls a real model. By default it runs on your local Claude Code
login (install Claude Code, run `claude`, then `/login`) and uses your
plan's limits; pass `--model` with any Pydantic AI model string to use an
API key instead.

With no model option it uses the library's recommended Claude Code setup
(`RECOMMENDED_MODEL` and `RECOMMENDED_ROLE_MODELS`): the PMs on Sonnet with
extended thinking, HX on Haiku and everyone else on Sonnet.

To change it: `--pm-model` sets the three PMs, `--hx-model` sets HX, and
`--role-model ROLE=MODEL` any role. `--model` sets every role not named,
and drops the recommended setup: only what you pass then applies. A Claude
Code model can carry a reasoning effort after a second colon (`low` to
`max`), as in `claude-code:sonnet:high`.

Type a message to talk to the Facilitator. Commands:

    /close            close the conversation and take it to the committee
    /review TEXT      take TEXT to the committee directly, with no conversation
    /approve [NOTES]  approve the synthesis: its proposed brief becomes a Brief
    /adjust NOTES     redo the synthesis only, with NOTES
    /reject REASON    end the request with no brief
    /submit           hand the approved Brief to the Product Owner
    /content          have Social Media write content from the approved Brief
    /design           hand the Backlog to the Designer
    /gantt            draw the current cycle, followed by its cost
    /cost             only the cost: model, tokens and estimated USD per agent (needs --trace-dir)
    /quit             leave, printing the cost

A write that needs your approval stops and asks you, one write at a time.
"""

import argparse
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic_ai import DeferredToolRequests, UsageLimits

from pydantic_squads.product import (
    COMMITTEE_ROLES,
    Backlog,
    Brief,
    BriefRejection,
    ContentPack,
    MarkdownKnowledgeBase,
    Prototype,
    SendBack,
    Synthesis,
)
from pydantic_squads.cli import build_report
from pydantic_squads.product.assembly import ProductSquad
from pydantic_squads.product.claude_code import RECOMMENDED_MODEL, RECOMMENDED_ROLE_MODELS

Ask = Callable[[str], str]


def show_synthesis(synthesis: Synthesis, note_path: str) -> None:
    print(f"\n=== Synthesis ===\n{synthesis.summary}")
    print("\nDivergences:" if synthesis.divergences else "\nDivergences: none")
    for divergence in synthesis.divergences:
        print(f"  {divergence.topic}")
        for role, position in divergence.positions.items():
            print(f"    {role}: {position}")
    print("\nWhat we don't know:" if synthesis.gaps else "\nWhat we don't know: HX reported no gap")
    for gap in synthesis.gaps:
        print(f"  {gap.gap}\n    asked HX: {'; '.join(gap.questions)} (by {', '.join(gap.asked_by)})")
    if synthesis.questions_for_human:
        print("\nQuestions for you:")
        for question in synthesis.questions_for_human:
            print(f"  - {question}")
    print("\nOpinions:")
    for label, opinions in (("", synthesis.opinions), (" (reply)", synthesis.rebuttals)):
        for opinion in opinions:
            print(f"  {opinion.role}{label}, {opinion.confidence} confidence: {opinion.recommendation}")
            for source in opinion.sources:
                print(f"    source: {source}")
    brief = synthesis.proposed_brief
    print(f"\nProposed brief:\n  Problem: {brief.problem}\n  Hypothesis: {brief.hypothesis}")
    print(f"  Success metric: {brief.success_metric}\n  Owner roles: {', '.join(brief.owner_roles)}")
    for criterion in brief.acceptance_criteria:
        print(f"  Acceptance criterion: {criterion}")
    print(f"\nFull note: {note_path}\nDecide: /approve [notes], /adjust notes, or /reject reason")


def resolve(call: Callable[..., Any], first: Any, ask: Ask) -> Any:
    """Ask the human about each write waiting for approval, until the call returns something else."""
    result = first
    while isinstance(result, DeferredToolRequests):
        approvals = {}
        for request in result.approvals:
            print(f"\nApproval needed: {request.tool_name} {request.args}")
            approvals[request.tool_call_id] = ask("Approve this write? [y/N] ").strip().lower() == "y"
        result = call(deferred_tool_results=result.build_results(approvals=approvals))
    return result


def show_cost(cycle_id: str | None, trace_dir: Path | None) -> None:
    """Tokens and estimated cost of a cycle, per agent, read from its trace file."""
    if trace_dir is None:
        print("Cost is read from the trace: start with --trace-dir to have it.")
        return
    if cycle_id is None or not (trace_dir / f"{cycle_id}.jsonl").exists():
        print("Nothing has run yet.")
        return
    metrics = sorted(build_report(cycle_id, trace_dir).agent_metrics, key=lambda m: -m.cost_usd)
    print(f"\n=== Cost of cycle {cycle_id} ===")
    row = "{:<14} {:<10} {:>5} {:>7} {:>13} {:>14} {:>7}"
    print(row.format("agent", "model", "calls", "retried", "input tokens", "output tokens", "USD"))
    for m in metrics:
        models = ", ".join(m.models) or "-"
        print(row.format(m.agent, models, m.calls, m.retried, f"{m.input_tokens:,}", f"{m.output_tokens:,}", f"{m.cost_usd:.2f}"))
    total = (
        sum(m.calls for m in metrics),
        sum(m.retried for m in metrics),
        f"{sum(m.input_tokens for m in metrics):,}",
        f"{sum(m.output_tokens for m in metrics):,}",
        f"{sum(m.cost_usd for m in metrics):.2f}",
    )
    print(row.format("total", "", *total))
    print("USD is an estimate at API list prices. On a Claude Code login it is not what you are charged.")


class Session:
    """What the terminal remembers between commands: the brief and backlog the next step needs."""

    def __init__(self, squad: ProductSquad, ask: Ask = input, trace_dir: Path | None = None) -> None:
        self.squad = squad
        self.ask = ask
        self.trace_dir = trace_dir
        self.brief: Brief | None = None
        self.backlog: Backlog | None = None

    def _show_round(self, result: Any) -> None:
        if isinstance(result, Synthesis):
            show_synthesis(result, f"squad/committee/{self.squad.cycle_id}/")

    def handle(self, line: str) -> bool:
        """Run one line of input. Returns False when the session should end."""
        command, _, rest = line.strip().partition(" ")
        rest = rest.strip()
        squad = self.squad
        try:
            if command == "/quit":
                return False
            if command == "/cost":
                show_cost(squad.cycle_id, self.trace_dir)
                return True
            if command == "/close":
                self._show_round(resolve(squad.close_request, squad.close_request(), self.ask))
            elif command == "/review":
                if not rest:
                    print("Usage: /review TEXT")
                else:
                    self._show_round(resolve(squad.review, squad.review(rest), self.ask))
            elif command == "/adjust":
                self._show_round(squad.adjust(rest))
            elif command == "/approve":
                self.brief, self.backlog = squad.approve(rest), None
                print(f"Approved. The brief is in squad/briefs/. Next: /submit, /content (cycle {squad.cycle_id})")
            elif command == "/reject":
                squad.reject(rest)
                print("Rejected. No brief was created.")
            elif command == "/submit":
                self._submit()
            elif command == "/content":
                self._content()
            elif command == "/design":
                self._design()
            elif command == "/gantt":
                squad.gantt(collapse_gaps_ms=2000).print()
                show_cost(squad.cycle_id, self.trace_dir)
            elif command.startswith("/"):
                print(f"Unknown command {command}. See the top of this file for the list.")
            elif line.strip():
                print(f"\n{resolve(squad.chat, squad.chat(line), self.ask)}")
        except ValueError as error:  # a command used out of order, e.g. /approve with nothing to approve
            print(f"Cannot do that now: {error}")
        return True

    def _approved_brief(self) -> Brief | None:
        if self.brief is None:
            print("There is no approved brief yet: /close (or /review), then /approve.")
        return self.brief

    def _submit(self) -> None:
        if (brief := self._approved_brief()) is None:
            return
        outcome = self.squad.submit_brief(brief)
        if isinstance(outcome, BriefRejection):
            print(f"The Product Owner rejected the brief: {outcome.reason}\n  Fix: {outcome.missing_fields}")
            return
        self.backlog = outcome
        print("\n=== Backlog ===")
        for story in outcome.stories:
            print(f"  {story.title}{' (needs design)' if story.needs_design else ''}")
            for criterion in story.acceptance_criteria:
                print(f"    - {criterion}")
        print("Next: /design")

    def _content(self) -> None:
        if (brief := self._approved_brief()) is None:
            return
        pack = self.squad.produce_content(brief)
        if isinstance(pack, ContentPack):
            for piece in pack.pieces:
                print(f"  {piece.kind} for {piece.channel}: {piece.path}")
            for question in pack.open_questions:
                print(f"  open question: {question}")

    def _design(self) -> None:
        if self.backlog is None:
            print("There is no backlog yet: /submit first.")
            return
        backlog = self.backlog
        result = resolve(self.squad.design, self.squad.design(backlog), self.ask)
        if result is None:
            print("No story needs design.")
        elif isinstance(result, SendBack):
            print(f"The Designer sent the backlog back: {result.reason}\n  {result.questions}")
        elif isinstance(result, Prototype):
            print(f"Prototype: {result.html_path}")
            for question in result.founder_questions:
                print(f"  question for you ({question.origin}): {question.question}")


def role_models(
    pm_model: str | None, hx_model: str | None, pairs: list[str], base: dict[str, str] | None = None
) -> dict[str, str]:
    """The role -> model map: `base`, then the shorthands, then each `ROLE=MODEL` pair, the last one winning."""
    models: dict[str, str] = dict(base or {})
    if pm_model:
        models.update(dict.fromkeys(COMMITTEE_ROLES, pm_model))
    if hx_model:
        models["hx"] = hx_model
    for pair in pairs:
        role_id, _, model = pair.partition("=")
        models[role_id.strip()] = model.strip()
    return models


def main() -> None:
    parser = argparse.ArgumentParser(description="Talk to the product squad in a terminal.")
    parser.add_argument("vault", type=Path, help="a folder of markdown notes: the knowledge base")
    parser.add_argument("--context", default="", help="what the product is, or a path to a file saying so")
    parser.add_argument(
        "--model", default=None, help="model for every role not named; omit for the recommended Claude Code setup"
    )
    parser.add_argument("--pm-model", default=None, help="model for the three PMs")
    parser.add_argument("--hx-model", default=None, help="model for HX")
    parser.add_argument(
        "--role-model", action="append", default=[], metavar="ROLE=MODEL", help="model for one role; repeatable"
    )
    parser.add_argument("--language", default="en", choices=["en", "pt-BR"])
    parser.add_argument("--trace-dir", type=Path, default=None, help="record each cycle's trace here")
    parser.add_argument("--request-limit", type=int, default=None, help="model requests allowed per agent run")
    args = parser.parse_args()

    context = Path(args.context).read_text() if args.context and Path(args.context).is_file() else args.context
    # No --model: the recommended setup, which the other model options can still adjust.
    recommended = RECOMMENDED_ROLE_MODELS if args.model is None else None
    models = role_models(args.pm_model, args.hx_model, args.role_model, recommended)
    model = args.model or RECOMMENDED_MODEL
    squad = ProductSquad(
        MarkdownKnowledgeBase(args.vault),
        model=model,
        models=models,
        context=context or "No product context was given.",
        language=args.language,
        trace_dir=args.trace_dir,
        usage_limits=UsageLimits(request_limit=args.request_limit) if args.request_limit else None,
    )
    session = Session(squad, trace_dir=args.trace_dir)
    print(f"Models: {model} for every role, except:" if models else f"Model: {model} for every role.")
    for role_id, role_model in models.items():
        print(f"  {role_id}: {role_model}")
    print("Talk to the Facilitator. /close takes the request to the committee; /quit leaves.")
    while True:
        try:
            line = input("\n> ")
        except (EOFError, KeyboardInterrupt):
            break
        if not session.handle(line):
            break
    if args.trace_dir is not None:
        show_cost(squad.cycle_id, args.trace_dir)


if __name__ == "__main__":
    main()
