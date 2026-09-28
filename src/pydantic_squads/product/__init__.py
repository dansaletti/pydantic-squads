"""Ready-made product squad: Growth PM, HX researcher, Product Owner.

Consuming projects supply only a `KnowledgeBase` (ADR 0003); roles and
contracts are fixed.
"""

from pydantic_squads.product.contracts import (
    Backlog,
    Bet,
    Finding,
    FindingKind,
    HXAnswer,
    POOutput,
    Revision,
    SendBack,
    Story,
)
from pydantic_squads.product.knowledge import KnowledgeBase, MarkdownKnowledgeBase, Note
from pydantic_squads.product.roles import GROWTH_PM, HX, PRODUCT_OWNER
from pydantic_squads.product.squad import Language, build_product_squad

__all__ = [
    "GROWTH_PM",
    "HX",
    "PRODUCT_OWNER",
    "Backlog",
    "Bet",
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
    "Story",
    "build_product_squad",
]
