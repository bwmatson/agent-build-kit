"""`abk gate` judges a unit's branch against the branch it stacks on.

It inferred the toolchain profile from whichever repo `--repo` sits in, and
took `main` for the base regardless — so run by hand in a repo that integrates
on `dev`, it compared the branch against a `main` that lacks most of the code
and reported a wall of commits that were never the unit's own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.pipeline import gate
from tests.conftest import make_installation


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`check_branch` recording the base it was asked to judge against."""
    bases: list[str] = []

    def record(repo, base, **kwargs):
        bases.append(base)
        return []

    monkeypatch.setattr(gate, "check_branch", record)
    return bases


def workspace_on(tmp_path: Path, branch: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    inst = make_installation(tmp_path / "planning")
    repos = {
        name: entry.model_copy(update={"default_branch": branch if name == "app" else "main"})
        for name, entry in inst.config.repos.items()
    }
    config = inst.config.model_copy(update={"repos": repos})
    (inst.root / "abk.yaml").write_text(dump(config))
    app = inst.root / "checkouts" / "app"
    app.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(inst.root)
    return app


def test_the_base_is_the_repo_s_integration_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asked: list[str]
) -> None:
    app = workspace_on(tmp_path, "dev", monkeypatch)

    assert main(["gate", "--repo", str(app)]) == 0

    assert asked == ["origin/dev"], "the remote's, as the runner builds on — the local one is stale"


def test_a_repo_on_main_is_judged_against_the_remote_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asked: list[str]
) -> None:
    app = workspace_on(tmp_path, "main", monkeypatch)

    main(["gate", "--repo", str(app)])

    assert asked == ["origin/main"]


def test_an_explicit_base_is_respected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asked: list[str]
) -> None:
    """A stacked unit's base is its parent's branch, which only the caller knows."""
    app = workspace_on(tmp_path, "dev", monkeypatch)

    main(["gate", "--repo", str(app), "--base", "spec/add-marker/1"])

    assert asked == ["spec/add-marker/1"]


def test_outside_any_installation_it_keeps_its_old_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asked: list[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "repo").mkdir()

    main(["gate", "--repo", str(tmp_path / "repo")])

    assert asked == ["main"]
