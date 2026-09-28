import importlib.util
from pathlib import Path


def test_product_squad_example_is_valid():
    """The product squad example builds a valid squad"""
    path = Path(__file__).parent.parent / "examples" / "product_squad" / "roles.py"
    spec = importlib.util.spec_from_file_location("product_roles", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert [r.id for r in module.PRODUCT_SQUAD.roles] == ["growth_pm", "hx", "product_owner"]
