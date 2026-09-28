"""Knowledge base protocol and a markdown/Obsidian-compatible adapter.

Only pydantic (ADR 0001): the product squad's tools (the `ai` extra) call
this protocol, they do not assume a markdown backend.
"""

import re
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

_FRONTMATTER_RE = re.compile(r"\A---\n(?P<frontmatter>.*?)\n---\n?(?P<body>.*)\Z", re.DOTALL)


class Note(BaseModel):
    """A note: its path relative to the knowledge base root, frontmatter and body."""

    model_config = ConfigDict(frozen=True)

    path: str
    frontmatter: dict[str, str | list[str]] = Field(default_factory=dict)
    content: str

    @property
    def tags(self) -> list[str]:
        tags = self.frontmatter.get("tags", [])
        return tags if isinstance(tags, list) else [tags]


@runtime_checkable
class KnowledgeBase(Protocol):
    """Read and write access to a team's notes."""

    def search(self, query: str) -> list[Note]: ...
    def read(self, path: str) -> Note: ...
    def list_by_tag(self, tag: str) -> list[Note]: ...
    def write(self, path: str, content: str) -> None: ...


class MarkdownKnowledgeBase:
    """A `KnowledgeBase` backed by a folder of markdown files with frontmatter.

    Compatible with Obsidian vaults. Paths are resolved relative to `root`
    and anything that would escape it is rejected. There is deliberately no
    delete operation (CLAUDE.md).
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    def _resolve(self, path: str) -> Path:
        candidate = (self.root / path).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError(f"path escapes the knowledge base root: {path}")
        return candidate

    def read(self, path: str) -> Note:
        text = self._resolve(path).read_text(encoding="utf-8")
        frontmatter, body = _parse_note(text)
        return Note(path=path, frontmatter=frontmatter, content=body)

    def list_by_tag(self, tag: str) -> list[Note]:
        return [note for note in self._all_notes() if tag in note.tags]

    def search(self, query: str) -> list[Note]:
        needle = query.lower()
        return [
            note
            for note in self._all_notes()
            if needle in note.content.lower() or needle in note.path.lower()
        ]

    def write(self, path: str, content: str) -> None:
        full = self._resolve(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")

    def _all_notes(self) -> list[Note]:
        notes = []
        for p in sorted(self.root.rglob("*.md")):
            rel = p.relative_to(self.root)
            if any(part.startswith(".") for part in rel.parts):
                continue  # skip dotfiles/dotfolders like .trash, .obsidian
            notes.append(self.read(str(rel)))
        return notes


def _parse_note(text: str) -> tuple[dict[str, str | list[str]], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    return _parse_frontmatter(match["frontmatter"]), match["body"]


def _parse_frontmatter(raw: str) -> dict[str, str | list[str]]:
    """Parse the tiny subset of YAML frontmatter this library needs.

    No YAML dependency (ADR 0001): scalar `key: value` lines, inline
    `key: [a, b]` lists and Obsidian's block `key:` + `  - item` lists.
    """
    result: dict[str, str | list[str]] = {}
    current_list_key: str | None = None
    for line in raw.splitlines():
        if line.startswith("- ") or line.startswith("  - "):
            if current_list_key is not None:
                result.setdefault(current_list_key, [])
                result[current_list_key].append(line.split("-", 1)[1].strip())
            continue
        if ":" not in line:
            current_list_key = None
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not value:
            current_list_key = key
            continue
        current_list_key = None
        if value.startswith("[") and value.endswith("]"):
            result[key] = [item.strip().strip("\"'") for item in value[1:-1].split(",") if item.strip()]
        else:
            result[key] = value.strip("\"'")
    return result
