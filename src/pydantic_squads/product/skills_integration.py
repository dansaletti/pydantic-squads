"""Skill support for the product squad: SKILL.md packages with references/,
assets/ and scripts/.

Needs the optional `skills` extra (`pydantic-ai-skills`). Isolated in this
one module: nothing else in `pydantic_squads.product` imports it, so the
`ai` extra alone still works without it (`ProductSquad` with neither
`skills_dirs` nor `skills`, the default, never imports this module — see
`assembly.py`).

A project's own skills, picked per role by a `SkillsConfig`, are wired here
too: `SquadSkills` resolves them once for the whole squad (ADR 0019).

See ADR 0005 for why `pydantic-ai-skills` is used here instead of
`pydantic-ai-harness`'s own `Skills` capability, which only loads a
`SKILL.md`'s instructions body and does not enumerate, read or execute a
skill's bundled `references/`, `assets/` or `scripts/` files.
"""

import atexit
import shutil
import tempfile
from collections.abc import Collection, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from pydantic_ai import ApprovalRequiredToolset, ModelRetry, Tool
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai_skills import LocalSkillScriptExecutor, SkillsCapability
from pydantic_ai_skills._toolset import SkillFilesToolset

from pydantic_squads import Role, Squad
from pydantic_squads.product.skill_registry import SKILL_FILE, Command, Skill, SkillRegistry
from pydantic_squads.product.skill_tools import SkillTool, SkillToolError
from pydantic_squads.product.skills_config import SkillsConfig

#: Execution timeout for a skill's bundled scripts, in seconds.
SCRIPT_TIMEOUT_SECONDS = 30

#: The library's own skills, always available alongside whatever the
#: consuming project passes as `ProductSquad(skills_dirs=...)`.
LIBRARY_SKILLS_DIR = Path(__file__).parent / "skills"

_RUN_SKILL_SCRIPT = "run_skill_script"

# The tools skills already bring: a declared skill tool may not take one of these names.
_SKILL_TOOL_NAMES = frozenset({"load_capability", "read_skill_resource", _RUN_SKILL_SCRIPT})


def _run_skill_script_requires_approval(ctx: Any, tool_def: Any, args: dict[str, Any]) -> bool:
    return tool_def.name == _RUN_SKILL_SCRIPT


#: Put before a command's own text when it is handed to a role as a skill.
COMMAND_NOTE = (
    "This is a workflow written as a slash command. There are no slash commands here: follow its "
    "steps in the conversation, loading each skill it names with `load_capability` when you reach it."
)


def stage_skills(skills: Sequence[Skill], commands: Sequence[Command] = ()) -> Path:
    """A skill library holding one link per skill, each named after its skill.

    A command becomes a skill of its own in that library: a `SKILL.md`
    written from the command's description and text as they are on disk
    now, so an updated repository needs nothing redone here.

    `pydantic-ai-skills` reads a library as a folder whose immediate
    children are skills, each in a folder named after it. Skills a project
    installs are rarely laid out that way, so they are linked into a
    temporary library that is (ADR 0019). It is removed when the process
    ends.
    """
    library = Path(tempfile.mkdtemp(prefix="pydantic-squads-skills-"))
    atexit.register(shutil.rmtree, library, ignore_errors=True)
    for skill in skills:
        (library / skill.name).symlink_to(skill.path, target_is_directory=True)
    for command in commands:
        frontmatter = yaml.safe_dump({"name": command.name, "description": command.description}, allow_unicode=True)
        (library / command.name).mkdir()
        (library / command.name / SKILL_FILE).write_text(
            f"---\n{frontmatter}---\n\n{COMMAND_NOTE}\n\n{command.body}\n", encoding="utf-8"
        )
    return library


def _as_tool(skill_tool: SkillTool) -> Tool[Any]:
    def run(**args: Any) -> str:
        try:
            return skill_tool.run(args)
        except SkillToolError as error:
            raise ModelRetry(str(error)) from error

    return Tool.from_schema(
        run, name=skill_tool.spec.name, description=skill_tool.spec.description, json_schema=skill_tool.json_schema
    )


def build_role_tools(role: Role, tools: Sequence[SkillTool]) -> Any | None:
    """Build the toolset exposing `tools`, the skill scripts declared for `role`.

    Returns `None` when there are none. A tool whose spec asks for
    `approval` pauses for the human, unless `role.scripts` is `"free"`.
    """
    if not tools:
        return None
    toolset: Any = FunctionToolset([_as_tool(tool) for tool in tools])
    gated = frozenset(tool.spec.name for tool in tools if tool.spec.approval and role.scripts != "free")
    if gated:
        toolset = ApprovalRequiredToolset(toolset, approval_required_func=lambda ctx, tool_def, args: tool_def.name in gated)
    return toolset


