from pydantic_squads.product import build_product_squad


def test_default_language_is_english():
    """build_product_squad defaults to English"""
    squad = build_product_squad()
    text = squad.instructions_for("growth_pm")
    assert "## Mission" in text
    assert "Always answer in English." in text


def test_role_ids_are_stable():
    """The product squad always has growth_pm, hx, product_owner and designer"""
    squad = build_product_squad()
    assert [r.id for r in squad.roles] == ["growth_pm", "hx", "product_owner", "designer"]


def test_portuguese_language_selects_pt_br_template():
    """language='pt-BR' renders labels and directive in Portuguese"""
    squad = build_product_squad("pt-BR")
    text = squad.instructions_for("growth_pm")
    assert "## Missão" in text
    assert "Sempre responda em português." in text


def test_language_does_not_mutate_shared_role_constants():
    """Building the squad does not add the directive to the shared Role objects"""
    from pydantic_squads.product.roles import GROWTH_PM

    build_product_squad("pt-BR")
    assert "Sempre responda em português." not in GROWTH_PM.principles
