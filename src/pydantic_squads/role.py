"""Declarative definition of a squad role.

A Role describes WHO an agent is: mission, boundaries, who it talks to and what
it may do. It has no dependency on pydantic_ai or on any LLM, so roles can be
validated and tested without an API key.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from pydantic_squads.prompt import EN, PromptTemplate

HUMAN = "human"
"""Reserved id for the human in the loop. Use it in `Role.talks_to`."""


class InteractionMode(str, Enum):
    CONVERSATIONAL = "conversational"  # multi-turn conversation with the human
    DELEGATE = "delegate"  # called by another agent as a tool
    TASK = "task"  # receives a contract, delivers a contract


class Permissions(BaseModel):
    """Glob patterns relative to the knowledge base root.

    There is deliberately no delete permission.
    """

    model_config = ConfigDict(frozen=True)

    read: list[str] = Field(default_factory=lambda: ["**"])
    write: list[str] = Field(default_factory=list)
    write_with_approval: list[str] = Field(default_factory=list)


class Role(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    mission: str
    responsibilities: list[str] = Field(min_length=1)
    out_of_scope: list[str] = Field(min_length=1)
    principles: list[str] = Field(default_factory=list)
    mode: InteractionMode
    talks_to: list[str] = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    permissions: Permissions = Field(default_factory=Permissions)
    delivers: str
    model: str | None = None  # None = the squad's default model

    def instructions(self, squad_name: str | None = None, template: PromptTemplate = EN) -> str:
        """Render this role as the agent's system instructions."""

        def bullets(items: list[str]) -> str:
            return "\n".join(f"- {i}" for i in items)

        t = template
        intro = t.intro_in_squad.format(role=self.name, squad=squad_name) if squad_name else t.intro.format(role=self.name)
        parts = [
            intro,
            f"## {t.mission}\n{self.mission}",
            f"## {t.responsibilities}\n{bullets(self.responsibilities)}",
            f"## {t.out_of_scope}\n{bullets(self.out_of_scope)}",
        ]
        if self.principles:
            parts.append(f"## {t.principles}\n{bullets(self.principles)}")
        parts.append(f"## {t.delivers}\n{self.delivers}")
        return "\n\n".join(parts)
