from pathlib import Path

import pytest

import pydantic_squads.product as product_pkg
from pydantic_squads.product.roles import GROWTH_PM, PM_MARKETING, SOCIAL_MEDIA

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


@pytest.mark.parametrize("name", ["user-stories", "story-mapping", "impeccable"])
def test_product_owner_skill_references_every_bundled_file(name):
    """Each Product Owner SKILL.md points to each of its references/ files"""
    skill_md = _skill_md(name)
    for reference in (SKILLS_DIR / name / "references").glob("*.md"):
        assert f"references/{reference.name}" in skill_md


def test_story_mapping_skill_has_skill_md_and_a_reference_file():
    """The story-mapping skill ships a SKILL.md naming itself and at least one references/ file"""
    assert "name: story-mapping" in _skill_md("story-mapping")
    assert _has_reference_file("story-mapping")


def test_prototyping_skill_has_skill_md_and_a_reference_file():
    """The prototyping skill ships a SKILL.md naming itself and at least one references/ file"""
    assert "name: prototyping" in _skill_md("prototyping")
    assert _has_reference_file("prototyping")


def test_prototyping_skill_references_every_bundled_file():
    """The prototyping SKILL.md points to each of its references/ files"""
    skill_md = _skill_md("prototyping")
    for reference in (SKILLS_DIR / "prototyping" / "references").glob("*.md"):
        assert f"references/{reference.name}" in skill_md


MARKETING_SKILLS = [
    "ab-testing",
    "analytics",
    "churn-prevention",
    "customer-research",
    "launch",
    "marketing-psychology",
    "onboarding",
    "paywalls",
    "pricing",
    "product-marketing",
    "referrals",
    "social",
]


@pytest.mark.parametrize("name", MARKETING_SKILLS)
def test_marketing_skill_ships_with_exactly_one_role(name):
    """Each marketingskills skill ships a SKILL.md naming itself and is declared by exactly one role"""
    assert f"name: {name}" in _skill_md(name)
    assert sum(name in role.skills for role in (GROWTH_PM, PM_MARKETING, SOCIAL_MEDIA)) == 1


@pytest.mark.parametrize("name", MARKETING_SKILLS)
def test_marketing_skill_has_no_upstream_only_paths(name):
    """Adapted skills don't point to .agents/ files or the upstream tools/ registry"""
    for path in (SKILLS_DIR / name).rglob("*.md"):
        text = path.read_text()
        assert ".agents/" not in text, path
        assert "tools/integrations" not in text and "tools/REGISTRY" not in text, path


def test_third_party_notice_credits_marketingskills():
    """The notice names the upstream repo and carries its MIT license"""
    notice = (SKILLS_DIR / "THIRD_PARTY_NOTICE.md").read_text()
    assert "coreyhaines31/marketingskills" in notice
    assert "MIT License" in notice


def test_impeccable_skill_has_no_upstream_tooling():
    """The adapted impeccable skill ships no scripts and never calls the upstream launcher"""
    skill_dir = SKILLS_DIR / "impeccable"
    assert not (skill_dir / "scripts").exists()
    for path in skill_dir.rglob("*.md"):
        text = path.read_text()
        assert "scripts/impeccable" not in text, path
        assert "`/impeccable" not in text, path
        assert "DESIGN.md" not in text, path


def test_third_party_notice_credits_impeccable():
    """The notice names the impeccable repo, and its Apache license ships with the skill"""
    notice = (SKILLS_DIR / "THIRD_PARTY_NOTICE.md").read_text()
    assert "pbakaus/impeccable" in notice
    assert "Apache License" in (SKILLS_DIR / "impeccable" / "LICENSE").read_text()
