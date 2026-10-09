import json
import os

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import pytest

pytest.importorskip("pydantic_ai", reason="requires the 'ai' extra: uv sync --extra ai")
pytest.importorskip("pydantic_ai_skills", reason="requires the 'skills' extra: uv sync --extra skills")

from helpers import write_script, write_skill
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, RetryPromptPart, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from pydantic_squads.product.assembly import ProductSquad
from pydantic_squads.product.knowledge import MarkdownKnowledgeBase
from pydantic_squads.product.skills_config import SkillsConfig
from pydantic_squads.product.skills_integration import SquadSkills
from pydantic_squads.product.squad import build_product_squad

SEARCH = {
    "name": "design_search",
    "roles": ["designer"],
    "skill": "foundation",
    "script": "scripts/echo.py",
    "description": "Search the design data.",
    "params": [{"name": "query", "required": True}],
    "approval": False,
}
PERSIST = {**SEARCH, "name": "persist_design_system", "fixed_args": ["--persist"], "approval": True}


def _installed(tmp_path):
    """A folder of installed third-party skills, laid out the awkward ways real repositories are."""
    root = tmp_path / "installed"
    write_skill(root, "pm/discovery/skills/tree", description="Builds an opportunity tree.")
    journey = write_skill(root, "pm/research/skills/journey-map", description="Maps a customer journey.")
    (journey / "references").mkdir(exist_ok=True)
    (journey / "references" / "template.md").write_text("# Journey template")
    (root / "secret.md").write_text("not part of any skill")
    write_script(write_skill(root, "ui/.hidden/skills/foundation", description="Tokens and palettes."))
    write_skill(root, "taste/skills/taste-skill", name="design-taste", description="Visual direction.")
    (root / "pm/discovery/commands").mkdir(exist_ok=True)
    (root / "pm/discovery/commands/discover.md").write_text(
        "---\ndescription: Run a full discovery cycle.\n---\n\n# /discover\n\nApply the **tree** skill, then **journey-map**.\n"
    )
    return root


def _config(tmp_path, **overrides) -> SkillsConfig:
    values = {
        "paths": [_installed(tmp_path)],
        "roles": {"pm_product": ["pm/*"], "designer": ["foundation", "design-taste"]},
        "rules": {"pm_product": ["Use skills as method, never as a source of facts."]},
    }
    return SkillsConfig(**{**values, **overrides})


def _call(name: str, args: dict):
    return lambda messages, info: ModelResponse(parts=[ToolCallPart(name, args)])


def _say(text: str):
    return lambda messages, info: ModelResponse(parts=[TextPart(text)])


def _scripted(*turns, seen: dict | None = None) -> FunctionModel:
    """A FunctionModel playing `turns` in order, recording what the first request offered."""
    state = {"n": 0}

    def fn(messages, info):
        if seen is not None and not seen:
            seen["instructions"] = info.instructions or ""
            seen["tools"] = sorted(t.name for t in info.function_tools)
        turn = turns[state["n"]]
        state["n"] += 1
        return turn(messages, info)

    return FunctionModel(fn)


def _agent(skills: SquadSkills, role_id: str, model) -> Agent:
    """A bare agent holding just what `role_id` gets from the squad's skills."""
    return Agent(model, output_type=[str, DeferredToolRequests], **skills.kwargs_for(skills.squad[role_id]))


def _parts(result, kind):
    return [p for m in result.all_messages() for p in m.parts if isinstance(p, kind)]


# -- the role mapping ---------------------------------------------------------


def test_project_skills_add_to_the_roles_own(tmp_path):
    """A role keeps the library's skills and gains the ones the project picked for it"""
    squad = SquadSkills(build_product_squad(), [], _config(tmp_path)).squad
    assert squad["pm_product"].skills == ["story-mapping", "journey-map", "tree"]
    assert squad["designer"].skills == ["prototyping", "impeccable", "design-taste", "foundation"]
    assert squad["hx"].skills == ["evidence-classification"]


def test_project_rules_become_the_roles_principles(tmp_path):
    """The rules a project writes for a role are rendered in that role's instructions only"""
    squad = SquadSkills(build_product_squad(), [], _config(tmp_path)).squad
    rule = "Use skills as method, never as a source of facts."
    assert rule in squad.instructions_for("pm_product")
    assert rule not in squad.instructions_for("designer")


