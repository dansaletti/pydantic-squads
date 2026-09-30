"""Ready-made product squad: Growth PM, HX researcher, Product Owner, Designer.

Consuming projects supply only a `KnowledgeBase` (ADR 0003); roles and
contracts are fixed.
"""

from pydantic_squads.product.contracts import (
    Backlog,
    Bet,
    BetRecord,
    ComponentProposal,
    CycleHeader,
    CycleSnapshot,
    DesignerOutput,
    Finding,
    FindingKind,
    FounderQuestion,
    HXAnswer,
    POOutput,
    Prototype,
    Revision,
    Screen,
    SendBack,
    Span,
    SpanStatus,
    Story,
    design_coverage_errors,
)
from pydantic_squads.product.knowledge import KnowledgeBase, MarkdownKnowledgeBase, Note, format_note
from pydantic_squads.product.roles import DESIGNER, GROWTH_PM, HX, PRODUCT_OWNER
from pydantic_squads.product.squad import Language, build_product_squad

__all__ = [
    "DESIGNER",
    "GROWTH_PM",
    "HX",
    "PRODUCT_OWNER",
    "Backlog",
    "Bet",
    "BetRecord",
    "ComponentProposal",
    "CycleHeader",
    "CycleSnapshot",
    "DesignerOutput",
    "Finding",
    "FindingKind",
    "FounderQuestion",
    "HXAnswer",
    "KnowledgeBase",
    "Language",
    "MarkdownKnowledgeBase",
    "Note",
    "POOutput",
    "Prototype",
    "Revision",
    "Screen",
    "SendBack",
    "Span",
    "SpanStatus",
    "Story",
    "build_product_squad",
    "design_coverage_errors",
    "format_note",
]
