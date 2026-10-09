"""What a project says about skills: where they are and which role uses which.

The library ships the mechanism; a project decides the content (ADR 0019).
A `SkillsConfig` names the directories holding the project's skills, the
skills each role may load on top of the library's own, the rules each role
follows when using them, and the skill scripts exposed as typed tools.

Depends only on `pydantic`. `load_skills_config` reads YAML and so needs
the `skills` extra, imported lazily.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_IDENTIFIER = r"^[a-z][a-z0-9_]*$"


class SkillToolParam(BaseModel):
    """One argument of a skill tool, and how it reaches the script."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=_IDENTIFIER)
    type: Literal["string", "integer", "boolean"] = "string"
    flag: str | None = Field(default=None, pattern=r"^--?[A-Za-z][A-Za-z0-9-]*$")  # None: a positional argument
    description: str = ""
    required: bool = False
    choices: list[str] | None = None  # string only
    minimum: int | None = None  # integer only
    maximum: int | None = None  # integer only

    @model_validator(mode="after")
    def _validate(self) -> "SkillToolParam":
        if self.type == "boolean" and self.flag is None:
            raise ValueError(f"boolean parameter '{self.name}' needs a flag")
        if self.choices is not None and self.type != "string":
            raise ValueError(f"parameter '{self.name}': choices only apply to a string")
        if (self.minimum is not None or self.maximum is not None) and self.type != "integer":
            raise ValueError(f"parameter '{self.name}': minimum and maximum only apply to an integer")
        return self


class SkillToolSpec(BaseModel):
    """A skill's script, declared as a typed tool for some roles.

    The model never names the script or writes its command line: it fills
    `params`, and only those. `fixed_args` are put on the command line by
    the project, before anything the model says, so a destination such as
    an output directory is never the model's to choose.

    `approval` (the default) pauses each call for the human, like an
    approval-gated note write. Turn it off only for a script that writes
    nothing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=_IDENTIFIER)
    roles: list[str] = Field(min_length=1)
    skill: str
    script: str  # relative to the skill's folder
    description: str = Field(min_length=1)
    params: list[SkillToolParam] = Field(default_factory=list)
    fixed_args: list[str] = Field(default_factory=list)
    timeout: float = Field(default=30, gt=0)  # seconds
    approval: bool = True

    @model_validator(mode="after")
    def _validate(self) -> "SkillToolSpec":
        names = [param.name for param in self.params]
        if len(names) != len(set(names)):
            raise ValueError(f"tool '{self.name}' declares a parameter twice")
        return self


class SkillsConfig(BaseModel):
    """A project's skills: directories, role mapping, role rules and typed tools.

    `roles` maps a role id to patterns picking skills from `paths` (see
    `SkillRegistry.select`); they add to the skills the role already has.
    `commands` does the same for command files (see
    `SkillRegistry.select_commands`): each one reaches the role as a skill
    of the same name, holding the workflow it describes.
    `rules` maps a role id to lines added to that role's principles.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    paths: list[Path] = Field(default_factory=list)
    roles: dict[str, list[str]] = Field(default_factory=dict)
    commands: dict[str, list[str]] = Field(default_factory=dict)
    rules: dict[str, list[str]] = Field(default_factory=dict)
    tools: list[SkillToolSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> "SkillsConfig":
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("two skill tools share a name")
        return self


def _expand(value: str, base: Path) -> str:
    """`value` with `~` expanded and, when it is a relative path, resolved against `base`."""
    path = Path(value).expanduser()
    return str(path if path.is_absolute() else base / path)


def load_skills_config(path: Path | str) -> SkillsConfig:
    """Read the `skills:` section of a YAML config file.

    Entries of `paths` are resolved against the file's own folder, with `~`
    expanded. In a tool's `fixed_args`, only an argument starting with `~`
    or `./` is treated as a path and resolved the same way.

    Raises:
        ValueError: If the file has no `skills:` mapping, or it is invalid.
    """
    import yaml

    path = Path(path).expanduser()
    data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    section = data.get("skills") if isinstance(data, dict) else None
    if not isinstance(section, dict):
        raise ValueError(f"{path} has no 'skills:' section")
    base = path.resolve().parent
    section = dict(section)
    section["paths"] = [_expand(str(p), base) for p in section.get("paths") or []]
    tools = []
    for tool in section.get("tools") or []:
        tool = dict(tool)
        tool["fixed_args"] = [
            _expand(arg, base) if arg.startswith(("~", "./")) else arg
            for arg in (str(a) for a in tool.get("fixed_args") or [])
        ]
        tools.append(tool)
    section["tools"] = tools
    return SkillsConfig.model_validate(section)
