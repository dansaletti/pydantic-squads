"""A squad is a validated composition of roles."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pydantic_squads.policies import DEFAULT_POLICIES, Policy
from pydantic_squads.prompt import EN, PromptTemplate
from pydantic_squads.role import HUMAN, Role


class Squad(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    roles: list[Role] = Field(min_length=1)
    policies: tuple[Policy, ...] = Field(default=DEFAULT_POLICIES, exclude=True)
    template: PromptTemplate = EN

    @model_validator(mode="after")
    def _validate(self) -> "Squad":
        # Invariants: true for every squad, not configurable.
        ids = [r.id for r in self.roles]
        if HUMAN in ids:
            raise ValueError(f"'{HUMAN}' is reserved and cannot be a role id")
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate role ids")
        known = set(ids) | {HUMAN}
        for r in self.roles:
            unknown = set(r.talks_to) - known
            if unknown:
                raise ValueError(f"{r.id} talks to unknown roles: {sorted(unknown)}")

        # Policies: opinionated, swappable.
        for policy in self.policies:
            policy(self.roles)
        return self

    def __getitem__(self, role_id: str) -> Role:
        for r in self.roles:
            if r.id == role_id:
                return r
        raise KeyError(role_id)

    def instructions_for(self, role_id: str) -> str:
        return self[role_id].instructions(squad_name=self.name, template=self.template)
