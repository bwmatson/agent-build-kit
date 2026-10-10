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
from agent_build_kit.pipeline.tier2 import Tier2Result, build_snapshot
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import Unit, ready_units

__all__ = [
    "follow_ups",
    "git",
    "init_repo",
    "new_unit",
    "output_of",
    "snapshot",
    "started_ids",
    "stored_unit",
    "unit",
]

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


def new_unit(uid: str, **overrides) -> StoredUnit:
    """A unit of the change named by the id's prefix, so each id is its own change."""
    return stored_unit(uid, change=uid.split("/")[0], **overrides)


def started_ids(graph, *, slots: int = 1, **kw) -> list[str]:
    """The ids `ready_units` starts from the graph, in the order it starts them."""
    return [u.id for u in ready_units(graph, max_concurrent=slots, depth_cap=9, **kw)]


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


def recognised_planning(path: Path) -> Path:
    """A planning directory with a manifest, so `abk init` recognises its environment
    and writes an abk.yaml that loads."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "pyproject.toml").write_text('[project]\nname = "planning"\n')
    return path


def output_of(size: int) -> str:
    """Distinct numbered lines ending in a recognisable tail, `size` characters."""
    lines: list[str] = []
    while sum(len(line) + 1 for line in lines) < size:
        lines.append(f"output line {len(lines):04d} " + "o" * 30)
    text = "\n".join(lines)[: size - 40]
    return text + "\n" + "TAIL FAILED tests/test_bar.py::test_bar".ljust(39)


def snapshot(output: str) -> str:
    return build_snapshot(
        Tier2Result(
            sha="abcdef0123",
            passed=3,
            failed=1,
            skipped=0,
            duration_seconds=1.5,
            command="uv run pytest -m local_stack",
            output=output,
        )
    )


def follow_ups(count: int) -> list[str]:
    return [f"follow-up {number:02d}: " + "f" * 60 for number in range(count)]
