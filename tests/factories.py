"""Builders the spec_driven tests share.

Nine test files each had their own `unit()` and seven their own `git()`, and
the copies had drifted in their defaults without any test depending on the
difference. A file that does need a different default says so where it
imports these, rather than in a tenth near-copy.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from agent_build_kit import openspec
from agent_build_kit.config import RepoConfig, dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.shell import git_out as git
from agent_build_kit.pipeline.tier2 import TestFailure, Tier2Result, build_snapshot
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import Unit, ready_units
from agent_build_kit.pipeline.wiring import build_commit

__all__ = [
    "STOCK_CONFIG",
    "commit",
    "commit_files",
    "commit_unit_work",
    "fake_openspec",
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
    on `main`, which ignores bytecode, the virtualenv and `uv.lock` so a unit's
    commits hold only the unit's work. The lock is ignored, not committed,
    because resolving it needs the network."""
    init_repo(path)
    (path / ".gitignore").write_text("__pycache__/\n*.pyc\n.venv/\nuv.lock\n")
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


def snapshot(output: str, *, failures: list[TestFailure] | None = None) -> str:
    return build_snapshot(
        Tier2Result(
            sha="abcdef0123",
            passed=3,
            failed=len(failures) if failures else 1,
            skipped=0,
            duration_seconds=1.5,
            command="uv run pytest -m local_stack",
            output=output,
            failures=failures or [],
        )
    )


def follow_ups(count: int) -> list[str]:
    return [f"follow-up {number:02d}: " + "f" * 60 for number in range(count)]


def commit(repo: Path, name: str, content: str = "x") -> str:
    """Write one file and commit everything, with the file's name in the message; the
    new commit's sha."""
    (repo / name).write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"write {name}")
    return git(repo, "rev-parse", "HEAD")


def commit_files(repo: Path, message: str, files: dict[str, str]) -> None:
    """Write each file (making its folders) and commit everything with this message."""
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


def commit_unit_work(tree: Path, config: RepoConfig) -> None:
    """Commit the tree's work through the pipeline's own commit step, which makes one commit."""
    made = build_commit(unit_id=unit().id, repo=config, base="main")("feat: the work", cwd=tree)
    assert made == 1


STOCK_CONFIG = (
    "schema: spec-driven\n\n# context: |\n#   ...\n# rules:\n#   proposal:\n#     - ...\n"
)


def fake_openspec(argv, *, cwd, **kwargs):
    """A stand-in for the OpenSpec CLI: `init` writes the stock layout, `validate` passes
    every change on disk, and anything else succeeds."""
    args = argv[len(openspec.command()) :]
    if args[0] == "init":
        (cwd / "openspec" / "changes" / "archive").mkdir(parents=True)
        (cwd / "openspec" / "specs").mkdir()
        (cwd / "openspec" / "config.yaml").write_text(STOCK_CONFIG)
        return subprocess.CompletedProcess(argv, 0, "ok", "")
    if args[0] == "validate":
        changes = sorted(p.name for p in (cwd / "openspec" / "changes").iterdir() if p.is_dir())
        items = [{"id": n, "type": "change", "valid": True, "issues": []} for n in changes]
        return subprocess.CompletedProcess(argv, 0, json.dumps({"items": items}), "")
    return subprocess.CompletedProcess(argv, 0, f"ran {' '.join(args)}", "")


def planning(root: Path) -> Installation:
    """An installation the CLI can find: in memory is not enough, since the
    command resolves abk.yaml from the working directory upwards."""
    from tests.conftest import make_installation

    inst = make_installation(root)
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    return inst


def which_all(name: str) -> str | None:
    """A `which` that finds every program."""
    return f"/usr/bin/{name}"
