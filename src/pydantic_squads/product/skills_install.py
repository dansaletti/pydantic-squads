"""Clones a skills repository into a local folder (`pydantic-squads skills install`).

Third-party skills are never versioned in this repository (ADR 0019): a
project installs the ones it uses and points its skills config at them.
Standard library only.
"""

import re
import subprocess
from pathlib import Path

#: Where `pydantic-squads skills install` puts a repository unless told otherwise.
DEFAULT_SKILLS_HOME = Path("~/.squads/skills")

_SHORTHAND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")
_HTTPS = re.compile(r"^https://[A-Za-z0-9.-]+/[A-Za-z0-9._/-]+$")


def repository(repo: str) -> tuple[str, str]:
    """The clone URL and the folder name for `repo`.

    `repo` is a GitHub `owner/name` or an `https://` URL.

    Raises:
        ValueError: If `repo` is neither.
    """
    if _SHORTHAND.match(repo):
        url = f"https://github.com/{repo}.git"
    elif _HTTPS.match(repo):
        url = repo
    else:
        raise ValueError(f"'{repo}' is not a GitHub owner/name or an https:// URL")
    name = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    if name in ("", ".", ".."):
        raise ValueError(f"'{repo}' does not name a repository")
    return url, name


def install_skills(repo: str, home: Path | str = DEFAULT_SKILLS_HOME, *, update: bool = False) -> Path:
    """Clone `repo` under `home` and return the folder it landed in.

    With `update`, a repository already there is fast-forwarded instead.

    Raises:
        ValueError: If `repo` is not a repository, or git fails.
        FileExistsError: If it is already installed and `update` is off.
    """
    url, name = repository(repo)
    home = Path(home).expanduser()
    target = home / name
    if target.exists():
        if not update:
            raise FileExistsError(f"{target} already exists: pass --update to fast-forward it")
        command = ["git", "-C", str(target), "pull", "--ff-only"]
    else:
        home.mkdir(parents=True, exist_ok=True)
        command = ["git", "clone", "--depth", "1", "--", url, str(target)]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)  # an argument list: no shell
    except FileNotFoundError as error:
        raise ValueError("git was not found: install it to install skills") from error
    except subprocess.CalledProcessError as error:
        raise ValueError(f"git failed: {error.stderr.strip()}") from error
    return target


def license_line(folder: Path) -> str | None:
    """The first line of `folder`'s license file, or `None` when it has none."""
    for candidate in sorted(folder.glob("LICENSE*")):
        if candidate.is_file():
            lines = [line.strip() for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines()]
            return next((line for line in lines if line), None)
    return None
