import subprocess

import pytest

from pydantic_squads.product.skills_install import install_skills, license_line, repository


def _record_git(monkeypatch, error: Exception | None = None) -> list[list[str]]:
    """Replace git with a recorder, so no test ever touches the network."""
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        if error is not None:
            raise error

    monkeypatch.setattr("subprocess.run", run)
    return calls


def test_repository_accepts_a_github_shorthand_and_an_https_url():
    """A repository is a GitHub owner/name or an https:// URL, cloned into a folder named after it"""
    assert repository("phuryn/pm-skills") == ("https://github.com/phuryn/pm-skills.git", "pm-skills")
    assert repository("https://example.com/team/skills.git") == ("https://example.com/team/skills.git", "skills")


@pytest.mark.parametrize(
    "repo",
    ["--upload-pack=evil", "git@github.com:a/b.git", "file:///etc", "https://example.com/a/.."],
    ids=["an option", "ssh", "a local file", "no repository name"],
)
def test_repository_rejects_anything_else(repo):
    """What is not an owner/name or an https:// URL is refused before git ever runs"""
    with pytest.raises(ValueError):
        repository(repo)


def test_install_skills_clones_into_the_skills_home(tmp_path, monkeypatch):
    """install_skills shallow-clones the repository into <home>/<name>"""
    calls = _record_git(monkeypatch)
    target = install_skills("phuryn/pm-skills", tmp_path / "home")
    assert target == tmp_path / "home" / "pm-skills" and (tmp_path / "home").is_dir()
    assert calls == [["git", "clone", "--depth", "1", "--", "https://github.com/phuryn/pm-skills.git", str(target)]]


def test_install_skills_refuses_to_overwrite_an_installed_repository(tmp_path, monkeypatch):
    """A repository already installed is left alone unless update is asked for"""
    calls = _record_git(monkeypatch)
    (tmp_path / "pm-skills").mkdir()
    with pytest.raises(FileExistsError, match="--update"):
        install_skills("phuryn/pm-skills", tmp_path)
    assert calls == []


def test_install_skills_fast_forwards_on_update(tmp_path, monkeypatch):
    """With update, an installed repository is fast-forwarded in place"""
    calls = _record_git(monkeypatch)
    (tmp_path / "pm-skills").mkdir()
    install_skills("phuryn/pm-skills", tmp_path, update=True)
    assert calls == [["git", "-C", str(tmp_path / "pm-skills"), "pull", "--ff-only"]]


def test_install_skills_reports_a_missing_git(tmp_path, monkeypatch):
    """Without git installed, the error says so"""
    _record_git(monkeypatch, FileNotFoundError())
    with pytest.raises(ValueError, match="git was not found"):
        install_skills("phuryn/pm-skills", tmp_path)


def test_install_skills_reports_a_failed_clone(tmp_path, monkeypatch):
    """A clone git refuses is reported with git's own message"""
    _record_git(monkeypatch, subprocess.CalledProcessError(128, "git", stderr="repository not found\n"))
    with pytest.raises(ValueError, match="git failed: repository not found"):
        install_skills("phuryn/pm-skills", tmp_path)


def test_license_line_reads_the_first_line_of_the_license_file(tmp_path):
    """license_line gives the license's first non-empty line, or None when there is no license file"""
    assert license_line(tmp_path) is None
    (tmp_path / "LICENSES").mkdir()
    assert license_line(tmp_path) is None
    (tmp_path / "LICENSE.md").write_text("\nMIT License\n\nCopyright (c) someone\n")
    assert license_line(tmp_path) == "MIT License"
