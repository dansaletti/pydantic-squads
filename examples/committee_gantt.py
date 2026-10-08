"""Prints the Gantt chart of one committee round, run on a fake model (no LLM, no API key).

    uv run --extra ai python examples/committee_gantt.py

The fake plays every agent and sleeps a little on each call, so the bars are
wide enough to read: the three PMs' opinions overlap under `fan_out`, the two
PMs that disagree reply once under `rebuttal`, and the Facilitator's two
syntheses bracket that reply.
"""

import asyncio
import os
import tempfile

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from pydantic_squads.product import MarkdownKnowledgeBase
from pydantic_squads.product.assembly import ProductSquad

BRIEF = {
    "problem": "Dispatch managers do not know route sharing exists",
    "hypothesis": "A fake-door landing page shows whether they want it",
    "success_metric": "waitlist signups",
    "acceptance_criteria": ["The page has one call to action"],
    "owner_roles": ["growth_pm", "pm_marketing"],
}
DIVERGENCE = {"topic": "How long to run it", "positions": {"growth_pm": "Two weeks", "pm_product": "A month"}}


async def fake_model(messages, info):
    """Answer as whichever agent is asking, told apart by the output it must produce."""
    await asyncio.sleep(0.05)
    schemas = {tool.parameters_json_schema.get("title"): tool.name for tool in info.output_tools}

    def output(title: str, arguments: dict) -> ModelResponse:
        return ModelResponse(parts=[ToolCallPart(schemas[title], arguments)])

    if "HXAnswer" in schemas:
        gap = {"claim": "Nobody asked dispatch managers about sharing", "kind": "gap"}
        return output("HXAnswer", {"question": "q", "summary": "No interview covers it", "findings": [gap]})
    if "Triage" in schemas:
        roles = ["growth_pm", "pm_product", "pm_marketing"]
        return output("Triage", {"request": "A fake-door landing page", "roles": roles, "rationale": "All three"})
    if "SynthesisDraft" in schemas:
        after_replies = "Replies after the first synthesis" in str(messages[0].parts[-1].content)
        divergences = [] if after_replies else [DIVERGENCE]
        return output("SynthesisDraft", {"summary": "Run it", "divergences": divergences, "proposed_brief": BRIEF})
    if len(messages) == 1 and "This is your one reply" not in str(messages[0].parts[-1].content):
        return ModelResponse(parts=[ToolCallPart("consult_hx", {"question": "Do they share routes today?"})])
    return output("OpinionDraft", {"recommendation": "Run it", "confidence": "medium"})


def main() -> None:
    with tempfile.TemporaryDirectory() as vault:
        squad = ProductSquad(MarkdownKnowledgeBase(vault), model=FunctionModel(fake_model), context="A demo product")
        squad.review("A fake-door landing page for route sharing")
        squad.approve("Go ahead")
        squad.gantt(width=120).print()


if __name__ == "__main__":
    main()