def test_each_agents_prompt_lists_only_its_own_roles_skills(tmp_path):
    """An agent is told the name and description of its role's skills, and of no other role's"""
    skills = SquadSkills(build_product_squad(), [], _config(tmp_path))
    seen: dict = {}
    _agent(skills, "pm_product", _scripted(_say("ok"), seen=seen)).run_sync("hi")
    assert "- tree: Builds an opportunity tree." in seen["instructions"]
    assert "- journey-map: Maps a customer journey." in seen["instructions"]
    assert "foundation" not in seen["instructions"] and "design-taste" not in seen["instructions"]

    seen = {}
    _agent(skills, "designer", _scripted(_say("ok"), seen=seen)).run_sync("hi")
    assert "- design-taste: Visual direction." in seen["instructions"]
    assert "journey-map" not in seen["instructions"] and "tree" not in seen["instructions"]


def test_a_skills_body_stays_out_of_the_prompt_until_it_is_loaded(tmp_path):
    """Only a skill's name and description are in the prompt; its instructions arrive with load_capability"""
    config = _config(tmp_path)
    write_skill(config.paths[0], "pm/discovery/skills/tree", description="Builds an opportunity tree.", body="STEP-ONE-MARKER")
    skills = SquadSkills(build_product_squad(), [], config)
    seen: dict = {}
    model = _scripted(_call("load_capability", {"id": "tree"}), _say("loaded"), seen=seen)
    result = _agent(skills, "pm_product", model).run_sync("hi")
    assert "STEP-ONE-MARKER" not in seen["instructions"]
    assert "STEP-ONE-MARKER" in str(_parts(result, ToolReturnPart)[0].content)


@pytest.mark.parametrize("name", ["no-such-skill", "foundation"], ids=["unknown", "another role's"])
def test_loading_a_skill_that_does_not_exist_is_refused(tmp_path, name):
    """load_capability with an unknown name, or another role's skill, comes back as a retry, not a crash"""
    skills = SquadSkills(build_product_squad(), [], _config(tmp_path))
    result = _agent(skills, "pm_product", _scripted(_call("load_capability", {"id": name}), _say("gave up"))).run_sync("hi")
    assert result.output == "gave up"
    assert f"No capability found with id '{name}'" in str(_parts(result, RetryPromptPart)[0].content)


def test_a_skill_named_differently_from_its_folder_still_loads(tmp_path):
    """A skill whose frontmatter name is not its folder's name loads under the frontmatter name"""
    skills = SquadSkills(build_product_squad(), [], _config(tmp_path))
    result = _agent(skills, "designer", _scripted(_call("load_capability", {"id": "design-taste"}), _say("ok"))).run_sync("hi")
    assert _parts(result, RetryPromptPart) == []


def test_reading_a_skills_own_file_works(tmp_path):
    """read_skill_resource reads a file bundled inside the skill's folder"""
    skills = SquadSkills(build_product_squad(), [], _config(tmp_path))
    model = _scripted(
        _call("load_capability", {"id": "journey-map"}),
        _call("read_skill_resource", {"skill_name": "journey-map", "resource_name": "references/template.md"}),
        _say("read"),
    )
    result = _agent(skills, "pm_product", model).run_sync("hi")
    assert "# Journey template" in str(_parts(result, ToolReturnPart)[-1].content)


@pytest.mark.parametrize(
    "path", ["../../../../secret.md", "references/../../../../../secret.md", "/etc/hosts"], ids=["parent", "nested", "absolute"]
)
def test_reading_outside_the_skills_folder_is_blocked(tmp_path, path):
    """read_skill_resource never leaves the skill's folder: a traversing or absolute path is refused"""
    skills = SquadSkills(build_product_squad(), [], _config(tmp_path))
    model = _scripted(
        _call("load_capability", {"id": "journey-map"}),
        _call("read_skill_resource", {"skill_name": "journey-map", "resource_name": path}),
        _say("blocked"),
    )
    result = _agent(skills, "pm_product", model).run_sync("hi")
    assert result.output == "blocked"
    assert "not found in skill 'journey-map'" in str(_parts(result, RetryPromptPart)[0].content)
    assert all("not part of any skill" not in str(p.content) for p in _parts(result, ToolReturnPart))


