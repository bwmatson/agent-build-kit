"""Builders the spec_driven tests share.

Nine test files each had their own `unit()` and seven their own `git()`, and
the copies had drifted in their defaults without any test depending on the
difference. A file that does need a different default says so where it
imports these, rather than in a tenth near-copy.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.shell import git_out as git
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import Unit

__all__ = ["git", "init_repo", "stored_unit", "unit"]

_DEFAULTS: dict[str, Any] = {
    "change": "add-marker",
    "title": "Register the marker",
    "repo": "app",
    "tier": "tier1",
    "depends_on": (),
    "estimated_lines": 140,
    "groups": (1,),
}


def unit(uid: str = "add-marker/1", **overrides) -> Unit:
    fields: dict[str, Any] = {**_DEFAULTS, "id": uid, **overrides}
    return Unit(**fields)


def stored_unit(uid: str = "add-marker/1", **overrides) -> StoredUnit:
    fields: dict[str, Any] = {**_DEFAULTS, "id": uid, **overrides}
    return StoredUnit(**fields)


def init_repo(path: Path) -> Path:
    """An empty repo on `main` with a local identity, so commits work under CI."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@t.t")
    git(path, "config", "user.name", "t")
    return path


def scratch_app(path: Path) -> Path:
    """A python-uv app whose tier 1 can run: pytest and pre-commit in the dev
    group, and a pre-commit config that needs no network. One initial commit
    on `main`, which ignores bytecode and the virtualenv so a unit's commits
    hold only the unit's work."""
    init_repo(path)
    (path / ".gitignore").write_text("__pycache__/\n*.pyc\n.venv/\n")
    (path / "pyproject.toml").write_text(
        '[project]\nname = "app"\nversion = "0"\nrequires-python = ">=3.12"\n'
        '[dependency-groups]\ndev = ["pytest", "pre-commit"]\n'
        '[tool.pytest.ini_options]\npythonpath = ["src"]\n'
    )
    (path / ".pre-commit-config.yaml").write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: no-conflict-markers\n"
        "        name: no conflict markers\n"
        "        language: system\n"
        "        entry: 'true'\n"
        "        pass_filenames: false\n"
    )
    (path / "src" / "app").mkdir(parents=True)
    (path / "src" / "app" / "__init__.py").write_text("")
    (path / "tests").mkdir()
    (path / "tests" / ".gitkeep").write_text("")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "start")
    return path


def activate_with(**sections):
    """Activate a copy of the active workspace with these top-level sections
    replaced (e.g. git={"push_host": "github-example"})."""
    from agent_build_kit import config as config_module

    current = config_module.active()
    updated = current.model_copy(
        update={
            name: type(getattr(current, name)).model_validate(value)
            for name, value in sections.items()
        }
    )
    config_module.activate(updated, config_module.active_root())
    return updated


def who_pushed(remote: Path, branch: str, pushes: list[str]) -> str:
    """A diagnostic: the branch's reflog on a remote, then the pushes a run log
    records. It never raises: a branch with no reflog, or none at all, is a
    normal case and is shown as what git said."""
    shown = subprocess.run(
        ["git", "reflog", "show", f"refs/heads/{branch}"],
        cwd=remote,
        capture_output=True,
        text=True,
    )
    reflog = shown.stdout if shown.returncode == 0 else shown.stderr
    return (
        f"--- remote reflog of {branch} ---\n{reflog.strip()}\n"
        "--- every `git push` the run log records ---\n" + "\n".join(pushes)
    )
