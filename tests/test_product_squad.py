from pydantic_squads.product import build_product_squad


def test_default_language_is_english():
    """build_product_squad defaults to English"""
    squad = build_product_squad()
    text = squad.instructions_for("facilitator")
    assert "## Mission" in text
    assert "Always answer in English." in text


def test_role_ids_are_stable():
    """The product squad's eight roles keep their ids and order"""
    squad = build_product_squad()
    assert [r.id for r in squad.roles] == [
        "facilitator",
        "growth_pm",
        "pm_product",
        "pm_marketing",
        "hx",
        "product_owner",
        "designer",
        "social_media",
    ]


def test_portuguese_language_selects_pt_br_template():
    """language='pt-BR' renders labels and directive in Portuguese"""
    squad = build_product_squad("pt-BR")
    text = squad.instructions_for("facilitator")
    assert "## Missão" in text
    assert "Sempre responda em português." in text


def test_language_does_not_mutate_shared_role_constants():
    """Building the squad does not add the directive to the shared Role objects"""
    from pydantic_squads.product.roles import GROWTH_PM

    build_product_squad("pt-BR")
    assert "Sempre responda em português." not in GROWTH_PM.principles


def test_product_squad_passes_the_default_policies_with_one_conversational_role():
    """The squad satisfies the default policies: the Facilitator is its single conversational role"""
    from pydantic_squads import InteractionMode
    from pydantic_squads.policies import DEFAULT_POLICIES

    squad = build_product_squad()
    for policy in DEFAULT_POLICIES:
        policy(squad.roles)
    assert [r.id for r in squad.roles if r.mode == InteractionMode.CONVERSATIONAL] == ["facilitator"]


def test_product_owner_single_door_is_a_policy_of_the_squad():
    """A role other than the Facilitator that talks to the Product Owner is rejected"""
    import pytest

    from pydantic_squads.product import PRODUCT_POLICIES, product_owner_has_one_door
    from pydantic_squads.product.roles import GROWTH_PM

    assert product_owner_has_one_door in PRODUCT_POLICIES
    squad = build_product_squad()
    leaky = GROWTH_PM.model_copy(update={"talks_to": ["facilitator", "product_owner"]})
    with pytest.raises(ValueError, match="only the Facilitator"):
        product_owner_has_one_door([*squad.roles, leaky])
