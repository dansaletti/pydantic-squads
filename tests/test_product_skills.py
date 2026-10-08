import os
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import pytest

pytest.importorskip("pydantic_ai", reason="requires the 'ai' extra: uv sync --extra ai")
pytest.importorskip("pydantic_ai_skills", reason="requires the 'skills' extra: uv sync --extra skills")

from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from pydantic_squads import InteractionMode, Role
from pydantic_squads.product.assembly import ProductSquad
from pydantic_squads.product.knowledge import MarkdownKnowledgeBase
from pydantic_squads.product.roles import GROWTH_PM, HX, PRODUCT_OWNER
from pydantic_squads.product.skills_integration import LIBRARY_SKILLS_DIR, build_role_skills

FIXTURE_SKILLS_DIR = Path(__file__).parent / "fixtures" / "skills"
TEST_CONTEXT = "A B2B tool for small logistics companies."


def _role(skills: list[str] | None = None, scripts: str = "approval") -> Role:
    return Role(
        id="tester",
        name="Tester",
        mission="m",
        responsibilities=["r"],
        out_of_scope=["o"],
        mode=InteractionMode.TASK,
        talks_to=["growth_pm"],
        skills=skills or [],
        scripts=scripts,
        delivers="d",
    )


def _text(text: str):
    return lambda messages, info: ModelResponse(parts=[TextPart(text)])


def _call_tool(name: str, args: dict):
    return lambda messages, info: ModelResponse(parts=[ToolCallPart(name, args)])


def _scripted_model(*turns) -> FunctionModel:
    """A FunctionModel that plays back `turns` in order, one per model call."""
    state = {"n": 0}

    def fn(messages, info):
        i = state["n"]
        state["n"] += 1
        assert i < len(turns), f"scripted model called more times ({i + 1}) than turns provided ({len(turns)})"
        return turns[i](messages, info)

    return FunctionModel(fn)


def _build_test_agent(role: Role, skills_dirs: list[Path], model) -> Agent:
    capability, toolset = build_role_skills(role, skills_dirs)
    return Agent(
        model,
        deps_type=str,
        output_type=[str, DeferredToolRequests],
        capabilities=[capability] if capability else [],
        toolsets=[toolset] if toolset else [],
    )


# -- build_role_skills: pure wiring, one model call at most -----------------


def test_build_role_skills_returns_none_for_a_role_with_no_skills():
    """build_role_skills returns (None, None) when the role declares no skills"""
    capability, toolset = build_role_skills(_role(skills=[]), [FIXTURE_SKILLS_DIR])
    assert capability is None
    assert toolset is None


def test_build_role_skills_raises_clear_error_for_unknown_skill():
    """A role declaring a skill that doesn't exist fails clearly at assembly time"""
    with pytest.raises(ValueError, match="role 'tester'"):
        build_role_skills(_role(skills=["nonexistent-skill"]), [FIXTURE_SKILLS_DIR])


def test_build_role_skills_scopes_catalog_to_declared_skills():
    """The capability only ever exposes the skills the role actually declared"""
    capability, _ = build_role_skills(_role(skills=["test-skill"]), [FIXTURE_SKILLS_DIR])
    assert capability.skill_names == ["test-skill"]


def test_library_skills_dir_has_the_three_shipped_skills():
    """The library's own skills directory resolves to the 3 shipped skills"""
    capability, _ = build_role_skills(
        _role(skills=["prioritization", "evidence-classification", "user-stories"]), [LIBRARY_SKILLS_DIR]
    )
    assert capability.skill_names == ["evidence-classification", "prioritization", "user-stories"]


# -- Role.scripts governs run_skill_script -----------------------------------


def test_scripts_never_has_no_run_skill_script_tool():
    """scripts='never' means the agent has no run_skill_script tool at all"""
    captured = {}

    def fn(messages, info):
        captured["names"] = sorted(t.name for t in info.function_tools)
        return ModelResponse(parts=[TextPart("ok")])

    agent = _build_test_agent(_role(skills=["test-skill"], scripts="never"), [FIXTURE_SKILLS_DIR], FunctionModel(fn))
    agent.run_sync("hi", deps="kb")
    assert "run_skill_script" not in captured["names"]
    assert "read_skill_resource" in captured["names"]


def test_scripts_never_still_allows_read_skill_resource():
    """scripts='never' only removes the script tool; reading resources still works"""
    agent = _build_test_agent(
        _role(skills=["test-skill"], scripts="never"),
        [FIXTURE_SKILLS_DIR],
        _scripted_model(
            _call_tool("load_capability", {"id": "test-skill"}),
            _call_tool("read_skill_resource", {"skill_name": "test-skill", "resource_name": "references/notes.md"}),
            _text("read it"),
        ),
    )
    result = agent.run_sync("hi", deps="kb")
    assert result.output == "read it"


def test_scripts_approval_pauses_run_skill_script(tmp_path):
    """scripts='approval' defers run_skill_script for human approval, like an approval-gated write"""
    agent = _build_test_agent(
        _role(skills=["test-skill"], scripts="approval"),
        [FIXTURE_SKILLS_DIR],
        _scripted_model(
            _call_tool("load_capability", {"id": "test-skill"}),
            _call_tool("read_skill_resource", {"skill_name": "test-skill", "resource_name": "references/notes.md"}),
            _call_tool("run_skill_script", {"skill_name": "test-skill", "script_name": "scripts/greet.py"}),
        ),
    )
    result = agent.run_sync("hi", deps="kb")
    assert isinstance(result.output, DeferredToolRequests)
    assert result.output.approvals[0].tool_name == "run_skill_script"


