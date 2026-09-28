"""Skill support for the product squad: SKILL.md packages with references/,
assets/ and scripts/.

Needs the optional `skills` extra (`pydantic-ai-skills`). Isolated in this
one module: nothing else in `pydantic_squads.product` imports it, so the
`ai` extra alone still works without it (`ProductSquad(skills_dirs=None)`,
the default, never imports this module — see `assembly.py`).

See ADR 0005 for why `pydantic-ai-skills` is used here instead of
`pydantic-ai-harness`'s own `Skills` capability, which only loads a
`SKILL.md`'s instructions body and does not enumerate, read or execute a
skill's bundled `references/`, `assets/` or `scripts/` files.
"""

from pathlib import Path
from typing import Any

from pydantic_ai import ApprovalRequiredToolset
from pydantic_ai_skills import LocalSkillScriptExecutor, SkillsCapability
from pydantic_ai_skills._toolset import SkillFilesToolset

from pydantic_squads import Role

#: Execution timeout for a skill's bundled scripts, in seconds.
SCRIPT_TIMEOUT_SECONDS = 30

#: The library's own skills, always available alongside whatever the
#: consuming project passes as `ProductSquad(skills_dirs=...)`.
LIBRARY_SKILLS_DIR = Path(__file__).parent / "skills"

_RUN_SKILL_SCRIPT = "run_skill_script"


def _run_skill_script_requires_approval(ctx: Any, tool_def: Any, args: dict[str, Any]) -> bool:
    return tool_def.name == _RUN_SKILL_SCRIPT


def build_role_skills(role: Role, skills_dirs: list[Path]) -> tuple[Any | None, Any | None]:
    """Build the `(capability, toolset)` pair exposing `role`'s declared skills.

    Returns `(None, None)` when `role.skills` is empty. Each agent gets a
    `SkillsCapability` scoped to its own role via `include`, so it never
    sees another role's skills — even one from the same directories.

    `role.scripts` controls the bundled-script tool:

    - `"never"`: the agent has no `run_skill_script` tool at all.
    - `"approval"` (the default): `run_skill_script` calls need human
      approval, the same `ApprovalRequired` / `DeferredToolRequests` path
      as an approval-gated note write. `read_skill_resource` stays free.
    - `"free"`: `run_skill_script` runs without approval.

    Args:
        role: The role to scope the skill catalog to.
        skills_dirs: Skill-library directories to search, most specific
            last (a later directory's skill wins a name collision).

    Raises:
        ValueError: If `role.skills` names a skill none of `skills_dirs`
            contains.
    """
    if not role.skills:
        return None, None

    try:
        capability = SkillsCapability(
            skills_dirs,
            include=role.skills,
            resources=False,
            scripts=False,
            script_executor=LocalSkillScriptExecutor(timeout=SCRIPT_TIMEOUT_SECONDS),
        )
    except ValueError as e:
        raise ValueError(f"role '{role.id}': {e}") from e

    toolset = SkillFilesToolset(
        capability.packages,
        resources=True,
        scripts=role.scripts != "never",
    )
    if role.scripts == "approval":
        toolset = ApprovalRequiredToolset(toolset, approval_required_func=_run_skill_script_requires_approval)

    return capability, toolset
