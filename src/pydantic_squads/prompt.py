"""Section labels used when rendering a Role into instructions.

Roles are usually written in the language the agents should speak, so the
surrounding labels must match. Ship your own PromptTemplate for other languages.
"""

from pydantic import BaseModel, ConfigDict


class PromptTemplate(BaseModel):
    model_config = ConfigDict(frozen=True)

    intro: str
    intro_in_squad: str
    mission: str
    responsibilities: str
    out_of_scope: str
    principles: str
    delivers: str


EN = PromptTemplate(
    intro="You are the {role}.",
    intro_in_squad="You are the {role} of the {squad} squad.",
    mission="Mission",
    responsibilities="Responsibilities",
    out_of_scope="Out of scope (do not do this)",
    principles="Principles",
    delivers="What you deliver",
)

PT_BR = PromptTemplate(
    intro="Você é o {role}.",
    intro_in_squad="Você é o {role} da squad {squad}.",
    mission="Missão",
    responsibilities="Responsabilidades",
    out_of_scope="Fora do seu escopo (não faça)",
    principles="Princípios",
    delivers="O que você entrega",
)
