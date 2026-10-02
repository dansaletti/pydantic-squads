from pathlib import Path

import pytest

import pydantic_squads.product as product_pkg
from pydantic_squads.product.roles import GROWTH_PM

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
def test_marketing_skill_ships_with_the_growth_pm(name):
    """Each marketingskills skill ships a SKILL.md naming itself and is declared by the Growth PM"""
    assert f"name: {name}" in _skill_md(name)
    assert name in GROWTH_PM.skills


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
