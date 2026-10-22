"""The runner's fixer pass: which files it passes, where it runs them, and what it reports
(spec: fixers-run-before-commits).

The pass runs over a real temporary git repository. The commands are a fake runner that
records them and edits files as a hook would, or, in the last two tests, a real program.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import ProjectConfig
from agent_build_kit.pipeline.stack_runner import FixResult
from agent_build_kit.pipeline.wiring import build_fixers
from tests.factories import commit_files, git, init_repo
from tests.fixers_fakes import FakeProfile, FakeRun, activate_app

PROTECTED = ".github/workflows/ci.yml"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A repo with `src/a.py`, `src/old.py`, `src/gone.py` and a protected file committed."""
    activate_app(
        environment={
            "sync": ["true"],
            "check": ["true"],
            "inputs": {"lock": ["uv.lock"]},
            "artifacts": ["node_modules/**"],
        }
    )
    repo = init_repo(tmp_path / "app")
    commit_files(
        repo,
        "start",
        {
            "src/a.py": "a=1\n",
            "src/old.py": "old=1\n",
            "src/gone.py": "gone=1\n",
            PROTECTED: "name: ci\n",
        },
    )
    return repo


def fixers(run: FakeRun, projects: list[ProjectConfig] | None = None):
    return build_fixers(profile=FakeProfile(), projects=projects, repo_name="app", run=run)  # type: ignore[arg-type]


def passed(run: FakeRun, call: int = 0) -> list[str]:
    """The files the `call`th command was given, in name order."""
    return sorted(run.calls[call][0][1:])


def test_a_modified_and_an_untracked_file_are_passed_and_a_committed_one_is_not(tree: Path) -> None:
    (tree / "src" / "a.py").write_text("a=2\n")
    (tree / "src" / "new.py").write_text("new=1\n")
    run = FakeRun()

    fixers(run)(cwd=tree)

    assert [argv[0] for argv, _ in run.calls] == ["fmt"]
    assert passed(run) == ["src/a.py", "src/new.py"]
    assert run.calls[0][1] == tree


def test_a_deleted_file_and_the_files_a_commit_unstages_are_left_out(tree: Path) -> None:
    (tree / "src" / "gone.py").unlink()
    (tree / "src" / "a.py").write_text("a=2\n")
    (tree / "uv.lock").write_text("lock\n")
    (tree / "node_modules").mkdir()
    (tree / "node_modules" / "x.js").write_text("x\n")
    run = FakeRun()

    fixers(run)(cwd=tree)

    assert passed(run) == ["src/a.py"]


def test_each_project_runs_in_its_own_directory_with_its_own_profile(tree: Path) -> None:
    commit_files(tree, "more", {"web/src/a.ts": "a\n", "tools/b.py": "b\n"})
    (tree / "web" / "src" / "a.ts").write_text("a;\n")
    (tree / "tools" / "b.py").write_text("b=1\n")
    run = FakeRun()

    fixers(run, [ProjectConfig(path="web", profile="node-npm")])(cwd=tree)

    by_where = {where: argv for argv, where in run.calls}
    assert set(by_where) == {tree / "web", tree}
    assert by_where[tree / "web"][0] == "sh"  # the node-npm profile's command
    assert by_where[tree / "web"][-1] == "src/a.ts"
    assert by_where[tree] == ["fmt", "tools/b.py"]
    assert len(run.calls) == 2


def test_a_clean_tree_runs_nothing_and_reports_nothing(tree: Path) -> None:
    run = FakeRun()

    result = fixers(run)(cwd=tree)

    assert run.calls == []
    assert result == FixResult()


def test_a_protected_file_is_not_passed_and_is_reported_skipped(tree: Path) -> None:
    (tree / "src" / "a.py").write_text("a=2\n")
    (tree / PROTECTED).write_text("name: changed\n")
    run = FakeRun()

    result = fixers(run)(cwd=tree)

    assert passed(run) == ["src/a.py"]
    assert result.skipped == (PROTECTED,)


def test_a_protected_file_the_command_rewrote_is_restored_and_reported(tree: Path) -> None:
    (tree / "src" / "a.py").write_text("a=2\n")

    def rewrite(argv: list[str], where: Path, call: int) -> int:
        (where / PROTECTED).write_text("name: rewritten by a hook\n")
        return 0

    result = fixers(FakeRun(rewrite))(cwd=tree)

    assert (tree / PROTECTED).read_text() == "name: ci\n"
    assert PROTECTED in result.skipped
    assert PROTECTED not in result.changed


def test_a_non_zero_exit_is_ignored_and_the_files_it_changed_are_reported(tree: Path) -> None:
    (tree / "src" / "a.py").write_text("a=2\n")

    def format_and_fail(argv: list[str], where: Path, call: int) -> int:
        (where / "src" / "a.py").write_text("a = 2\n")
        return 1

    result = fixers(FakeRun(format_and_fail))(cwd=tree)

    assert result.changed == ("src/a.py",)
    assert result.failed == ()


