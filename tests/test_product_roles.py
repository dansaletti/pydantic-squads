from pydantic_squads import HUMAN, InteractionMode
from pydantic_squads.product.roles import DESIGNER, GROWTH_PM, HX, PRODUCT_OWNER


def test_growth_pm_declares_its_skills():
    """The Growth PM declares prioritization first, then its marketing skills"""
    assert GROWTH_PM.skills[0] == "prioritization"
    assert len(GROWTH_PM.skills) == 13


def test_hx_declares_its_skill():
    """HX declares the evidence-classification skill"""
    assert HX.skills == ["evidence-classification"]


def test_product_owner_declares_its_skill():
    """The Product Owner declares the user-stories and story-mapping skills"""
    assert PRODUCT_OWNER.skills == ["user-stories", "story-mapping"]


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


def test_designer_is_a_task_role_that_never_talks_to_the_human():
    """The Designer receives a Backlog and delivers a Prototype, without talking to the human"""
    assert DESIGNER.mode == InteractionMode.TASK
    assert HUMAN not in DESIGNER.talks_to
    assert set(DESIGNER.talks_to) == {"product_owner", "hx"}


def test_designer_declares_its_skill():
    """The Designer loads the prototyping skill"""
    assert DESIGNER.skills == ["prototyping", "impeccable"]


def test_designer_can_consult_hx():
    """The Designer has the consult_hx tool"""
    assert "consult_hx" in DESIGNER.tools


def test_designer_writes_design_notes_freely_and_the_design_system_with_approval():
    """The Designer writes squad/design/** freely and design-system/** only with approval"""
    assert DESIGNER.permissions.write == ["squad/design/**"]
    assert DESIGNER.permissions.write_with_approval == ["design-system/**"]
