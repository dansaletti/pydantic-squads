import pytest

pytest.importorskip("yaml", reason="requires the 'skills' extra: uv sync --extra skills")

from helpers import write_skill

from pydantic_squads.product.skill_registry import SkillRegistry, parse_skill_file


def test_parse_skill_file_reads_name_and_description_from_the_frontmatter():
    """parse_skill_file returns the YAML frontmatter and the instructions under it"""
    frontmatter, body = parse_skill_file("---\nname: journey-map\ndescription: Maps a journey.\n---\n\n# Steps\nGo.\n")
    assert frontmatter == {"name": "journey-map", "description": "Maps a journey."}
    assert body == "# Steps\nGo."


@pytest.mark.parametrize(
    "text",
    ["", "# No frontmatter", "---\nname: never-closed\n", "---\nname: [broken\n---\nbody", "---\n- a list\n---\nbody"],
    ids=["empty", "no frontmatter", "not closed", "invalid YAML", "not a mapping"],
)
def test_parse_skill_file_without_usable_frontmatter_returns_the_text(text):
    """A SKILL.md with no frontmatter, or one that is not a YAML mapping, parses to no frontmatter at all"""
    assert parse_skill_file(text) == ({}, text)


def test_registry_discovers_skills_however_deep(tmp_path):
    """The registry finds every SKILL.md under its paths, nested and under hidden folders alike"""
    write_skill(tmp_path, "pack/skills/journey-map")
    write_skill(tmp_path, ".hidden/skills/foundation")
    registry = SkillRegistry([tmp_path])
    assert [(s.name, s.location) for s in registry.skills] == [
        ("foundation", ".hidden/skills/foundation"),
        ("journey-map", "pack/skills/journey-map"),
    ]


def test_registry_takes_the_skill_name_from_the_frontmatter_not_the_folder(tmp_path):
    """A skill is named by its frontmatter, even in a folder called something else"""
    folder = write_skill(tmp_path, "taste", name="design-taste", description="Visual direction.")
    (skill,) = SkillRegistry([tmp_path]).skills
    assert (skill.name, skill.description, skill.path) == ("design-taste", "Visual direction.", folder.resolve())


def test_skill_body_is_read_from_disk_on_demand(tmp_path):
    """Skill.body reads the instructions when asked, so a later edit shows up"""
    folder = write_skill(tmp_path, "journey-map", body="First version.")
    (skill,) = SkillRegistry([tmp_path]).skills
    assert skill.body == "First version."
    write_skill(tmp_path, "journey-map", body="Second version.")
    assert skill.body == "Second version." and folder.is_dir()


def test_registry_skips_git_folders_and_a_skills_own_subfolders(tmp_path):
    """Neither .git nor the folders inside a skill are searched for more skills"""
    write_skill(tmp_path, ".git/hooks/ghost")
    write_skill(tmp_path, "journey-map/references/nested")
    write_skill(tmp_path, "journey-map")
    assert [s.name for s in SkillRegistry([tmp_path]).skills] == ["journey-map"]


def test_registry_skips_a_skill_file_without_a_usable_name_and_description(tmp_path):
    """A SKILL.md with no name, an unusable name or no description is listed as skipped, not loaded"""
    (tmp_path / "bare").mkdir()
    (tmp_path / "bare" / "SKILL.md").write_text("# Just prose")
    write_skill(tmp_path, "slash", name="a/b")
    (tmp_path / "mute").mkdir()
    (tmp_path / "mute" / "SKILL.md").write_text("---\nname: mute\n---\nbody")
    write_skill(tmp_path, "fine")
    registry = SkillRegistry([tmp_path])
    assert [s.name for s in registry.skills] == ["fine"]
    assert sorted(p.parent.name for p in registry.skipped) == ["bare", "mute", "slash"]


def test_registry_rejects_a_path_that_is_not_a_directory(tmp_path):
    """A configured skills path that does not exist fails clearly"""
    with pytest.raises(ValueError, match="not a directory"):
        SkillRegistry([tmp_path / "missing"])


