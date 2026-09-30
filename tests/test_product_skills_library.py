from pathlib import Path

import pydantic_squads.product as product_pkg

SKILLS_DIR = Path(product_pkg.__file__).parent / "skills"


def _skill_md(name: str) -> str:
    return (SKILLS_DIR / name / "SKILL.md").read_text()


def _has_reference_file(name: str) -> bool:
    return bool(list((SKILLS_DIR / name / "references").glob("*")))


def test_prioritization_skill_has_skill_md_and_a_reference_file():
    """The prioritization skill ships a SKILL.md naming itself and at least one references/ file"""
    assert "name: prioritization" in _skill_md("prioritization")
    assert _has_reference_file("prioritization")


def test_evidence_classification_skill_has_skill_md_and_a_reference_file():
    """The evidence-classification skill ships a SKILL.md naming itself and at least one references/ file"""
    assert "name: evidence-classification" in _skill_md("evidence-classification")
    assert _has_reference_file("evidence-classification")


def test_user_stories_skill_has_skill_md_and_a_reference_file():
    """The user-stories skill ships a SKILL.md naming itself and at least one references/ file"""
    assert "name: user-stories" in _skill_md("user-stories")
    assert _has_reference_file("user-stories")


def test_user_stories_skill_explains_needs_design():
    """The user-stories skill tells the Product Owner how to set needs_design"""
    assert "needs_design" in _skill_md("user-stories")


def test_prototyping_skill_has_skill_md_and_a_reference_file():
    """The prototyping skill ships a SKILL.md naming itself and at least one references/ file"""
    assert "name: prototyping" in _skill_md("prototyping")
    assert _has_reference_file("prototyping")


def test_prototyping_skill_references_every_bundled_file():
    """The prototyping SKILL.md points to each of its references/ files"""
    skill_md = _skill_md("prototyping")
    for reference in (SKILLS_DIR / "prototyping" / "references").glob("*.md"):
        assert f"references/{reference.name}" in skill_md
