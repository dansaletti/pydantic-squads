"""Finds the Agent Skills a project keeps outside this library.

A skill is a folder with a `SKILL.md`: YAML frontmatter (`name`,
`description`) and the instructions under it. Third-party repositories lay
those folders out in their own ways (nested under a plugin, under a hidden
directory, in a folder named differently from the skill), so a
`SkillRegistry` walks whole directories, reads each frontmatter and lets a
project pick skills by name or by where they sit (ADR 0019).

Some repositories also ship commands: a Markdown file, outside any skill,
whose frontmatter has a `description` and whose text chains several skills
into one workflow. The registry lists those too, so a role can be given the
workflow as its authors wrote it and keep up with it when they change it.

Needs the `skills` extra (`pyyaml`, which `pydantic-ai-skills` depends on).
It never imports `pydantic_ai`.
"""

import os
import re
from collections.abc import Sequence
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict

SKILL_FILE = "SKILL.md"

#: Directories never searched for skills.
_SKIPPED_DIRS = frozenset({".git", "node_modules", "__pycache__"})

# A name becomes a folder name in the role's skill library, so it must be one.
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def parse_skill_file(text: str) -> tuple[dict[str, Any], str]:
    """Split a `SKILL.md` into its frontmatter and the instructions under it.

    Returns `({}, text)` when there is no frontmatter, or it is not a YAML
    mapping.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            break
    else:
        return {}, text
    try:
        frontmatter = yaml.safe_load("\n".join(lines[1:index]))
    except yaml.YAMLError:
        return {}, text
    if not isinstance(frontmatter, dict):
        return {}, text
    return frontmatter, "\n".join(lines[index + 1 :]).strip()


class Skill(BaseModel):
    """One skill found on disk. Its instructions are read only when asked for."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    path: Path  # the skill's folder
    location: str  # that folder, relative to the directory it was found under

    @property
    def body(self) -> str:
        """The instructions under the frontmatter, read from disk on demand."""
        return parse_skill_file((self.path / SKILL_FILE).read_text(encoding="utf-8"))[1]


class Command(BaseModel):
    """A workflow file found outside any skill, named after the file."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    path: Path  # the Markdown file
    location: str  # that file, relative to the directory it was found under

    @property
    def body(self) -> str:
        """The workflow under the frontmatter, read from disk on demand."""
        return parse_skill_file(self.path.read_text(encoding="utf-8", errors="replace"))[1]


class SkillRegistry:
    """Every skill under `paths`, however deep.

    `skills` lists them. `skipped` lists each `SKILL.md` that has no usable
    `name` and `description` in its frontmatter: a third-party repository
    may carry one, and it must not take the others down with it.
    `commands` lists every other Markdown file, outside a skill's folder,
    whose frontmatter has a `description`.

    Raises:
        ValueError: If one of `paths` is not a directory.
    """

    def __init__(self, paths: Sequence[Path | str]) -> None:
        self.paths = [Path(path).expanduser() for path in paths]
        self.skills: list[Skill] = []
        self.skipped: list[Path] = []
        self.commands: list[Command] = []
        for root in self.paths:
            if not root.is_dir():
                raise ValueError(f"skills path is not a directory: {root}")
            self._discover(root.resolve())

    def _discover(self, root: Path) -> None:
        for current, dirs, files in os.walk(root):
            if SKILL_FILE not in files:
                dirs[:] = sorted(d for d in dirs if d not in _SKIPPED_DIRS)
                for file in sorted(Path(current) / f for f in files if f.endswith(".md")):
                    description = parse_skill_file(file.read_text(encoding="utf-8", errors="replace"))[0].get("description")
                    if isinstance(description, str) and _NAME.match(file.stem):
                        self.commands.append(
                            Command(
                                name=file.stem,
                                description=description,
                                path=file,
                                location=file.relative_to(root).as_posix(),
                            )
                        )
                continue
            dirs[:] = []  # a skill's own folders are its bundled files, not more skills
            folder = Path(current)
            frontmatter, _ = parse_skill_file((folder / SKILL_FILE).read_text(encoding="utf-8"))
            name, description = frontmatter.get("name"), frontmatter.get("description")
            if not isinstance(name, str) or not _NAME.match(name) or not isinstance(description, str):
                self.skipped.append(folder / SKILL_FILE)
                continue
            self.skills.append(
                Skill(name=name, description=description, path=folder, location=folder.relative_to(root).as_posix())
            )

    def select(self, patterns: Sequence[str]) -> list[Skill]:
        """The skills `patterns` pick, sorted by name.

        A pattern is a glob matched against a skill's name and against its
        location, so `journey-map` picks one skill and `pm-discovery/*`
        picks every skill under that folder. A pattern starting with `!`
        takes its matches back out.

        Raises:
            ValueError: If a pattern matches nothing, or if two different
                folders are picked for the same skill name.
        """
        return _select("skill", self.skills, patterns)

    def select_commands(self, patterns: Sequence[str]) -> list[Command]:
        """The commands `patterns` pick, sorted by name: same patterns as `select`.

        A command's name is its file's name without `.md`, and its location
        is the file's path, so `discover` picks one and
        `pm-discovery/commands/*` picks every command in that folder.

        Raises:
            ValueError: If a pattern matches nothing, or if two different
                files are picked for the same command name.
        """
        return _select("command", self.commands, patterns)


_Found = TypeVar("_Found", Skill, Command)


def _select(kind: str, found: Sequence[_Found], patterns: Sequence[str]) -> list[_Found]:
    picked: dict[Path, _Found] = {}
    for pattern in patterns:
        glob = pattern.removeprefix("!")
        matches = [item for item in found if fnmatchcase(item.name, glob) or fnmatchcase(item.location, glob)]
        if not matches:
            available = ", ".join(sorted({item.name for item in found})) or "none"
            raise ValueError(f"no {kind} matches '{pattern}'. Found: {available}")
        for item in matches:
            if pattern.startswith("!"):
                picked.pop(item.path, None)
            else:
                picked[item.path] = item
    by_name: dict[str, _Found] = {}
    for item in picked.values():
        other = by_name.setdefault(item.name, item)
        if other is not item:
            raise ValueError(
                f"{kind} '{item.name}' is in two places ({other.path} and {item.path}): "
                "pick one by its location, or leave the other out with a '!' pattern"
            )
    return sorted(by_name.values(), key=lambda item: item.name)
