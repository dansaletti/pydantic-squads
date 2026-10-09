import sys
from pathlib import Path

import pytest

pytest.importorskip("yaml", reason="requires the 'skills' extra: uv sync --extra skills")

from pydantic import ValidationError

from pydantic_squads.product.skills_config import SkillsConfig, SkillToolParam, SkillToolSpec, load_skills_config


def _spec(**overrides) -> SkillToolSpec:
    values = {"name": "search", "roles": ["designer"], "skill": "foundation", "script": "s.py", "description": "d"}
    return SkillToolSpec(**{**values, **overrides})


@pytest.mark.parametrize(
    ("param", "message"),
    [
        ({"name": "persist", "type": "boolean"}, "needs a flag"),
        ({"name": "count", "type": "integer", "choices": ["1"]}, "choices only apply to a string"),
        ({"name": "query", "minimum": 1}, "only apply to an integer"),
    ],
    ids=["boolean without a flag", "choices on an integer", "minimum on a string"],
)
def test_skill_tool_param_rejects_a_shape_that_cannot_reach_the_script(param, message):
    """A parameter that could not be turned into a command-line argument is rejected when declared"""
    with pytest.raises(ValidationError, match=message):
        SkillToolParam(**param)


def test_skill_tool_spec_defaults_to_needing_approval():
    """A declared skill tool pauses for the human unless the project says it writes nothing"""
    assert _spec().approval is True and _spec().timeout == 30


def test_skill_tool_spec_rejects_a_parameter_declared_twice():
    """Two parameters of one tool cannot share a name"""
    with pytest.raises(ValidationError, match="declares a parameter twice"):
        _spec(params=[{"name": "query"}, {"name": "query"}])


def test_skills_config_rejects_two_tools_with_one_name():
    """Two skill tools cannot share a name"""
    with pytest.raises(ValidationError, match="share a name"):
        SkillsConfig(tools=[_spec(), _spec()])


def test_skills_config_rejects_an_unknown_key():
    """A typo in the config is an error, not a setting silently ignored"""
    with pytest.raises(ValidationError):
        SkillsConfig(role={"designer": ["foundation"]})


def test_load_skills_config_reads_the_skills_section(tmp_path, monkeypatch):
    """load_skills_config reads roles, rules and tools, resolving paths against the file's folder and ~"""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    config_file = tmp_path / "squads.yaml"
    config_file.write_text(
        """
skills:
  paths: [skills, ~/shared, /abs/skills]
  roles:
    designer: [foundation]
  rules:
    designer: [Read MASTER.md first.]
  tools:
    - name: persist
      roles: [designer]
      skill: foundation
      script: scripts/search.py
      description: Persist the design system.
      fixed_args: [--persist, --output-dir, ~/vault, --cache, ./cache, --level, 3]
"""
    )
    config = load_skills_config(config_file)
    base = tmp_path.resolve()
    assert config.paths == [base / "skills", tmp_path / "home" / "shared", Path("/abs/skills")]
    assert config.roles == {"designer": ["foundation"]} and config.rules == {"designer": ["Read MASTER.md first."]}
    assert config.tools[0].fixed_args == [
        "--persist",
        "--output-dir",
        str(tmp_path / "home" / "vault"),
        "--cache",
        str(base / "cache"),
        "--level",
        "3",
    ]


def test_load_skills_config_accepts_a_section_with_only_roles(tmp_path):
    """A skills section may leave paths and tools out"""
    config_file = tmp_path / "squads.yaml"
    config_file.write_text("skills:\n  roles: {}\n")
    assert load_skills_config(config_file) == SkillsConfig()


@pytest.mark.parametrize("text", ["other: 1\n", "- a list\n", "skills: nope\n"], ids=["no section", "a list", "not a mapping"])
def test_load_skills_config_rejects_a_file_without_a_skills_section(tmp_path, text):
    """A config file with no skills: mapping fails clearly"""
    config_file = tmp_path / "squads.yaml"
    config_file.write_text(text)
    with pytest.raises(ValueError, match="has no 'skills:' section"):
        load_skills_config(config_file)


def test_skills_config_module_needs_no_yaml_until_a_file_is_loaded(monkeypatch, tmp_path):
    """Building a SkillsConfig in Python never imports yaml; only loading a file does"""
    monkeypatch.setitem(sys.modules, "yaml", None)
    assert SkillsConfig(paths=[tmp_path]).paths == [tmp_path]
    with pytest.raises(ImportError):
        load_skills_config(tmp_path / "squads.yaml")


def test_the_example_config_is_valid():
    """examples/skills.yaml, the Phase 1 config the README points to, loads as a SkillsConfig"""
    config = load_skills_config(Path(__file__).parent.parent / "examples" / "skills.yaml")
    assert sorted(config.roles) == ["designer", "pm_product"] and sorted(config.rules) == ["designer", "pm_product"]
    assert sorted(config.commands) == ["pm_product"]
    assert {tool.name: tool.approval for tool in config.tools} == {
        "design_search": False,
        "design_system": False,
        "persist_design_system": True,
    }