# -- commands: a repository's own workflows -----------------------------------


def test_a_command_reaches_its_role_as_a_skill_holding_the_workflow(tmp_path):
    """A command picked for a role is listed like a skill, and loading it gives the workflow with a note on how to follow it"""
    config = _config(tmp_path, commands={"pm_product": ["pm/discovery/commands/*"]})
    skills = SquadSkills(build_product_squad(), [], config)
    assert skills.squad["pm_product"].skills == ["story-mapping", "journey-map", "tree", "discover"]
    seen: dict = {}
    model = _scripted(_call("load_capability", {"id": "discover"}), _say("ok"), seen=seen)
    result = _agent(skills, "pm_product", model).run_sync("hi")
    assert "- discover: Run a full discovery cycle." in seen["instructions"]
    loaded = str(_parts(result, ToolReturnPart)[0].content)
    assert "Apply the **tree** skill, then **journey-map**." in loaded and "There are no slash commands here" in loaded


def test_a_command_follows_the_file_on_disk(tmp_path):
    """A squad built after the repository changed gets the command's new text, with nothing else to edit"""
    config = _config(tmp_path, commands={"pm_product": ["discover"]})
    (config.paths[0] / "pm/discovery/commands/discover.md").write_text(
        "---\ndescription: Run a full discovery cycle.\n---\n\nApply **journey-map** first now.\n"
    )
    skills = SquadSkills(build_product_squad(), [], config)
    result = _agent(skills, "pm_product", _scripted(_call("load_capability", {"id": "discover"}), _say("ok"))).run_sync("hi")
    assert "Apply **journey-map** first now." in str(_parts(result, ToolReturnPart)[0].content)


def test_a_role_can_have_commands_and_no_project_skill(tmp_path):
    """A role given only a command still gets it"""
    skills = SquadSkills(build_product_squad(), [], _config(tmp_path, roles={}, commands={"growth_pm": ["discover"]}))
    seen: dict = {}
    _agent(skills, "growth_pm", _scripted(_say("ok"), seen=seen)).run_sync("hi")
    assert "- discover: Run a full discovery cycle." in seen["instructions"]


def test_a_command_named_like_one_of_the_roles_skills_is_rejected(tmp_path):
    """A command cannot take the name of a skill the role already has"""
    root = _installed(tmp_path)
    (root / "pm/discovery/commands/tree.md").write_text("---\ndescription: Clashes.\n---\nbody\n")
    with pytest.raises(ValueError, match=r"role 'pm_product': commands named like a skill it already has: \['tree'\]"):
        SquadSkills(build_product_squad(), [], _config(tmp_path, commands={"pm_product": ["pm/discovery/commands/*"]}))


def test_a_pattern_matching_no_command_names_the_role(tmp_path):
    """A commands pattern matching nothing fails, naming the role it was written for"""
    with pytest.raises(ValueError, match="role 'hx': no command matches 'nope'"):
        SquadSkills(build_product_squad(), [], _config(tmp_path, commands={"hx": ["nope"]}))


# -- typed skill tools --------------------------------------------------------


def test_a_declared_skill_tool_reaches_only_its_role(tmp_path):
    """A skill tool is offered to the roles it names, and to no other"""
    skills = SquadSkills(build_product_squad(), [], _config(tmp_path, tools=[SEARCH]))
    designer, pm = {}, {}
    _agent(skills, "designer", _scripted(_say("ok"), seen=designer)).run_sync("hi")
    _agent(skills, "pm_product", _scripted(_say("ok"), seen=pm)).run_sync("hi")
    assert "design_search" in designer["tools"] and "design_search" not in pm["tools"]


def test_a_project_skills_scripts_run_only_as_declared_tools(tmp_path):
    """run_skill_script cannot reach a project skill's scripts: only the declared tool runs them"""
    skills = SquadSkills(build_product_squad(), [], _config(tmp_path, tools=[SEARCH]))
    model = _scripted(
        _call("load_capability", {"id": "foundation"}),
        _call("run_skill_script", {"skill_name": "foundation", "script_name": "scripts/echo.py"}),
    )
    result = _agent(skills, "designer", model).run_sync("hi")
    assert isinstance(result.output, DeferredToolRequests)
    resumed_model = _scripted(_say("no script"))
    resumed = _agent(skills, "designer", resumed_model).run_sync(
        message_history=result.all_messages(), deferred_tool_results=result.output.build_results(approve_all=True)
    )
    assert "Script 'scripts/echo.py' not found in skill 'foundation'. Available: []" in str(
        _parts(resumed, RetryPromptPart)[0].content
    )