def test_a_second_pass_is_made_only_when_the_first_changed_a_file(tree: Path) -> None:
    (tree / "src" / "a.py").write_text("a=2\n")

    def change_once(argv: list[str], where: Path, call: int) -> int:
        if call == 1:
            (where / "src" / "a.py").write_text("a = 2\n")
        return 1

    changed = FakeRun(change_once)
    fixers(changed)(cwd=tree)
    assert len(changed.calls) == 2

    unchanged = FakeRun()
    fixers(unchanged)(cwd=tree)
    assert len(unchanged.calls) == 1


def test_there_is_never_a_third_pass(tree: Path) -> None:
    (tree / "src" / "a.py").write_text("a=2\n")

    def change_every_time(argv: list[str], where: Path, call: int) -> int:
        (where / "src" / "a.py").write_text(f"a = {call}\n")
        return 0

    run = FakeRun(change_every_time)
    result = fixers(run)(cwd=tree)

    assert len(run.calls) == 2
    assert result.changed == ("src/a.py",)


def test_a_command_that_cannot_start_is_reported_and_does_not_stop_the_pass(tree: Path) -> None:
    (tree / "src" / "a.py").write_text("a=2\n")

    def missing(argv: list[str], where: Path, call: int) -> int:
        raise FileNotFoundError(argv[0])

    result = fixers(FakeRun(missing))(cwd=tree)

    assert len(result.failed) == 1
    assert "fmt" in result.failed[0]
    assert result.changed == ()


def test_the_repos_own_command_replaces_the_profiles(tree: Path) -> None:
    activate_app(tests={"fix_command": ["scripts/format.sh", "--write"]})
    (tree / "src" / "a.py").write_text("a=2\n")
    run = FakeRun()

    fixers(run)(cwd=tree)

    assert run.calls == [(["scripts/format.sh", "--write", "src/a.py"], tree)]


def test_the_empty_list_turns_the_pass_off(tree: Path) -> None:
    activate_app(tests={"fix_command": []})
    (tree / "src" / "a.py").write_text("a=2\n")
    run = FakeRun()

    result = fixers(run)(cwd=tree)

    assert run.calls == []
    assert result == FixResult()


def test_unset_follows_the_profile(tree: Path) -> None:
    (tree / "src" / "a.py").write_text("a=2\n")
    run = FakeRun()

    fixers(run)(cwd=tree)

    assert run.calls == [(["fmt", "src/a.py"], tree)]


def test_a_real_formatter_formats_an_untracked_file_and_the_result_names_it(tree: Path) -> None:
    activate_app(
        tests={
            "fix_command": [
                "sh",
                "-c",
                'for f in "$@"; do sed -i "s/ *= */ = /" "$f"; done; exit 1',
                "sh",
            ]
        }
    )
    (tree / "src" / "new.py").write_text("new=1\n")

    result = build_fixers(profile=profiles.get("python-uv"), repo_name="app")(cwd=tree)

    assert (tree / "src" / "new.py").read_text() == "new = 1\n"
    assert result.changed == ("src/new.py",)
    assert git(tree, "status", "--porcelain").splitlines() == ["?? src/new.py"]


def test_two_hooks_where_the_second_reformats_the_first_reach_the_stable_result(
    tree: Path,
) -> None:
    # One run of the hooks, in order, leaves "b"; only a second run reaches "c".
    hooks = 'for f in "$@"; do sed -i "s/b/c/" "$f"; sed -i "s/a/b/" "$f"; done'
    activate_app(tests={"fix_command": ["sh", "-c", hooks, "sh"]})
    (tree / "src" / "new.txt").write_text("a\n")

    result = build_fixers(profile=profiles.get("python-uv"), repo_name="app")(cwd=tree)

    assert (tree / "src" / "new.txt").read_text() == "c\n"
    assert result.changed == ("src/new.txt",)


def test_the_repos_command_runs_in_each_projects_directory_over_relative_paths(
    tree: Path,
) -> None:
    activate_app(tests={"fix_command": ["scripts/format.sh"]})
    commit_files(tree, "more", {"web/src/a.ts": "a\n", "tools/b.py": "b\n"})
    (tree / "web" / "src" / "a.ts").write_text("a;\n")
    (tree / "tools" / "b.py").write_text("b=1\n")
    run = FakeRun()

    fixers(run, [ProjectConfig(path="web", profile="node-npm")])(cwd=tree)

    assert sorted(run.calls) == sorted(
        [
            (["scripts/format.sh", "src/a.ts"], tree / "web"),
            (["scripts/format.sh", "tools/b.py"], tree),
        ]
    )
    assert not any(argv[0] in ("sh", "npx") for argv, _ in run.calls)


def test_a_protected_file_a_command_created_is_removed_and_reported(tree: Path) -> None:
    (tree / "src" / "a.py").write_text("a=2\n")
    created = ".github/workflows/new.yml"

    def create(argv: list[str], where: Path, call: int) -> int:
        (where / created).write_text("name: new\n")
        return 0

    result = fixers(FakeRun(create))(cwd=tree)

    assert not (tree / created).exists()
    assert created in result.skipped
