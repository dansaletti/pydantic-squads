from pydantic_squads import HUMAN, InteractionMode, Role


def make_role(id: str, mode: InteractionMode = InteractionMode.TASK, talks_to: list[str] | None = None) -> Role:
    return Role(
        id=id,
        name=id.title(),
        mission="Test mission",
        responsibilities=["Do the thing"],
        out_of_scope=["Everything else"],
        mode=mode,
        talks_to=talks_to or [HUMAN],
        delivers="A result",
    )


def lead(talks_to: list[str] | None = None) -> Role:
    return make_role("lead", InteractionMode.CONVERSATIONAL, [HUMAN, *(talks_to or [])])


def worker(id: str = "worker") -> Role:
    return make_role(id, InteractionMode.TASK, ["lead"])