def test_a_skill_tool_without_approval_runs_at_once(tmp_path):
    """A tool declared with approval off runs its script and returns the output to the model"""
    skills = SquadSkills(build_product_squad(), [], _config(tmp_path, tools=[SEARCH]))
    result = _agent(skills, "designer", _scripted(_call("design_search", {"query": "spa"}), _say("done"))).run_sync("hi")
    assert json.loads(_parts(result, ToolReturnPart)[0].content)["argv"] == ["spa"]


def test_invalid_skill_tool_arguments_come_back_to_the_model(tmp_path):
    """Arguments the tool's model rejects reach the model as a retry it can correct"""
    skills = SquadSkills(build_product_squad(), [], _config(tmp_path, tools=[SEARCH]))
    model = _scripted(_call("design_search", {"query": "--force"}), _call("design_search", {"query": "spa"}), _say("done"))
    result = _agent(skills, "designer", model).run_sync("hi")
    assert "invalid arguments for design_search" in str(_parts(result, RetryPromptPart)[0].content)
    assert result.output == "done"


def test_a_skill_tool_with_approval_pauses_then_runs(tmp_path):
    """A tool that needs approval defers to the human, and runs with its fixed arguments once approved"""
    skills = SquadSkills(build_product_squad(), [], _config(tmp_path, tools=[SEARCH, PERSIST]))
    assert skills.gated_roles == {"designer"}
    pending = _agent(skills, "designer", _scripted(_call("persist_design_system", {"query": "spa"}))).run_sync("hi")
    assert pending.output.approvals[0].tool_name == "persist_design_system"
    resumed = _agent(skills, "designer", _scripted(_say("saved"))).run_sync(
        message_history=pending.all_messages(), deferred_tool_results=pending.output.build_results(approve_all=True)
    )
    assert json.loads(_parts(resumed, ToolReturnPart)[0].content)["argv"] == ["--persist", "spa"]


def test_a_role_with_free_scripts_runs_an_approval_tool_without_pausing(tmp_path):
    """Role.scripts='free' lifts the approval a tool asks for"""
    squad = build_product_squad()
    roles = [r.model_copy(update={"scripts": "free"}) if r.id == "designer" else r for r in squad.roles]
    skills = SquadSkills(squad.model_copy(update={"roles": roles}), [], _config(tmp_path, tools=[PERSIST]))
    assert skills.gated_roles == set()
    model = _scripted(_call("persist_design_system", {"query": "spa"}), _say("saved"))
    assert _agent(skills, "designer", model).run_sync("hi").output == "saved"


# -- a config that cannot work fails when the squad is built -----------------


def test_config_naming_an_unknown_role_is_rejected(tmp_path):
    """A skills config naming a role the squad does not have fails clearly"""
    with pytest.raises(ValueError, match=r"roles the squad does not have: \['orchestrator'\]"):
        SquadSkills(build_product_squad(), [], _config(tmp_path, rules={"orchestrator": ["x"]}))


def test_config_picking_a_missing_skill_names_the_role(tmp_path):
    """A pattern matching no installed skill fails, naming the role it was written for"""
    with pytest.raises(ValueError, match="role 'hx': no skill matches 'nope'"):
        SquadSkills(build_product_squad(), [], _config(tmp_path, roles={"hx": ["nope"]}))


def test_tool_for_a_role_without_its_skill_is_rejected(tmp_path):
    """A tool can only be declared for a role the project gave its skill to"""
    with pytest.raises(ValueError, match="role 'pm_product' does not have the skill 'foundation'"):
        SquadSkills(build_product_squad(), [], _config(tmp_path, tools=[{**SEARCH, "roles": ["pm_product"]}]))


