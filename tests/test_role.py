import pytest
from pydantic import ValidationError

from pydantic_squads import PT_BR, Permissions, Role

from helpers import make_role


def test_invalid_id_rejected():
    """Role ids must be snake_case"""
    with pytest.raises(ValidationError):
        make_role("Not Valid")


def test_role_is_immutable():
    """Roles are immutable after creation"""
    with pytest.raises(ValidationError):
        make_role("a").name = "b"


def test_no_delete_permission():
    """Permissions have no delete capability"""
    assert set(Permissions.model_fields) == {"read", "write", "write_with_approval"}


def test_instructions_render_sections():
    """Instructions render mission, responsibilities and out of scope"""
    text = make_role("a").instructions()
    assert "## Mission" in text and "## Out of scope" in text


def test_principles_optional():
    """Principles section is omitted when empty"""
    assert "## Principles" not in make_role("a").instructions()


def test_instructions_in_portuguese():
    """PT_BR template renders labels in Portuguese"""
    text = make_role("a").instructions(squad_name="Produto", template=PT_BR)
    assert text.startswith("Você é o A da squad Produto.")
    assert "## Fora do seu escopo" in text


def test_principles_rendered():
    """Principles section is rendered when present"""
    role = make_role("a").model_copy(update={"principles": ["Be honest"]})
    assert "## Principles\n- Be honest" in role.instructions()


def test_skills_default_to_empty():
    """A role declares no skills by default"""
    assert make_role("a").skills == []


def test_scripts_default_to_approval():
    """A role's bundled-script policy defaults to requiring approval"""
    assert make_role("a").scripts == "approval"


def test_scripts_rejects_unknown_value():
    """A role's bundled-script policy only accepts never/approval/free"""
    with pytest.raises(ValidationError):
        Role.model_validate(make_role("a").model_dump() | {"scripts": "always"})
