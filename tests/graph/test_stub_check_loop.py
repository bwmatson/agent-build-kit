"""The check-and-fix loop after the test step of a stubbed build (spec: stub-check-loop).

The agent and the static checks are the runner's fakes; the checks the pipeline binds are
exercised over a real repository and a fake profile at the end.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, cast

from agent_build_kit.pipeline.wiring import build_stub_checks
from agent_build_kit.profiles.base import ToolchainProfile
from tests.factories import git, init_repo
from tests.graph.stub_loop_fakes import StubLoop, stubbed_build
from tests.graph.test_build_path import build
from tests.graph_driver import fresh as fresh_store

LINT = "tests/test_x.py:1:8: F401 `os` imported but unused"


def looping(tmp_path: Path, **options: Any) -> StubLoop:
    stubbed_build()
    started = fresh_store(tmp_path)
    return StubLoop(started.store, **options)


def test_checks_that_pass_make_the_tests_commit_and_go_on_to_the_implementation(
    tmp_path: Path,
) -> None:
    recorder = looping(tmp_path)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open"
    assert recorder.events[:5] == [
        "claude:tests",
        "stub-checks",
        "commit:test",
        "claude:impl",
        "commit:feat",
    ]


def test_no_test_is_executed_by_the_loop(tmp_path: Path) -> None:
    recorder = looping(tmp_path, checks=[(False, LINT), (True, "")])

    build(tmp_path, recorder, **recorder.overrides(tmp_path))

    before_the_tests_commit = recorder.events[: recorder.events.index("commit:test")]
    assert before_the_tests_commit.count("stub-checks") == 2
    assert "unit-test" not in before_the_tests_commit
    assert "e2e-test" not in before_the_tests_commit


def test_a_failing_check_hands_its_output_to_the_test_agent_and_runs_the_checks_again(
    tmp_path: Path,
) -> None:
    recorder = looping(tmp_path, checks=[(False, LINT), (True, "")])

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open"
    assert recorder.events[:7] == [
        "claude:tests",
        "stub-checks",
        "claude:fix_stub",
        "stub-checks",
        "commit:test",
        "claude:impl",
        "commit:feat",
    ]
    (fix,) = recorder.fix_prompts
    assert LINT in fix
    assert LINT not in recorder.prompts[0], "the tests prompt was written before any check ran"


def test_the_checks_a_stubbed_build_binds_stage_a_new_file_and_run_the_clean_command_with_types(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("base\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    (repo / "stub.py").write_text("def f() -> int:\n    raise NotImplementedError\n")
    head = git(repo, "rev-parse", "HEAD")

    class Profile:
        """Accepts the clean command only for a file the index holds; any other command is
        an assertion that the loop ran something it must not."""

        asked: list[bool]

        def __init__(self) -> None:
            self.asked = []

        def clean_command(self, *, types: bool = False) -> str:
            self.asked.append(types)
            return "git diff --cached --name-only | grep -x stub.py"

        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"the loop used {name}")

    profile = Profile()

    ok, output = build_stub_checks(profile=cast(ToolchainProfile, profile))(cwd=repo)

    assert ok, output
    assert profile.asked == [True]
    assert git(repo, "rev-parse", "HEAD") == head, "nothing was committed"
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=repo, capture_output=True, text=True
    )
    assert staged.stdout.split() == ["stub.py"]
