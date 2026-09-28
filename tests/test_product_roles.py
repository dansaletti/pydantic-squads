from pydantic_squads.product.roles import GROWTH_PM, HX


def test_growth_pm_can_write_assumptions_with_approval():
    """The Growth PM can write to assumptions/** once approved, to act on an HX proposal (ADR 0004)"""
    assert "assumptions/**" in GROWTH_PM.permissions.write_with_approval


def test_growth_pm_can_still_write_docs_with_approval():
    """The Growth PM can still write to docs/** once approved"""
    assert "docs/**" in GROWTH_PM.permissions.write_with_approval


def test_hx_has_no_write_with_approval():
    """HX has no write_with_approval permission: it cannot request approval (ADR 0004)"""
    assert HX.permissions.write_with_approval == []