def test_scripts_approval_resumes_and_runs_after_approval():
    """Resuming a deferred run_skill_script with approval actually runs the script"""
    agent = _build_test_agent(
        _role(skills=["test-skill"], scripts="approval"),
        [FIXTURE_SKILLS_DIR],
        _scripted_model(
            _call_tool("load_capability", {"id": "test-skill"}),
            _call_tool("run_skill_script", {"skill_name": "test-skill", "script_name": "scripts/greet.py"}),
            _text("ran it"),
        ),
    )
    pending = agent.run_sync("hi", deps="kb")
    assert isinstance(pending.output, DeferredToolRequests)

    resumed = agent.run_sync(
        deps="kb",
        message_history=pending.all_messages(),
        deferred_tool_results=pending.output.build_results(approve_all=True),
    )
    assert resumed.output == "ran it"


def test_scripts_free_runs_without_approval():
    """scripts='free' runs run_skill_script without pausing for approval"""
    agent = _build_test_agent(
        _role(skills=["test-skill"], scripts="free"),
        [FIXTURE_SKILLS_DIR],
        _scripted_model(
            _call_tool("load_capability", {"id": "test-skill"}),
            _call_tool("run_skill_script", {"skill_name": "test-skill", "script_name": "scripts/greet.py"}),
            _text("ran it"),
        ),
    )
    result = agent.run_sync("hi", deps="kb")
    assert result.output == "ran it"


# -- a role only sees its own declared skills --------------------------------


def test_role_cannot_load_a_skill_it_does_not_declare():
    """A role's agent cannot load_capability a skill outside its own Role.skills"""
    agent = _build_test_agent(
        _role(skills=["test-skill"]),  # does not declare "other-skill"
        [FIXTURE_SKILLS_DIR],
        _scripted_model(
            _call_tool("load_capability", {"id": "other-skill"}),
            _text("could not load it"),
        ),
    )
    result = agent.run_sync("hi", deps="kb")
    assert result.output == "could not load it"
    retry_parts = [p for m in result.all_messages() for p in m.parts if isinstance(p, RetryPromptPart)]
    assert retry_parts, "expected a RetryPromptPart when loading an undeclared skill"


def test_role_cannot_read_a_skill_it_has_not_loaded():
    """read_skill_resource refuses a skill this role's agent never loaded, even if it exists on disk"""
    agent = _build_test_agent(
        _role(skills=["test-skill"]),
        [FIXTURE_SKILLS_DIR],
        _scripted_model(
            _call_tool("read_skill_resource", {"skill_name": "other-skill", "resource_name": "references/notes.md"}),
            _text("could not read it"),
        ),
    )
    result = agent.run_sync("hi", deps="kb")
    assert result.output == "could not read it"
    retry_parts = [p for m in result.all_messages() for p in m.parts if isinstance(p, RetryPromptPart)]
    assert retry_parts, "expected a RetryPromptPart when reading an unloaded skill"


# -- ProductSquad wiring: skills_dirs is opt-in ------------------------------


def test_product_squad_without_skills_dirs_needs_no_skills_extra(tmp_path):
    """ProductSquad(skills_dirs=None), the default, never touches pydantic_ai_skills"""
    kb = MarkdownKnowledgeBase(tmp_path)
    squad = ProductSquad(kb, model=_scripted_model(_text("hi")), context=TEST_CONTEXT)
    assert squad.chat("hello") == "hi"


def _opinion_draft():
    """A model turn returning an OpinionDraft through whichever output tool the agent offers."""

    def turn(messages, info):
        args = {"recommendation": "Rank by impact", "confidence": "medium"}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    return turn


def _growth_pm_retries(tmp_path, skill: str) -> list[RetryPromptPart]:
    """Have the squad's Growth PM try to load `skill`, and return the retry prompts it got back."""
    squad = ProductSquad(
        MarkdownKnowledgeBase(tmp_path),
        model=_scripted_model(_call_tool("load_capability", {"id": skill}), _opinion_draft()),
        context=TEST_CONTEXT,
        skills_dirs=[],
    )
    result = squad._pms["growth_pm"].run_sync("Give your opinion", deps=squad.kb)
    return [p for m in result.all_messages() for p in m.parts if isinstance(p, RetryPromptPart)]


def test_product_squad_growth_pm_can_load_its_own_skill(tmp_path):
    """With skills_dirs set, the Growth PM can load the library's prioritization skill"""
    assert _growth_pm_retries(tmp_path, "prioritization") == []


def test_product_squad_growth_pm_cannot_load_hx_skill(tmp_path):
    """The Growth PM's agent cannot load HX's evidence-classification skill"""
    assert _growth_pm_retries(tmp_path, "evidence-classification")


def test_facilitator_has_no_skills_to_load(tmp_path):
    """The Facilitator declares no skill, so with skills on it is offered no way to load one"""
    kb = MarkdownKnowledgeBase(tmp_path)
    offered = {}

    def fn(messages, info):
        offered["tools"] = [t.name for t in info.function_tools]
        return ModelResponse(parts=[TextPart("hi")])

    squad = ProductSquad(kb, model=FunctionModel(fn), context=TEST_CONTEXT, skills_dirs=[])
    squad.chat("hello")
    assert "load_capability" not in offered["tools"]


def test_product_squad_consumer_skills_dir_supplements_library(tmp_path):
    """A consumer-supplied skills directory adds to, not replaces, the library's own"""
    kb = MarkdownKnowledgeBase(tmp_path)
    role = GROWTH_PM.model_copy(update={"skills": ["prioritization", "test-skill"]})
    capability, _ = build_role_skills(role, [LIBRARY_SKILLS_DIR, FIXTURE_SKILLS_DIR])
    assert capability.skill_names == ["prioritization", "test-skill"]