def test_tool_for_a_role_that_may_not_run_scripts_is_rejected(tmp_path):
    """Role.scripts='never' also forbids declared skill tools"""
    squad = build_product_squad()
    roles = [r.model_copy(update={"scripts": "never"}) if r.id == "designer" else r for r in squad.roles]
    with pytest.raises(ValueError, match="role 'designer' may not run skill scripts"):
        SquadSkills(squad.model_copy(update={"roles": roles}), [], _config(tmp_path, tools=[SEARCH]))


@pytest.mark.parametrize("name", ["write_note", "read_skill_resource"], ids=["a note tool", "a skill tool"])
def test_tool_named_like_one_the_role_already_has_is_rejected(tmp_path, name):
    """A declared tool cannot take the name of a tool the role already has"""
    with pytest.raises(ValueError, match="already has a tool of that name"):
        SquadSkills(build_product_squad(), [], _config(tmp_path, tools=[{**SEARCH, "name": name}]))


def test_squad_skills_without_a_config_leaves_the_squad_alone(tmp_path):
    """With no project config, the squad is unchanged and a role without skills gets nothing"""
    squad = build_product_squad()
    skills = SquadSkills(squad, [])
    assert skills.squad is squad and skills.kwargs_for(squad["facilitator"]) == {}


# -- ProductSquad -------------------------------------------------------------


def test_product_squad_gives_each_agent_its_project_skills_and_rules(tmp_path):
    """ProductSquad(skills=...) turns skills on: the Product PM sees its skills and rules, the Growth PM neither"""
    seen: dict = {}

    def fn(messages, info):
        seen.setdefault("prompts", []).append(
            (info.instructions or "") + " ".join(str(getattr(p, "content", "")) for m in messages for p in m.parts)
        )
        args = {"recommendation": "Map the journey first", "confidence": "medium"}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    (tmp_path / "vault").mkdir()
    squad = ProductSquad(
        MarkdownKnowledgeBase(tmp_path / "vault"), model=FunctionModel(fn), context="A cycle app.", skills=_config(tmp_path)
    )
    squad._pms["pm_product"].run_sync("Give your opinion", deps=squad.kb)
    squad._pms["growth_pm"].run_sync("Give your opinion", deps=squad.kb)
    product, growth = seen["prompts"]
    assert "- tree: Builds an opportunity tree." in product and "never as a source of facts" in product
    assert "- tree:" not in growth and "never as a source of facts" not in growth
    assert "- prioritization:" in growth  # the library's own skills are still there


def test_product_squad_designer_pauses_on_an_approval_tool(tmp_path):
    """The Designer's run stops for approval when it calls a skill tool that writes"""
    (tmp_path / "vault").mkdir()
    squad = ProductSquad(
        MarkdownKnowledgeBase(tmp_path / "vault"),
        model=_scripted(_call("persist_design_system", {"query": "spa"})),
        context="A cycle app.",
        skills=_config(tmp_path, tools=[SEARCH, PERSIST]),
    )
    result = squad._designer.run_sync("Design it", deps=squad.kb)
    assert result.output.approvals[0].tool_name == "persist_design_system"


def test_product_squad_rejects_an_approval_tool_on_a_role_that_cannot_pause(tmp_path):
    """A tool needing approval on a PM is refused: a PM's run has no way to stop for the human"""
    (tmp_path / "vault").mkdir()
    tool = {**PERSIST, "roles": ["pm_product"], "skill": "tree", "script": "scripts/echo.py"}
    write_script(_installed(tmp_path) / "pm/discovery/skills/tree")
    with pytest.raises(ValueError, match=r"cannot pause for it: \['pm_product'\]"):
        ProductSquad(
            MarkdownKnowledgeBase(tmp_path / "vault"),
            model=_scripted(),
            context="A cycle app.",
            skills=_config(tmp_path, tools=[tool]),
        )


def test_a_failing_skill_tool_does_not_loop_forever(tmp_path):
    """A script that keeps failing ends the run with an error instead of retrying without end"""
    skills = SquadSkills(build_product_squad(), [], _config(tmp_path, tools=[{**SEARCH, "fixed_args": ["--fail"]}]))
    model = _scripted(*[_call("design_search", {"query": "spa"})] * 5)
    with pytest.raises(UnexpectedModelBehavior, match="design_search"):
        _agent(skills, "designer", model).run_sync("hi")
