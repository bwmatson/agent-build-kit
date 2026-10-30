"""A group that names only test files is built as a lone `test:` commit, the path an
`[e2e-test]` group takes, and the repeat check still re-runs the tests it changed (spec:
group-build-modes)."""

from __future__ import annotations

from pathlib import Path

from tests.graph.branch_fakes import agent_calls, build, prepared, subjects, titled
from tests.pipeline.test_unit_test_repeat_check import ADDED, Runs, checkout, unit_test

TESTS = "- [ ] {n}.1 Test: fix `tests/test_foo.py` and `tests/helpers.py`.\n\n"
CODE = "- [ ] {n}.1 Test: a\n- [ ] {n}.2 Do `src/app/a.py`\n\n"


def tasks_of(tmp_path: Path, kinds: dict[int, str]) -> None:
    """Rewrite the unit's tasks: each group of `kinds` is headed `[unit-test]` and names the
    paths of its kind ("tests" or "code")."""
    path = tmp_path / "meta" / "openspec" / "changes" / "add-marker" / "tasks.md"
    path.write_text(
        "".join(
            f"## {n}. [app] [unit-test] G{n}\n\n" + (TESTS if kind == "tests" else CODE).format(n=n)
            for n, kind in kinds.items()
        )
    )


def run(tmp_path: Path, kinds: dict[int, str]) -> tuple[list[str], str, list[str], list[str]]:
    recorder, repo = prepared(tmp_path, groups={"add-marker": titled(*kinds)})
    tasks_of(tmp_path, kinds)
    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))
    return agent_calls(recorder.events), outcome.status, subjects(repo), recorder.events


def test_a_group_of_test_paths_commits_one_test_and_no_feat(tmp_path: Path) -> None:
    calls, status, commits, events = run(tmp_path, {1: "tests"})

    assert status == "open"
    assert calls == ["claude:tests"]
    assert commits == ["test: G1"]
    assert "review" in events


def test_a_test_path_group_beside_a_code_group_is_built_group_by_group(tmp_path: Path) -> None:
    calls, status, commits, _ = run(tmp_path, {1: "code", 2: "tests", 3: "code"})

    assert status == "open"
    assert calls == ["claude:tests", "claude:impl", "claude:tests", "claude:tests", "claude:impl"]
    assert commits == ["test: G1", "feat: G1", "test: G2", "test: G3", "feat: G3"]


def test_a_test_path_group_is_passed_over_by_the_implement_step(tmp_path: Path) -> None:
    calls, _, commits, _ = run(tmp_path, {1: "tests", 2: "tests"})

    assert calls == ["claude:tests"] * 2
    assert commits == ["test: G1", "test: G2"]


def test_the_repeat_check_still_reruns_the_tests_a_test_only_group_changed(
    tmp_path: Path,
) -> None:
    repo, base = checkout(tmp_path, {"test_new.py": ADDED})
    runs = Runs()

    passed, _ = unit_test(runs, repo, base)

    assert passed
    assert len(runs.repeating("test_added")) == 3
