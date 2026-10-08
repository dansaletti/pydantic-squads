"""Knowledge base protocol and a markdown/Obsidian-compatible adapter.

Only pydantic (ADR 0001): the product squad's tools (the `ai` extra) call
this protocol, they do not assume a markdown backend.
"""

import re
import threading
from pathlib import Path, PurePosixPath
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


class NoteExcerpt(BaseModel):
    """A note as a search result: where it is and the parts that matched, not the whole note."""

    model_config = ConfigDict(frozen=True)

    path: str
    tags: list[str] = Field(default_factory=list)
    size: int  # characters in the whole note, so a reader knows what reading it costs
    excerpts: list[str] = Field(default_factory=list)


def _terms(query: str) -> set[str]:
    """The words of `query` worth matching: words of two letters or less (`de`, `a`, `of`) are ignored."""
    return {term for term in re.findall(r"\w+", query.lower()) if len(term) > 2}


def excerpt(note: Note, query: str = "", *, width: int = 240, limit: int = 2) -> NoteExcerpt:
    """`note` cut down to at most `limit` excerpts of about `width` characters around what `query` matched.

    The whole query is looked for first, then each of its words. When
    nothing matches in the content (the match was in the path, or there is
    no query), the excerpt is the beginning of the note. Whitespace is
    collapsed and a cut is marked with `…`.
    """
    content = note.content
    lowered = content.lower()
    needle = query.lower().strip()
    found = [lowered.find(target) for target in ([needle] if needle else []) + sorted(_terms(query))]
    windows: list[tuple[int, int]] = []
    for position in [p for p in found if p >= 0] or [0]:
        if len(windows) == limit or any(start <= position < end for start, end in windows):
            continue
        start = max(0, position - width // 3)
        windows.append((start, min(len(content), start + width)))
    excerpts = []
    for start, end in sorted(windows):
        text = " ".join(content[start:end].split())
        if text:
            excerpts.append(("…" if start > 0 else "") + text + ("…" if end < len(content) else ""))
    return NoteExcerpt(path=note.path, tags=note.tags, size=len(content), excerpts=excerpts)


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
        """Read a note by its path, or by an Obsidian-style reference.

        `docs/x.md`, `docs/x` and, when exactly one note in the vault is
        named `x`, `x` or `[[x|alias]]` all read `docs/x.md`. The returned
        note carries the real path, so callers check permissions on it.
        """
        path = self._locate(path)
        text = self._resolve(path).read_text(encoding="utf-8")
        frontmatter, body = _parse_note(text)
        return Note(path=path, frontmatter=frontmatter, content=body)

    def _locate(self, path: str) -> str:
        ref = path.strip()
        if ref.startswith("[[") and ref.endswith("]]"):
            ref = ref[2:-2].split("|", 1)[0].split("#", 1)[0].strip()
        candidates = [ref] if ref.endswith(".md") else [ref, f"{ref}.md"]
        for candidate in candidates:
            if self._resolve(candidate).exists():
                return candidate
        name = ref.removesuffix(".md")
        named = [p for p in self._note_paths() if PurePosixPath(p).name.removesuffix(".md") == name]
        return named[0] if len(named) == 1 else ref  # missing or ambiguous: let the read fail

    def list_by_tag(self, tag: str) -> list[Note]:
        return [note for note in self._all_notes() if tag in note.tags]

    def search(self, query: str) -> list[Note]:
        """Notes matching any word of `query` in their path or content, best first.

        A note containing the whole query ranks above any partial match; then
        notes rank by how many words they contain, ties broken by path. Words
        of two letters or less (`de`, `a`, `of`) are ignored.
        """
        needle = query.lower().strip()
        terms = _terms(query)
        scored: list[tuple[int, Note]] = []
        for note in self._all_notes():
            haystack = f"{note.path}\n{note.content}".lower()
            score = sum(term in haystack for term in terms)
            if needle and needle in haystack:
                score += len(terms) + 1
            if score:
                scored.append((score, note))
        scored.sort(key=lambda item: (-item[0], item[1].path))
        return [note for _, note in scored]

    def write(self, path: str, content: str) -> None:
        full = self._resolve(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")

    def _note_paths(self) -> list[str]:
        paths = []
        for p in sorted(self.root.rglob("*.md")):
            rel = p.relative_to(self.root)
            if any(part.startswith(".") for part in rel.parts):
                continue  # skip dotfiles/dotfolders like .trash, .obsidian
            paths.append(rel.as_posix())
        return paths

    def _all_notes(self) -> list[Note]:
        notes = []
        for rel in self._note_paths():
            try:
                notes.append(self.read(rel))
            except (OSError, ValueError):
                continue  # skip notes that can't be read: a directory, a
                # broken symlink, or one whose target escapes the vault root
        return notes


class SerializedKnowledgeBase:
    """A `KnowledgeBase` whose writes go through a single writer, one at a time.

    Reads pass straight through, so any number of agents can query the
    knowledge base in parallel; `write` holds a lock, so two of them never
    write at once (ADR 0010). The lock is a thread lock, not an asyncio one:
    the squad's note tools are plain functions, which run in worker threads.
    Like every knowledge base, it has no delete operation.
    """

    def __init__(self, kb: KnowledgeBase) -> None:
        self._kb = kb
        self._write_lock = threading.Lock()

    @classmethod
    def wrap(cls, kb: KnowledgeBase) -> "SerializedKnowledgeBase":
        """`kb` behind a single writer; one that already is comes back unchanged."""
        return kb if isinstance(kb, cls) else cls(kb)

    def search(self, query: str) -> list[Note]:
        return self._kb.search(query)

    def read(self, path: str) -> Note:
        return self._kb.read(path)

    def list_by_tag(self, tag: str) -> list[Note]:
        return self._kb.list_by_tag(tag)

    def write(self, path: str, content: str) -> None:
        with self._write_lock:
            self._kb.write(path, content)


def format_note(frontmatter: dict[str, str | list[str]], content: str) -> str:
    """Render frontmatter and content into markdown text `_parse_note` can read back.

    The inverse of `_parse_frontmatter`, for the same tiny subset of YAML
    (ADR 0001): scalar `key: value` lines and block `key:` + `  - item`
    lists. Returns `content` unchanged when `frontmatter` is empty.
    """
    if not frontmatter:
        return content
    lines: list[str] = []
    for key, value in frontmatter.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{key}: {value}")
    return "---\n" + "\n".join(lines) + "\n---\n" + content


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
