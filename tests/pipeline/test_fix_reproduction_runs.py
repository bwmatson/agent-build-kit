"""The runs of the reproduction check: how many, alone and under load, and what each outcome
says (spec: fix-unit-reproduction).

`check` is given fakes for one run alone and one run under load; the test lookups read a
planning folder; `build_reproduce` runs the profile's commands through a fake `run`.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.pipeline.fix_reproduction import Attempt, Outcome, check
from agent_build_kit.pipeline.flakes import fix_change_test, merged_fix_since
from agent_build_kit.pipeline.wiring import build_reproduce
from tests.conftest import make_installation

TEST = "tests/test_widget.py::test_renders_the_label"


class Runs:
    """Answers each run in turn with `answers[kind]`, keeping the order the runs were made in."""

    def __init__(self, alone: Attempt = Attempt.PASSED, loaded: Attempt = Attempt.PASSED) -> None:
        self.answers = {"alone": alone, "loaded": loaded}
        self.made: list[str] = []

    def one(self, kind: str):
        def run() -> Attempt:
            self.made.append(kind)
            return self.answers[kind]

        return run


def checked(runs: Runs, count: int = 3):
    return check(TEST, count, alone=runs.one("alone"), loaded=runs.one("loaded"))


def test_a_test_that_never_fails_is_not_reproduced_and_says_how_many_runs() -> None:
    runs = Runs()

    found = checked(runs, 3)

    assert found.outcome is Outcome.NOT_REPRODUCED
    assert found.note.startswith("not reproduced: 0 of 3 runs alone, 0 of 3 under load")
    assert runs.made == ["alone"] * 3 + ["loaded"] * 3


def test_a_failure_alone_is_enough() -> None:
    assert checked(Runs(alone=Attempt.FAILED)).outcome is Outcome.FAILS


def test_a_failure_only_under_load_is_enough() -> None:
    runs = Runs(loaded=Attempt.FAILED)

    assert checked(runs).outcome is Outcome.FAILS
    assert runs.made == ["alone"] * 3 + ["loaded"], "it stops at the first failure"


def test_a_test_that_is_not_collected_is_gone() -> None:
    found = checked(Runs(alone=Attempt.NOT_COLLECTED))

    assert found.outcome is Outcome.GONE
    assert TEST in found.note and "no longer in the tree" in found.note


def test_the_test_of_a_fix_change_is_read_from_its_first_group_heading(tmp_path: Path) -> None:
    installation = make_installation(tmp_path)
    for name, heading in {
        "fix-test-a": f"Make `{TEST}` deterministic",
        "fix-test-b": "Do the work",
    }.items():
        tasks = installation.changes_dir / name / "tasks.md"
        tasks.parent.mkdir(parents=True)
        tasks.write_text(f"# Tasks\n\n## 1. [app] [unit-test] {heading}\n\n- [ ] 1.1 Test: x\n")

    assert fix_change_test(installation, "fix-test-a") == TEST
    assert fix_change_test(installation, "fix-test-b") is None
    assert fix_change_test(installation, "fix-test-missing") is None


def test_a_merged_fix_of_the_same_test_is_found_only_when_newer(tmp_path: Path) -> None:
    installation = make_installation(tmp_path)
    own = installation.changes_dir / "fix-test-tests-test-widget-py-test-renders-the-label-2"
    (own).mkdir(parents=True)
    (own / "proposal.md").write_text("## Why\n")
    archive = installation.changes_dir / "archive"
    earlier = archive / "2000-01-01-fix-test-tests-test-widget-py-test-renders-the-label"
    earlier.mkdir(parents=True)

    assert merged_fix_since(installation, own.name, TEST) is None, "an older fix is not newer"

    newer = archive / "2999-01-01-fix-flaky-tests-test-widget-py-test-renders-the-label"
    newer.mkdir()

    found = merged_fix_since(installation, own.name, TEST)
    assert found is not None and found.endswith("test-renders-the-label")
    assert merged_fix_since(installation, own.name, "tests/test_other.py::test_x") is None


def test_a_fix_archived_the_day_the_change_was_written_is_not_newer(tmp_path: Path) -> None:
    installation = make_installation(tmp_path)
    own = installation.changes_dir / "fix-test-tests-test-widget-py-test-renders-the-label-2"
    own.mkdir(parents=True)
    (own / "proposal.md").write_text("## Why\n")
    today = f"{datetime.now(UTC):%Y-%m-%d}"
    earlier = (
        installation.changes_dir
        / "archive"
        / (f"{today}-fix-test-tests-test-widget-py-test-renders-the-label")
    )
    earlier.mkdir(parents=True)

    assert merged_fix_since(installation, own.name, TEST) is None


def reproducing(tmp_path: Path, outputs: dict[str, subprocess.CompletedProcess]):
    """A `reproduce_test` over a worktree holding the test, and the commands it ran."""
    tree = tmp_path / "tree"
    (tree / "tests").mkdir(parents=True)
    (tree / "tests" / "test_widget.py").write_text(
        "def test_renders_the_label():\n    assert True\n"
    )
    (tree / "pyproject.toml").write_text(
        '[project]\nname = "app"\nversion = "0"\ndependencies = ["pytest-xdist"]\n'
    )
    commands: list[list[str]] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        commands.append(args)
        kind = "loaded" if "tests/test_widget.py" in args else "alone"
        return outputs[kind]

    reproduce = build_reproduce(profile=profiles.get("python-uv"), run=run)
    return tree, reproduce, commands


def done(code: int, out: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout=out, stderr="")


def test_the_runs_alone_and_under_load_are_made_the_configured_times(tmp_path: Path) -> None:
    tree, reproduce, commands = reproducing(tmp_path, {"alone": done(0), "loaded": done(0)})

    found = reproduce(cwd=tree, test=TEST, runs=2)

    assert found.outcome is Outcome.NOT_REPRODUCED
    assert "0 of 2 runs alone, 0 of 2 under load" in found.note
    alone = [c for c in commands if TEST in c]
    loaded = [c for c in commands if "tests/test_widget.py" in c and TEST not in c]
    assert (len(alone), len(loaded)) == (2, 2)
    assert all("-n" not in c for c in alone), "alone is serial"
    assert all("-n" in c for c in loaded), "under load is the file's tests on the workers"


def test_a_run_that_names_the_test_failed_reproduces_it(tmp_path: Path) -> None:
    failure = done(1, f"FAILED {TEST} - assert False\n")
    tree, reproduce, _ = reproducing(tmp_path, {"alone": failure, "loaded": done(0)})

    assert reproduce(cwd=tree, test=TEST, runs=2).outcome is Outcome.FAILS


NOT_FOUND = "ERROR: not found: tests/test_widget.py::test_was_renamed (no match in any of [])"


def test_a_test_the_collection_does_not_find_is_gone(tmp_path: Path) -> None:
    tree, reproduce, commands = reproducing(
        tmp_path, {"alone": done(4, NOT_FOUND), "loaded": done(0)}
    )

    found = reproduce(cwd=tree, test="tests/test_widget.py::test_was_renamed", runs=2)

    assert found.outcome is Outcome.GONE
    assert len(commands) == 1, "the first run says so"


def test_a_name_the_file_does_not_hold_is_not_gone_when_collection_finds_it(
    tmp_path: Path,
) -> None:
    # Inherited from a base class in another file, or made up at collection time.
    for name in ("test_inherited_from_a_base", "test_made_up[param]"):
        tree, reproduce, _ = reproducing(
            tmp_path / name[:12], {"alone": done(0), "loaded": done(0)}
        )

        found = reproduce(cwd=tree, test=f"tests/test_widget.py::{name}", runs=2)

        assert found.outcome is Outcome.NOT_REPRODUCED, name


def test_a_file_not_found_under_the_root_is_skipped_not_gone(tmp_path: Path) -> None:
    tree, reproduce, commands = reproducing(tmp_path, {"alone": done(0), "loaded": done(0)})

    found = reproduce(
        cwd=tree, test="elsewhere/tests/test_widget.py::test_renders_the_label", runs=2
    )

    assert found.outcome is Outcome.SKIPPED
    assert commands == []


def test_a_profile_that_cannot_run_one_test_is_skipped(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    (tree / "tests").mkdir(parents=True)
    (tree / "tests" / "test_widget.py").write_text("")
    reproduce = build_reproduce(profile=profiles.get("node-npm"), run=lambda *a, **k: done(0))

    assert reproduce(cwd=tree, test=TEST, runs=2).outcome is Outcome.SKIPPED
