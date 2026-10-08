import threading
import time
from pathlib import Path

import pytest

from pydantic_squads.product import (
    KnowledgeBase,
    MarkdownKnowledgeBase,
    Note,
    SerializedKnowledgeBase,
    excerpt,
    format_note,
)

VAULT = Path(__file__).parent / "fixtures" / "vault"


def test_read_parses_inline_list_tags_and_body():
    """Reading a note with inline-list tags separates them from the body"""
    kb = MarkdownKnowledgeBase(VAULT)
    note = kb.read("interviews/onboarding-friction.md")
    assert note.tags == ["onboarding", "evidence"]
    assert "signup wizard" in note.content


def test_read_parses_block_list_tags():
    """Reading a note with Obsidian's block-list tags parses them too"""
    kb = MarkdownKnowledgeBase(VAULT)
    note = kb.read("assumptions/shorter-onboarding-lifts-activation.md")
    assert note.tags == ["onboarding", "assumption"]


def test_read_parses_scalar_frontmatter_fields():
    """A non-list frontmatter field like title is parsed as a plain string"""
    kb = MarkdownKnowledgeBase(VAULT)
    note = kb.read("context/product.md")
    assert note.frontmatter["title"] == "Product context"


def test_list_by_tag_filters_notes():
    """list_by_tag returns only notes carrying that tag"""
    kb = MarkdownKnowledgeBase(VAULT)
    onboarding = kb.list_by_tag("onboarding")
    assert {n.path for n in onboarding} == {
        "interviews/onboarding-friction.md",
        "assumptions/shorter-onboarding-lifts-activation.md",
    }


def test_list_by_tag_with_no_matches_is_empty():
    """list_by_tag returns an empty list when nothing carries the tag"""
    kb = MarkdownKnowledgeBase(VAULT)
    assert kb.list_by_tag("nonexistent") == []


def test_search_matches_content_case_insensitively():
    """search matches a substring in note content regardless of case"""
    kb = MarkdownKnowledgeBase(VAULT)
    results = kb.search("DISPATCH MANAGER")
    assert [n.path for n in results] == ["context/product.md"]


def test_search_matches_path():
    """search also matches a substring in the note's path"""
    kb = MarkdownKnowledgeBase(VAULT)
    results = kb.search("interviews/")
    assert [n.path for n in results] == ["interviews/onboarding-friction.md"]


def test_search_ignores_dotfolders(tmp_path):
    """search skips notes under a dot-prefixed folder like .trash or .obsidian"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("notes/keep.md", "alpha content")
    kb.write(".trash/deleted.md", "alpha content too")
    kb.write(".obsidian/workspace.md", "alpha content as well")
    assert [n.path for n in kb.search("alpha")] == ["notes/keep.md"]


def test_list_by_tag_ignores_dotfolders(tmp_path):
    """list_by_tag skips notes under a dot-prefixed folder like .trash or .obsidian"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("notes/keep.md", "---\ntags: [x]\n---\nbody")
    kb.write(".trash/deleted.md", "---\ntags: [x]\n---\nbody")
    assert [n.path for n in kb.list_by_tag("x")] == ["notes/keep.md"]


def test_read_still_works_for_a_note_inside_a_dotfolder(tmp_path):
    """Dotfolders are only skipped by enumeration (search/list_by_tag); direct read still works"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write(".trash/deleted.md", "still readable directly")
    assert kb.read(".trash/deleted.md").content == "still readable directly"


def test_all_notes_skips_a_directory_matching_the_md_glob(tmp_path):
    """search/list_by_tag skip an entry that matches *.md but is actually a directory"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("keep.md", "alpha content")
    (tmp_path / "oops.md").mkdir()
    assert [n.path for n in kb.search("alpha")] == ["keep.md"]


def test_all_notes_skips_a_broken_symlink(tmp_path):
    """search/list_by_tag skip a note whose file can't be read, like a broken symlink"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("keep.md", "alpha content")
    (tmp_path / "broken.md").symlink_to(tmp_path / "does-not-exist.md")
    assert [n.path for n in kb.search("alpha")] == ["keep.md"]


def test_all_notes_skips_a_symlink_escaping_the_root(tmp_path):
    """search/list_by_tag skip a note whose symlink target resolves outside the vault root"""
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.md").write_text("alpha content")
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("keep.md", "alpha content")
    (tmp_path / "escape.md").symlink_to(outside / "secret.md")
    assert [n.path for n in kb.search("alpha")] == ["keep.md"]


def test_write_then_read_round_trips(tmp_path):
    """A note written to the vault can be read back with its frontmatter"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("squad/bets/faster-onboarding.md", "---\ntags: [bet]\n---\nHypothesis: ...")
    note = kb.read("squad/bets/faster-onboarding.md")
    assert note.tags == ["bet"]
    assert "Hypothesis" in note.content


