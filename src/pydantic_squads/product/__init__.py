"""Ready-made product squad: Growth PM, HX researcher, Product Owner.

Consuming projects supply only a `KnowledgeBase` (ADR 0003); roles and
contracts are fixed.
"""

from pydantic_squads.product.contracts import (
    Backlog,
    Bet,
    BetRecord,
    CycleHeader,
    CycleSnapshot,
    Finding,
    FindingKind,
    HXAnswer,
    POOutput,
    Revision,
    SendBack,
    Span,
    SpanStatus,
    Story,
)
from pydantic_squads.product.knowledge import KnowledgeBase, MarkdownKnowledgeBase, Note, format_note
from pydantic_squads.product.roles import GROWTH_PM, HX, PRODUCT_OWNER
from pydantic_squads.product.squad import Language, build_product_squad

__all__ = [
    "GROWTH_PM",
    "HX",
    "PRODUCT_OWNER",
    "Backlog",
    "Bet",
    "BetRecord",
    "CycleHeader",
    "CycleSnapshot",
    "Finding",
    "FindingKind",
    "HXAnswer",
    "KnowledgeBase",
    "Language",
    "MarkdownKnowledgeBase",
    "Note",
    "POOutput",
    "Revision",
    "SendBack",
    "Span",
    "SpanStatus",
    "Story",
    "build_product_squad",
    "format_note",
]
