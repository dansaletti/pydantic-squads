"""Assembles the ready-made product squad in a chosen language."""

from collections.abc import Sequence
from typing import Literal

from pydantic_squads import EN, PT_BR, PromptTemplate, Role, Squad
from pydantic_squads.policies import DEFAULT_POLICIES, Policy
from pydantic_squads.product.roles import (
    DESIGNER,
    FACILITATOR,
    GROWTH_PM,
    HX,
    PM_MARKETING,
    PM_PRODUCT,
    PRODUCT_OWNER,
    SOCIAL_MEDIA,
)

Language = Literal["en", "pt-BR"]

COMMITTEE_ROLES: tuple[str, ...] = ("growth_pm", "pm_product", "pm_marketing")
"""The PMs that give an `Opinion` on a request, each from its own point of view."""

_TEMPLATES: dict[Language, PromptTemplate] = {"en": EN, "pt-BR": PT_BR}
_DIRECTIVES: dict[Language, str] = {
    "en": "Always answer in English.",
    "pt-BR": "Sempre responda em português.",
}


def product_owner_has_one_door(roles: Sequence[Role]) -> None:
    """Only the Facilitator hands work to the Product Owner (ADR 0011, ADR 0013)."""
    for role in roles:
        if role.id != FACILITATOR.id and PRODUCT_OWNER.id in role.talks_to:
            raise ValueError(f"{role.id} must not talk to the Product Owner: only the Facilitator does")


PRODUCT_POLICIES: tuple[Policy, ...] = (*DEFAULT_POLICIES, product_owner_has_one_door)
"""The default policies plus the product squad's own (ADR 0002)."""


def build_product_squad(language: Language = "en") -> Squad:
    """Build the product squad in `language`.

    Its roles: Facilitator, Growth PM, Product PM, Marketing PM, HX, Product
    Owner, Designer and Social Media. The Facilitator is the only
    conversational one.

    Role content stays in English; `language` only selects the instruction
    labels and adds a directive so the agent answers in that language.
    """
    directive = _DIRECTIVES[language]
    roles = [
        role.model_copy(update={"principles": [*role.principles, directive]})
        for role in (FACILITATOR, GROWTH_PM, PM_PRODUCT, PM_MARKETING, HX, PRODUCT_OWNER, DESIGNER, SOCIAL_MEDIA)
    ]
    return Squad(name="Product", roles=roles, policies=PRODUCT_POLICIES, template=_TEMPLATES[language])
