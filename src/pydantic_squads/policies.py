"""Composition policies: opinionated rules a squad may or may not adopt.

Invariants that hold for every squad live in `Squad` itself. Policies are the
rules that depend on how you want your squad to work, so they are swappable.
A policy is any callable that receives the roles and raises ValueError.
"""

from collections.abc import Callable, Sequence

from pydantic_squads.role import HUMAN, InteractionMode, Role

Policy = Callable[[Sequence[Role]], None]


def single_conversational_role(roles: Sequence[Role]) -> None:
    """The human talks to exactly one agent."""
    conversational = [r.id for r in roles if r.mode == InteractionMode.CONVERSATIONAL]
    if len(conversational) != 1:
        raise ValueError(f"expected exactly 1 conversational role, found {conversational}")


def only_conversational_talks_to_human(roles: Sequence[Role]) -> None:
    """Conversational roles talk to the human; no other role does."""
    for r in roles:
        is_conversational = r.mode == InteractionMode.CONVERSATIONAL
        if is_conversational and HUMAN not in r.talks_to:
            raise ValueError(f"{r.id} is conversational but does not talk to the human")
        if not is_conversational and HUMAN in r.talks_to:
            raise ValueError(f"{r.id} is not conversational and must not talk to the human")


DEFAULT_POLICIES: tuple[Policy, ...] = (
    single_conversational_role,
    only_conversational_talks_to_human,
)