def test_write_creates_missing_parent_directories(tmp_path):
    """write creates parent directories that do not exist yet"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("a/b/c.md", "body")
    assert (tmp_path / "a" / "b" / "c.md").exists()


def test_note_without_frontmatter_has_empty_tags(tmp_path):
    """A note with no frontmatter block still reads, with no tags"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("plain.md", "just body text")
    note = kb.read("plain.md")
    assert note.tags == []
    assert note.content == "just body text"


def test_format_note_round_trips_through_a_written_and_read_note(tmp_path):
    """format_note renders text that read() parses back into the same frontmatter and content"""
    kb = MarkdownKnowledgeBase(tmp_path)
    text = format_note({"cycle_id": "abc123", "tags": ["bet", "onboarding"]}, "Hypothesis: ...")
    kb.write("squad/bets/x.md", text)
    note = kb.read("squad/bets/x.md")
    assert note.frontmatter["cycle_id"] == "abc123"
    assert note.tags == ["bet", "onboarding"]
    assert note.content == "Hypothesis: ..."


def test_format_note_with_no_frontmatter_returns_content_unchanged():
    """format_note skips the frontmatter block entirely when given an empty dict"""
    assert format_note({}, "just body text") == "just body text"


def test_frontmatter_blank_line_is_ignored(tmp_path):
    """A blank line inside frontmatter does not break parsing"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("n.md", "---\ntitle: X\n\ntags: [a]\n---\nbody")
    note = kb.read("n.md")
    assert note.frontmatter["title"] == "X"
    assert note.tags == ["a"]


def test_frontmatter_orphan_list_item_is_ignored(tmp_path):
    """A bullet line with no preceding list key is ignored, not an error"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("n.md", "---\n- orphan\ntags: [a]\n---\nbody")
    assert kb.read("n.md").tags == ["a"]


