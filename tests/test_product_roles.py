from pydantic_squads.product.roles import GROWTH_PM, HX, PRODUCT_OWNER


def test_growth_pm_declares_its_skill():
    """The Growth PM declares the prioritization skill"""
    assert GROWTH_PM.skills == ["prioritization"]


def test_hx_declares_its_skill():
    """HX declares the evidence-classification skill"""
    assert HX.skills == ["evidence-classification"]


def test_product_owner_declares_its_skill():
    """The Product Owner declares the user-stories skill"""
    assert PRODUCT_OWNER.skills == ["user-stories"]


def test_growth_pm_can_write_assumptions_with_approval():
    """The Growth PM can write to assumptions/** once approved, to act on an HX proposal (ADR 0004)"""
    assert "assumptions/**" in GROWTH_PM.permissions.write_with_approval


def test_growth_pm_can_still_write_docs_with_approval():
    """The Growth PM can still write to docs/** once approved"""
    assert "docs/**" in GROWTH_PM.permissions.write_with_approval


def test_hx_has_no_write_with_approval():
    """HX has no write_with_approval permission: it cannot request approval (ADR 0004)"""
    assert HX.permissions.write_with_approval == []


def test_product_owner_marks_needs_design():
    """The Product Owner is responsible for deciding each story's needs_design"""
    assert any("needs_design" in r for r in PRODUCT_OWNER.responsibilities)
