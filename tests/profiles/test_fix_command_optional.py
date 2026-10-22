"""A profile without `fix_command` gets no fixer pass, as one without `supports_stubs` gets
no stubs (spec: fixers-run-before-commits)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.pipeline.stack_runner import FixResult
from agent_build_kit.pipeline.wiring import build_fixers
from tests.factories import commit_files, git, init_repo
from tests.fixers_fakes import Bare, FakeRun, activate_app


def test_a_profile_without_the_method_is_registered_and_runs_no_command(tmp_path: Path) -> None:
    activate_app()
    tree = init_repo(tmp_path / "app")
    commit_files(tree, "start", {"src/a.py": "x = 1\n"})
    (tree / "src" / "a.py").write_text("x=2\n")
    run = FakeRun()

    with profiles.registered(Bare()):  # type: ignore[arg-type]
        fixers = build_fixers(profile=profiles.get("bare"), repo_name="app", run=run)
        result = fixers(cwd=tree)

    assert result == FixResult()
    assert run.calls == []
    assert git(tree, "status", "--porcelain").strip() == "M src/a.py"
