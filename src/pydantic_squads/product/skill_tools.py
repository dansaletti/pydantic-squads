"""Runs a skill's script as a typed tool (ADR 0019).

A `SkillTool` binds a `SkillToolSpec` to the skill it belongs to. The
arguments a model sends are validated by a Pydantic model built from the
spec, then turned into a command line for that one script: there is no
shell, no free command, and no script the project did not declare.

Depends only on `pydantic` and the standard library.
"""

import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, create_model

from pydantic_squads.product.skill_registry import Skill
from pydantic_squads.product.skills_config import SkillToolParam, SkillToolSpec

#: A script's output past this many characters is cut before it reaches the model.
MAX_OUTPUT_CHARS = 20_000


class SkillToolError(Exception):
    """A skill tool call that did not produce a result: bad arguments, a timeout or a failed script."""


def _no_leading_dash(value: str) -> str:
    # A value starting with "-" would be read by the script as one of its own options.
    if value.startswith("-"):
        raise ValueError("must not start with '-'")
    return value


def _field(param: SkillToolParam) -> tuple[Any, Any]:
    kind: Any
    if param.type == "boolean":
        return bool, Field(default=False, description=param.description)
    if param.type == "integer":
        kind = Annotated[int, Field(ge=param.minimum, le=param.maximum)]
    elif param.choices is not None:
        kind = Literal[tuple(param.choices)]
    else:
        kind = Annotated[str, AfterValidator(_no_leading_dash)]
    if param.required:
        return kind, Field(description=param.description)
    return Optional[kind], Field(default=None, description=param.description)


def _args_model(spec: SkillToolSpec) -> type[BaseModel]:
    fields: dict[str, Any] = {param.name: _field(param) for param in spec.params}
    return create_model(f"{spec.name}_args", __config__=ConfigDict(extra="forbid"), **fields)


class SkillTool:
    """One declared script of one skill, callable with validated arguments.

    Raises:
        ValueError: If the script is not a Python file inside the skill's folder.
    """

    def __init__(self, spec: SkillToolSpec, skill: Skill) -> None:
        folder = skill.path.resolve()
        script = (folder / spec.script).resolve()
        if not script.is_relative_to(folder) or not script.is_file() or script.suffix != ".py":
            raise ValueError(f"tool '{spec.name}': '{spec.script}' is not a Python script inside skill '{skill.name}'")
        self.spec = spec
        self.skill = skill
        self.script: Path = script
        self.args_model = _args_model(spec)

    @property
    def json_schema(self) -> dict[str, Any]:
        """The JSON schema of the arguments the model may send."""
        return self.args_model.model_json_schema()

    def argv(self, args: Mapping[str, Any]) -> list[str]:
        """The script's arguments for `args`: the fixed ones, then flags, then positionals.

        Raises:
            SkillToolError: If `args` does not validate.
        """
        try:
            validated = self.args_model(**args)
        except ValidationError as error:
            raise SkillToolError(f"invalid arguments for {self.spec.name}: {error}") from error
        flags: list[str] = []
        positionals: list[str] = []
        for param in self.spec.params:
            value = getattr(validated, param.name)
            if value is None or value is False:
                continue
            if param.type == "boolean":
                flags.append(str(param.flag))
            elif param.flag is not None:
                flags += [param.flag, str(value)]
            else:
                positionals.append(str(value))
        return [*self.spec.fixed_args, *flags, *positionals]

    def run(self, args: Mapping[str, Any]) -> str:
        """Run the script with `args` and return what it printed.

        Raises:
            SkillToolError: If `args` does not validate, the script runs past
                `spec.timeout`, or it exits with an error.
        """
        command = [sys.executable, "-B", str(self.script), *self.argv(args)]  # -B: leave no bytecode in the skill
        try:
            done = subprocess.run(  # a declared script, as an argument list: no shell
                command,
                cwd=self.skill.path,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=self.spec.timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise SkillToolError(f"{self.spec.name} timed out after {self.spec.timeout:g}s") from error
        if done.returncode != 0:
            raise SkillToolError(f"{self.spec.name} failed (exit {done.returncode}): {done.stderr.strip()[-2000:]}")
        output = done.stdout.strip() or "(no output)"
        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + "\n[output cut]"
        return output
