"""Assembles the ready-made product squad in a chosen language."""

from typing import Literal

from pydantic_squads import EN, PT_BR, PromptTemplate, Squad
from pydantic_squads.product.roles import GROWTH_PM, HX, PRODUCT_OWNER

Language = Literal["en", "pt-BR"]

_TEMPLATES: dict[Language, PromptTemplate] = {"en": EN, "pt-BR": PT_BR}
_DIRECTIVES: dict[Language, str] = {
    "en": "Always answer in English.",
    "pt-BR": "Sempre responda em português.",
}


def build_product_squad(language: Language = "en") -> Squad:
    """Build the product squad (Growth PM, HX, Product Owner) in `language`.

    Role content stays in English; `language` only selects the instruction
    labels and adds a directive so the agent answers in that language.
    """
    directive = _DIRECTIVES[language]
    roles = [
        role.model_copy(update={"principles": [*role.principles, directive]})
        for role in (GROWTH_PM, HX, PRODUCT_OWNER)
    ]
    return Squad(name="Product", roles=roles, template=_TEMPLATES[language])