def test_select_picks_by_name_and_by_location_glob(tmp_path):
    """A pattern picks a skill by its name, or every skill under a folder by a glob on its location"""
    write_skill(tmp_path, "discovery/skills/tree")
    write_skill(tmp_path, "discovery/skills/interview")
    write_skill(tmp_path, "research/skills/journey-map")
    registry = SkillRegistry([tmp_path])
    assert [s.name for s in registry.select(["discovery/*"])] == ["interview", "tree"]
    assert [s.name for s in registry.select(["journey-map", "tree"])] == ["journey-map", "tree"]


def test_select_takes_back_what_a_negated_pattern_matches(tmp_path):
    """A pattern starting with ! removes its matches from what was picked"""
    write_skill(tmp_path, "discovery/skills/tree")
    write_skill(tmp_path, "discovery/skills/interview")
    registry = SkillRegistry([tmp_path])
    assert [s.name for s in registry.select(["discovery/*", "!interview"])] == ["tree"]
    assert registry.select(["!interview"]) == []


def test_select_rejects_a_pattern_matching_nothing(tmp_path):
    """A pattern that matches no skill fails, naming the skills that exist"""
    write_skill(tmp_path, "tree")
    with pytest.raises(ValueError, match="no skill matches 'nope'. Found: tree"):
        SkillRegistry([tmp_path]).select(["nope"])
    with pytest.raises(ValueError, match="Found: none"):
        SkillRegistry([]).select(["nope"])


def test_select_rejects_one_name_picked_from_two_folders(tmp_path):
    """The same skill name in two folders is ambiguous until one is picked by location or left out"""
    write_skill(tmp_path, "a/design")
    write_skill(tmp_path, "b/design")
    registry = SkillRegistry([tmp_path])
    with pytest.raises(ValueError, match="skill 'design' is in two places"):
        registry.select(["design"])
    assert [s.location for s in registry.select(["a/design"])] == ["a/design"]
    assert [s.location for s in registry.select(["design", "!a/*"])] == ["b/design"]


def _write_command(root, location: str, description: str = "Run a full discovery cycle.", body: str = "Apply the **tree** skill."):
    file = root / location
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(f"---\ndescription: {description}\n---\n\n{body}\n", encoding="utf-8")
    return file


def test_registry_lists_command_files_outside_skills(tmp_path):
    """A Markdown file with a description in its frontmatter, outside any skill, is a command named after the file"""
    file = _write_command(tmp_path, "pm/commands/discover.md")
    (tmp_path / "pm" / "README.md").write_text("# No frontmatter here")
    _write_command(tmp_path, "pm/commands/not a name.md")
    skill = write_skill(tmp_path, "pm/skills/tree")
    _write_command(skill, "references/inside-a-skill.md")
    (command,) = SkillRegistry([tmp_path]).commands
    assert (command.name, command.description, command.location) == (
        "discover",
        "Run a full discovery cycle.",
        "pm/commands/discover.md",
    )
    assert command.body == "Apply the **tree** skill." and command.path == file.resolve()


def test_select_commands_picks_by_name_and_by_location_glob(tmp_path):
    """Commands are picked with the same patterns as skills"""
    _write_command(tmp_path, "pm/commands/discover.md")
    _write_command(tmp_path, "pm/commands/interview.md")
    _write_command(tmp_path, "other/commands/discover.md")
    registry = SkillRegistry([tmp_path])
    assert [c.name for c in registry.select_commands(["pm/commands/*"])] == ["discover", "interview"]
    assert [c.name for c in registry.select_commands(["pm/commands/*", "!interview"])] == ["discover"]
    with pytest.raises(ValueError, match="command 'discover' is in two places"):
        registry.select_commands(["discover"])
    with pytest.raises(ValueError, match="no command matches 'nope'. Found: discover, interview"):
        registry.select_commands(["nope"])