class SquadSkills:
    """A squad's skills, resolved once: the library's, the given directories' and the project's.

    `squad` is the squad to build agents from: with a `config`, each role
    carries the project skills picked for it and the rules written for it.
    `kwargs_for(role)` gives the `capabilities=`/`toolsets=` of that role's
    agent. `gated_roles` names the roles holding a tool that pauses for
    approval.

    Raises:
        ValueError: If `config` names a role the squad does not have, picks
            a skill or command that does not exist, gives a role a command
            named like one of its skills, or declares a tool for a role
            that lacks its skill, may not run scripts, or already has a
            tool of that name.
    """

    def __init__(self, squad: Squad, skills_dirs: Sequence[Path], config: SkillsConfig | None = None) -> None:
        self.squad = squad
        self.gated_roles: set[str] = set()
        self._dirs = [LIBRARY_SKILLS_DIR, *skills_dirs]
        self._libraries: dict[str, Path] = {}
        self._project_skills: dict[str, list[Skill]] = {}
        self._tools: dict[str, list[SkillTool]] = {}
        if config is None:
            return

        named = {*config.roles, *config.commands, *config.rules, *(role_id for tool in config.tools for role_id in tool.roles)}
        unknown = sorted(named - {role.id for role in squad.roles})
        if unknown:
            raise ValueError(f"skills config names roles the squad does not have: {unknown}")

        registry = SkillRegistry(config.paths)
        roles = []
        for role in squad.roles:
            try:
                skills = registry.select(config.roles.get(role.id, []))
                commands = registry.select_commands(config.commands.get(role.id, []))
            except ValueError as e:
                raise ValueError(f"role '{role.id}': {e}") from e
            added = [*(skill.name for skill in skills), *(command.name for command in commands)]
            clash = sorted({*role.skills, *(skill.name for skill in skills)} & {command.name for command in commands})
            if clash:
                raise ValueError(f"role '{role.id}': commands named like a skill it already has: {clash}")
            if added:
                self._project_skills[role.id] = skills
                self._libraries[role.id] = stage_skills(skills, commands)
            roles.append(
                role.model_copy(
                    update={
                        "skills": [*role.skills, *added],
                        "principles": [*role.principles, *config.rules.get(role.id, [])],
                    }
                )
            )
        self.squad = squad.model_copy(update={"roles": roles})

        for spec in config.tools:
            for role_id in spec.roles:
                role = self.squad[role_id]
                skill = next((s for s in self._project_skills.get(role_id, []) if s.name == spec.skill), None)
                if skill is None:
                    raise ValueError(f"tool '{spec.name}': role '{role_id}' does not have the skill '{spec.skill}'")
                if role.scripts == "never":
                    raise ValueError(f"tool '{spec.name}': role '{role_id}' may not run skill scripts")
                if spec.name in {*role.tools, *_SKILL_TOOL_NAMES}:
                    raise ValueError(f"tool '{spec.name}': role '{role_id}' already has a tool of that name")
                self._tools.setdefault(role_id, []).append(SkillTool(spec, skill))
                if spec.approval and role.scripts != "free":
                    self.gated_roles.add(role_id)

    def kwargs_for(self, role: Role) -> dict[str, list[Any]]:
        """The `capabilities=`/`toolsets=` kwargs of `role`'s agent; empty when it has no skill."""
        role = self.squad[role.id]
        project = self._project_skills.get(role.id, [])
        dirs = [*self._dirs, self._libraries[role.id]] if role.id in self._libraries else self._dirs
        capability, toolset = build_role_skills(role, dirs, typed_only=[skill.name for skill in project])
        toolsets = [t for t in (toolset, build_role_tools(role, self._tools.get(role.id, []))) if t is not None]
        kwargs: dict[str, list[Any]] = {}
        if capability is not None:
            kwargs["capabilities"] = [capability]
        if toolsets:
            kwargs["toolsets"] = toolsets
        return kwargs


def build_role_skills(
    role: Role, skills_dirs: Sequence[Path], typed_only: Collection[str] = ()
) -> tuple[Any | None, Any | None]:
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
        skills_dirs: Skill-library directories to search. Two of them
            holding a skill of the same name is an error when the role
            declares it.
        typed_only: Names of skills whose scripts `run_skill_script` must
            not reach: a project's skills, whose scripts run only as the
            typed tools the project declared (ADR 0019).

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

    packages = {
        name: replace(package, scripts=()) if name in typed_only else package
        for name, package in capability.packages.items()
    }
    toolset = SkillFilesToolset(
        packages,
        resources=True,
        scripts=role.scripts != "never",
    )
    if role.scripts == "approval":
        toolset = ApprovalRequiredToolset(toolset, approval_required_func=_run_skill_script_requires_approval)

    return capability, toolset
