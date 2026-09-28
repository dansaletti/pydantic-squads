from pathlib import Path

import pytest

from pydantic_squads.product import KnowledgeBase, MarkdownKnowledgeBase

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
