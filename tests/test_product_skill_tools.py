import json

import pytest

pytest.importorskip("yaml", reason="requires the 'skills' extra: uv sync --extra skills")

from helpers import write_script, write_skill

from pydantic_squads.product.skill_registry import Skill
from pydantic_squads.product.skill_tools import MAX_OUTPUT_CHARS, SkillTool, SkillToolError
from pydantic_squads.product.skills_config import SkillToolSpec

PARAMS = [
    {"name": "query", "required": True, "description": "What to search for"},
    {"name": "domain", "flag": "--domain", "choices": ["style", "color"]},
    {"name": "limit", "type": "integer", "flag": "-n", "minimum": 1, "maximum": 20},
    {"name": "page", "flag": "--page"},
    {"name": "full", "type": "boolean", "flag": "--full"},
]


def _skill(tmp_path) -> Skill:
    folder = write_skill(tmp_path, "foundation")
    write_script(folder)
    return Skill(name="foundation", description="d", path=folder, location="foundation")


def _tool(tmp_path, **overrides) -> SkillTool:
    values = {
        "name": "search",
        "roles": ["designer"],
        "skill": "foundation",
        "script": "scripts/echo.py",
        "description": "Search the design data.",
        "params": PARAMS,
    }
    return SkillTool(SkillToolSpec(**{**values, **overrides}), _skill(tmp_path))


def test_skill_tool_runs_its_script_in_the_skill_folder(tmp_path):
    """A skill tool runs the declared script with the skill's folder as the working directory"""
    tool = _tool(tmp_path)
    output = json.loads(tool.run({"query": "calm wellness app"}))
    assert output == {"argv": ["calm wellness app"], "cwd": str(tool.skill.path.resolve())}


def test_skill_tool_builds_the_command_line_from_validated_arguments(tmp_path):
    """Fixed arguments come first, then flags, then positionals; unset and false ones are left out"""
    tool = _tool(tmp_path, fixed_args=["--output-dir", "/vault"])
    args = {"query": "spa", "domain": "color", "limit": 5, "full": True}
    assert tool.argv(args) == ["--output-dir", "/vault", "--domain", "color", "-n", "5", "--full", "spa"]
    assert tool.argv({"query": "spa", "full": False}) == ["--output-dir", "/vault", "spa"]


def test_skill_tool_schema_lists_only_the_declared_parameters(tmp_path):
    """The schema the model sees has the declared parameters, their constraints and nothing else"""
    schema = _tool(tmp_path).json_schema
    assert sorted(schema["properties"]) == ["domain", "full", "limit", "page", "query"]
    assert schema["required"] == ["query"] and schema["additionalProperties"] is False
    assert schema["properties"]["query"]["description"] == "What to search for"


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"query": "spa", "domain": "fonts"},
        {"query": "spa", "limit": 99},
        {"query": "spa", "limit": "many"},
        {"query": "spa", "output_dir": "/etc"},
        {"query": "--output-dir=/etc"},
        {"query": "spa", "page": "--force"},
    ],
    ids=[
        "missing required",
        "not a choice",
        "past the maximum",
        "wrong type",
        "undeclared parameter",
        "positional posing as an option",
        "flag value posing as an option",
    ],
)
def test_skill_tool_rejects_invalid_arguments_without_running_the_script(tmp_path, args, monkeypatch):
    """Arguments that do not validate never reach a subprocess"""
    tool = _tool(tmp_path)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("the script must not run"))
    with pytest.raises(SkillToolError, match="invalid arguments for search"):
        tool.run(args)


def test_skill_tool_times_out(tmp_path):
    """A script running past the tool's timeout is stopped and reported"""
    tool = _tool(tmp_path, timeout=0.2, fixed_args=["--sleep"])
    with pytest.raises(SkillToolError, match="search timed out after 0.2s"):
        tool.run({"query": "spa"})


def test_skill_tool_reports_a_failing_script_with_its_stderr(tmp_path):
    """A script exiting with an error is reported with its exit code and stderr"""
    tool = _tool(tmp_path, fixed_args=["--fail"])
    with pytest.raises(SkillToolError, match=r"search failed \(exit 3\): boom"):
        tool.run({"query": "spa"})


def test_skill_tool_says_so_when_the_script_prints_nothing(tmp_path):
    """A script that prints nothing still gives the model an answer"""
    assert _tool(tmp_path, fixed_args=["--quiet"]).run({"query": "spa"}) == "(no output)"


def test_skill_tool_cuts_a_very_long_output(tmp_path):
    """Output past the limit is cut before it reaches the model"""
    output = _tool(tmp_path, fixed_args=["--big"]).run({"query": "spa"})
    assert output.endswith("[output cut]") and len(output) < MAX_OUTPUT_CHARS + 20


@pytest.mark.parametrize(
    "script", ["../outside.py", "scripts/missing.py", "SKILL.md"], ids=["outside the skill", "missing", "not Python"]
)
def test_skill_tool_only_accepts_a_python_script_inside_its_skill(tmp_path, script):
    """A tool cannot be declared for a file outside the skill's folder, a missing one or a non-Python one"""
    (tmp_path / "outside.py").write_text("print('escaped')")
    with pytest.raises(ValueError, match="is not a Python script inside skill 'foundation'"):
        _tool(tmp_path, script=script)
