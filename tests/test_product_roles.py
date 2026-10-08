from pydantic_squads import HUMAN, InteractionMode
from pydantic_squads.product.roles import (
    DESIGNER,
    FACILITATOR,
    GROWTH_PM,
    HX,
    PM_MARKETING,
    PM_PRODUCT,
    PRODUCT_OWNER,
    SOCIAL_MEDIA,
)
from pydantic_squads.product.squad import COMMITTEE_ROLES


def test_growth_pm_declares_its_skills():
    """The Growth PM declares prioritization first, then its growth skills, and none of the Marketing PM's"""
    assert GROWTH_PM.skills[0] == "prioritization"
    assert len(GROWTH_PM.skills) == 9
    assert not set(GROWTH_PM.skills) & {"product-marketing", "marketing-psychology", "launch", "social"}


def test_hx_declares_its_skill():
    """HX declares the evidence-classification skill"""
    assert HX.skills == ["evidence-classification"]


def test_product_owner_declares_its_skill():
    """The Product Owner declares the user-stories and story-mapping skills"""
    assert PRODUCT_OWNER.skills == ["user-stories", "story-mapping"]


def test_facilitator_can_write_assumptions_and_docs_with_approval():
    """The Facilitator, the one role with a path to the human, carries out approved writes (ADR 0004, ADR 0013)"""
    assert FACILITATOR.permissions.write_with_approval == ["docs/**", "assumptions/**"]
    assert FACILITATOR.permissions.write == []


def test_facilitator_is_the_only_conversational_role_and_is_neutral():
    """Only the Facilitator talks to the human; it has no PM skill and opinions are out of its scope"""
    assert FACILITATOR.mode == InteractionMode.CONVERSATIONAL and HUMAN in FACILITATOR.talks_to
    assert FACILITATOR.skills == []
    assert any("opinion" in item for item in FACILITATOR.out_of_scope)
    for role in (GROWTH_PM, PM_PRODUCT, PM_MARKETING, HX, PRODUCT_OWNER, DESIGNER, SOCIAL_MEDIA):
        assert role.mode != InteractionMode.CONVERSATIONAL and HUMAN not in role.talks_to


def test_growth_pm_is_a_task_role_like_the_other_pms():
    """The Growth PM no longer talks to the human or the Product Owner, and cannot write"""
    assert GROWTH_PM.mode == InteractionMode.TASK
    assert GROWTH_PM.talks_to == ["facilitator", "hx"] == PM_PRODUCT.talks_to == PM_MARKETING.talks_to
    assert "write_note" not in GROWTH_PM.tools
    assert GROWTH_PM.permissions.write == [] and GROWTH_PM.permissions.write_with_approval == []


def test_pms_do_not_talk_to_each_other():
    """No PM lists another PM: there is no free debate in the squad's graph"""
    for role in (GROWTH_PM, PM_PRODUCT, PM_MARKETING):
        assert not set(role.talks_to) & set(COMMITTEE_ROLES)


def test_only_the_facilitator_talks_to_the_product_owner():
    """The Product Owner hears the Facilitator alone, and nobody else lists it"""
    assert PRODUCT_OWNER.talks_to == ["facilitator"]
    for role in (GROWTH_PM, PM_PRODUCT, PM_MARKETING, HX, DESIGNER, SOCIAL_MEDIA):
        assert "product_owner" not in role.talks_to


def test_hx_has_no_write_with_approval():
    """HX has no write_with_approval permission: it cannot request approval (ADR 0004)"""
    assert HX.permissions.write_with_approval == []


def test_hx_is_read_only():
    """HX has no write tool and no write permission at all: it is a query tool (ADR 0010)"""
    assert "write_note" not in HX.tools
    assert HX.permissions.write == []
    assert any("opinion" in item for item in HX.out_of_scope)


def test_hx_is_told_a_gap_has_no_source():
    """HX's responsibilities say a gap is given no source, which the Finding contract enforces"""
    assert any("gap no source" in item for item in HX.responsibilities)


def test_product_owner_marks_needs_design():
    """The Product Owner is responsible for deciding each story's needs_design"""
    assert any("needs_design" in r for r in PRODUCT_OWNER.responsibilities)


def test_designer_is_a_task_role_that_never_talks_to_the_human():
    """The Designer receives a Backlog and delivers a Prototype, without talking to the human"""
    assert DESIGNER.mode == InteractionMode.TASK
    assert HUMAN not in DESIGNER.talks_to
    assert set(DESIGNER.talks_to) == {"hx", "pm_marketing"}


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


def test_product_pm_is_a_task_role_that_only_reads():
    """The Product PM never talks to the human and has no write tool or permission"""
    assert PM_PRODUCT.mode == InteractionMode.TASK
    assert HUMAN not in PM_PRODUCT.talks_to
    assert "write_note" not in PM_PRODUCT.tools
    assert PM_PRODUCT.permissions.write == [] and PM_PRODUCT.permissions.write_with_approval == []


def test_product_pm_delivers_an_opinion_and_does_not_debate():
    """The Product PM delivers an Opinion, consults HX, and answering another PM is out of its scope"""
    assert "Opinion" in PM_PRODUCT.delivers
    assert "consult_hx" in PM_PRODUCT.tools
    assert any("another PM" in item for item in PM_PRODUCT.out_of_scope)


def test_committee_roles_are_the_pms_that_give_opinions():
    """The committee is the Growth PM, the Product PM and the Marketing PM"""
    assert COMMITTEE_ROLES == ("growth_pm", "pm_product", "pm_marketing")


def test_marketing_pm_owns_the_brand_skills_and_only_reads():
    """The Marketing PM holds the positioning skills, gives an Opinion and never writes"""
    assert PM_MARKETING.skills == ["product-marketing", "marketing-psychology", "launch"]
    assert PM_MARKETING.mode == InteractionMode.TASK
    assert HUMAN not in PM_MARKETING.talks_to
    assert "write_note" not in PM_MARKETING.tools
    assert PM_MARKETING.permissions.write == [] and PM_MARKETING.permissions.write_with_approval == []


def test_designer_takes_brand_questions_to_the_marketing_pm():
    """The Designer can consult the Marketing PM, which decides brand ahead of the founder"""
    assert "consult_pm_marketing" in DESIGNER.tools
    assert any("Marketing PM" in item for item in DESIGNER.responsibilities)


def test_social_media_sits_under_the_marketing_pm():
    """Social Media talks only to the Marketing PM, writes only under squad/content, and is outside the committee"""
    assert SOCIAL_MEDIA.mode == InteractionMode.TASK
    assert SOCIAL_MEDIA.talks_to == ["pm_marketing"]
    assert SOCIAL_MEDIA.permissions.write == ["squad/content/**"]
    assert SOCIAL_MEDIA.permissions.write_with_approval == []
    assert SOCIAL_MEDIA.skills == ["social"]
    assert "social_media" not in COMMITTEE_ROLES