def test_read_rejects_path_outside_root(tmp_path):
    """Reading a path that escapes the vault root is rejected"""
    kb = MarkdownKnowledgeBase(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        kb.read("../outside.md")


def test_write_rejects_path_outside_root(tmp_path):
    """Writing a path that escapes the vault root is rejected"""
    kb = MarkdownKnowledgeBase(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        kb.write("../outside.md", "content")


def test_no_delete_method():
    """MarkdownKnowledgeBase exposes no delete operation"""
    assert not hasattr(MarkdownKnowledgeBase, "delete")


def test_satisfies_knowledge_base_protocol(tmp_path):
    """MarkdownKnowledgeBase structurally satisfies the KnowledgeBase protocol"""
    assert isinstance(MarkdownKnowledgeBase(tmp_path), KnowledgeBase)


@pytest.mark.parametrize(
    "ref",
    ["9. Premissas a validar", "[[9. Premissas a validar]]", "[[9. Premissas a validar|Premissas]]", "assumptions/9. Premissas a validar"],
)
def test_read_resolves_obsidian_style_references(tmp_path, ref):
    """read resolves a bare note name, a [[wikilink]] or a path without .md to the real note"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("assumptions/9. Premissas a validar.md", "premissas")
    note = kb.read(ref)
    assert note.path == "assumptions/9. Premissas a validar.md"
    assert note.content == "premissas"


def test_read_does_not_guess_between_notes_with_the_same_name(tmp_path):
    """read fails on a bare name shared by two notes instead of picking one"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("docs/x.md", "a")
    kb.write("assumptions/x.md", "b")
    with pytest.raises(FileNotFoundError):
        kb.read("x")


def test_search_matches_any_word_and_ranks_by_how_many_match(tmp_path):
    """search with several words returns notes matching some of them, the best matches first"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("a.md", "growth via lista de espera")
    kb.write("b.md", "canais de aquisição e growth")
    kb.write("c.md", "nada a ver")
    results = kb.search("growth aquisição canais")
    assert [n.path for n in results] == ["b.md", "a.md"]


def test_search_ranks_the_whole_phrase_first(tmp_path):
    """A note containing the whole query ranks above one that only has its words apart"""
    kb = MarkdownKnowledgeBase(tmp_path)
    kb.write("a.md", "manager of dispatch, dispatch manager's friend")
    kb.write("b.md", "dispatch then manager")
    kb.write("c.md", "the dispatch manager")
    results = kb.search("dispatch manager")
    assert [n.path for n in results] == ["a.md", "c.md", "b.md"]


# -- SerializedKnowledgeBase: one writer at a time (ADR 0010) ---------------


class _SlowWriteKB(MarkdownKnowledgeBase):
    """A knowledge base whose writes take a while and count how many overlap."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.writing = 0
        self.most_at_once = 0
        self._count_lock = threading.Lock()

    def write(self, path: str, content: str) -> None:
        with self._count_lock:
            self.writing += 1
            self.most_at_once = max(self.most_at_once, self.writing)
        time.sleep(0.01)
        super().write(path, content)
        with self._count_lock:
            self.writing -= 1


def _write_from_threads(kb: KnowledgeBase, count: int) -> None:
    start = threading.Barrier(count)

    def write(i: int) -> None:
        start.wait(timeout=5)
        kb.write(f"squad/n{i}.md", f"note {i}")

    threads = [threading.Thread(target=write, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)


def test_serialized_knowledge_base_writes_one_at_a_time(tmp_path):
    """Writes from several threads never overlap behind a SerializedKnowledgeBase"""
    inner = _SlowWriteKB(tmp_path)
    _write_from_threads(SerializedKnowledgeBase(inner), 5)
    assert inner.most_at_once == 1
    assert sorted(p.name for p in (tmp_path / "squad").iterdir()) == [f"n{i}.md" for i in range(5)]


def test_unserialized_writes_do_overlap(tmp_path):
    """The same writes overlap without the wrapper, so the test above does prove the lock"""
    inner = _SlowWriteKB(tmp_path)
    _write_from_threads(inner, 5)
    assert inner.most_at_once > 1


def test_serialized_knowledge_base_passes_reads_through():
    """search, read and list_by_tag answer exactly as the wrapped knowledge base does"""
    inner = MarkdownKnowledgeBase(VAULT)
    kb = SerializedKnowledgeBase(inner)
    assert kb.read("context/product.md") == inner.read("context/product.md")
    assert kb.search("onboarding") == inner.search("onboarding")
    assert kb.list_by_tag("evidence") == inner.list_by_tag("evidence")


def test_serialized_knowledge_base_satisfies_the_protocol_and_cannot_delete(tmp_path):
    """SerializedKnowledgeBase is a KnowledgeBase and exposes no delete operation"""
    assert isinstance(SerializedKnowledgeBase(MarkdownKnowledgeBase(tmp_path)), KnowledgeBase)
    assert not hasattr(SerializedKnowledgeBase, "delete")


def test_wrap_does_not_wrap_twice(tmp_path):
    """wrap() returns an already serialized knowledge base unchanged, so there is one lock"""
    kb = SerializedKnowledgeBase.wrap(MarkdownKnowledgeBase(tmp_path))
    assert isinstance(kb, SerializedKnowledgeBase)
    assert SerializedKnowledgeBase.wrap(kb) is kb


# -- excerpt(): a note as a search result (ADR 0015) -------------------------

_LONG = "Intro paragraph. " + "filler " * 80 + "Managers email routes to drivers every morning. " + "filler " * 80


def test_excerpt_is_the_text_around_the_match_not_the_whole_note():
    """excerpt() returns a short window around the matched words, marked where it was cut"""
    note = Note(path="interviews/a.md", frontmatter={"tags": ["evidence"]}, content=_LONG)
    result = excerpt(note, "email routes")
    assert result.path == "interviews/a.md" and result.tags == ["evidence"]
    assert result.size == len(_LONG)
    [text] = result.excerpts
    assert "Managers email routes to drivers" in text
    assert len(text) <= 242 and text.startswith("…") and text.endswith("…")


def test_excerpt_gives_one_window_per_distant_match_up_to_the_limit():
    """Words matched far apart get an excerpt each, in note order, and never more than the limit"""
    content = "alpha here. " + "filler " * 100 + "beta there. " + "filler " * 100 + "gamma last."
    note = Note(path="a.md", content=content)
    result = excerpt(note, "gamma alpha beta")
    assert len(result.excerpts) == 2
    assert "alpha here" in result.excerpts[0] and "beta there" in result.excerpts[1]
    assert len(excerpt(note, "gamma alpha beta", limit=3).excerpts) == 3


def test_excerpt_does_not_repeat_a_window_for_words_that_are_close():
    """Two words inside the same window make one excerpt"""
    note = Note(path="a.md", content="alpha and beta sit together in this short note")
    assert excerpt(note, "alpha beta").excerpts == ["alpha and beta sit together in this short note"]


def test_excerpt_falls_back_to_the_beginning_of_the_note():
    """With no query, or a match only in the path, the excerpt is how the note begins"""
    note = Note(path="docs/pricing.md", content="First line of the note.\n\nSecond   paragraph." + " tail" * 200)
    for query in ("", "pricing", "de a"):
        [text] = excerpt(note, query).excerpts
        assert text.startswith("First line of the note. Second paragraph.") and text.endswith("…")


def test_excerpt_of_an_empty_note_has_no_text():
    """A note with no content yields no excerpt, only its path and size"""
    result = excerpt(Note(path="a.md", content="  \n"), "alpha")
    assert result.excerpts == [] and result.size == 3
