from pydantic_squads import HUMAN, InteractionMode, Role


def make_role(id: str, mode: InteractionMode = InteractionMode.TASK, talks_to: list[str] | None = None) -> Role:
    return Role(
        id=id,
        name=id.title(),
        mission="Test mission",
        responsibilities=["Do the thing"],
        out_of_scope=["Everything else"],
        mode=mode,
        talks_to=talks_to or [HUMAN],
        delivers="A result",
    )


def lead(talks_to: list[str] | None = None) -> Role:
    return make_role("lead", InteractionMode.CONVERSATIONAL, [HUMAN, *(talks_to or [])])


def worker(id: str = "worker") -> Role:
    return make_role(id, InteractionMode.TASK, ["lead"])


def write_skill(root, location: str, name: str = "", description: str = "A test skill.", body: str = "Do the thing."):
    """Write a skill folder at `root/location`, named `name` (its folder's name by default), and return it."""
    folder = root / location
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name or folder.name}\ndescription: {description}\n---\n\n{body}\n", encoding="utf-8"
    )
    return folder


#: A skill script that echoes its arguments, or misbehaves on request.
FAKE_SCRIPT = """\
import json, os, sys, time

args = sys.argv[1:]
if "--sleep" in args:
    time.sleep(5)
if "--fail" in args:
    sys.stderr.write("boom\\n")
    sys.exit(3)
if "--big" in args:
    print("x" * 30000)
elif "--quiet" not in args:
    print(json.dumps({"argv": args, "cwd": os.getcwd()}))
"""


def write_script(skill_folder, name: str = "scripts/echo.py"):
    """Write `FAKE_SCRIPT` into a skill folder and return its path."""
    script = skill_folder / name
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(FAKE_SCRIPT, encoding="utf-8")
    return script
