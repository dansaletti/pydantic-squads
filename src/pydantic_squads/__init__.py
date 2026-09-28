"""Declarative, validated agent squads on top of Pydantic AI."""

from pydantic_squads.policies import (
    DEFAULT_POLICIES,
    Policy,
    only_conversational_talks_to_human,
    single_conversational_role,
)
from pydantic_squads.prompt import EN, PT_BR, PromptTemplate
from pydantic_squads.role import HUMAN, InteractionMode, Permissions, Role
from pydantic_squads.squad import Squad

__all__ = [
    "DEFAULT_POLICIES",
    "EN",
    "HUMAN",
    "PT_BR",
    "InteractionMode",
    "Permissions",
    "Policy",
    "PromptTemplate",
    "Role",
    "Squad",
    "only_conversational_talks_to_human",
    "single_conversational_role",
]
