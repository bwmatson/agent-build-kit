"""`abk init --policy-only`, `--policy-fix` and `--run-policy-fix`: the policy step alone on an
existing installation, the exit codes, and what each flag lets be written or run."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from tests.cli.policy_step_fakes import (
    AMEND_ROW,
    Operator,
    PolicyFileRuntime,
    changing_nothing,
    command_of,
    configured,
    patching,
    policy_file,
    real_fixes,
    recorded,
)
from tests.cli.test_init import app, init_args, stubs  # noqa: F401 — fixtures
from tests.runtimes.selectable import AMEND


@pytest.fixture
def events() -> list[str]:
    return []


def tree(root: Path) -> dict[str, bytes]:
    """Every file under `root` with its bytes."""
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def forbid_the_other_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Detection, research and propose are not part of the policy step."""

    def refuse(*args: object, **kwargs: object) -> None:
        pytest.fail("a step the policy step does not include ran")

    for step in ("detect_repo", "research", "propose", "run_claude", "run_openspec"):
        monkeypatch.setattr(init_cmd, step, refuse)


def test_a_passing_check_asks_nothing_and_exits_zero(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = PolicyFileRuntime("known", policy_file(tmp_path / "policy.txt"), log=events)
    planning = configured(tmp_path, app, monkeypatch, runtime)
    events.clear()
    before = tree(planning)
    forbid_the_other_steps(monkeypatch)

    assert main(["init", str(planning), "--policy-only"]) == 0

    assert events == ["check"]
    assert tree(planning) == before


def test_a_recorded_fix_is_the_only_change_to_the_file_and_no_repo_is_detected(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    patched = policy_file(tmp_path / "policy.txt", AMEND_ROW)
    fix = [*patching(tmp_path, "patch.sh"), str(patched)]
    runtime = PolicyFileRuntime("unknown", patched, log=events)
    planning = configured(tmp_path, app, monkeypatch, runtime)
    before = tree(planning)
    raw = yaml.safe_load((planning / "abk.yaml").read_text())
    forbid_the_other_steps(monkeypatch)
    monkeypatch.setattr(init_cmd, "ask", Operator(capfd, "2", " ".join(fix)))
    real_fixes(monkeypatch)

    assert main(["init", str(planning), "--policy-only"]) == 0

    raw["runtimes"]["unknown"]["policy_fix"] = fix
    assert yaml.safe_load((planning / "abk.yaml").read_text()) == raw
    after = tree(planning)
    assert {p for p in after if before.get(p) != after[p]} == {str(planning / "abk.yaml")}
    assert after.keys() == before.keys()


def test_a_class_still_open_after_the_step_exits_one_naming_the_spelling(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    runtime = PolicyFileRuntime("known", policy_file(tmp_path / "policy.txt", AMEND_ROW), log=[])
    planning = configured(tmp_path, app, monkeypatch, runtime)

    assert main(["init", str(planning), "--policy-only", "--yes"]) == 1

    shown = capfd.readouterr()
    said = shown.out + shown.err
    assert AMEND in said
    assert command_of(AMEND, AMEND_ROW[1]) in said


def test_a_missing_abk_yaml_is_a_usage_error_that_writes_nothing(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    assert main(["init", str(empty), "--policy-only"]) == 2

    assert list(empty.iterdir()) == []


def test_an_unknown_runtime_is_a_usage_error_that_writes_nothing(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = PolicyFileRuntime("known", policy_file(tmp_path / "policy.txt"), log=[])
    planning = configured(tmp_path, app, monkeypatch, runtime)
    before = tree(planning)

    assert main(["init", str(planning), "--policy-only", "--runtime", "no-such-runtime"]) == 2

    assert tree(planning) == before


def test_a_flag_that_cannot_combine_with_it_is_a_usage_error_that_writes_nothing(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = PolicyFileRuntime("known", policy_file(tmp_path / "policy.txt"), log=[])
    planning = configured(tmp_path, app, monkeypatch, runtime)
    before = tree(planning)

    assert main(["init", str(planning), "--policy-only", "--update-rules"]) == 2

    assert tree(planning) == before


def test_policy_fix_that_is_not_an_executable_is_refused_with_exit_two(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = PolicyFileRuntime("known", policy_file(tmp_path / "policy.txt", AMEND_ROW), log=[])
    planning = configured(tmp_path, app, monkeypatch, runtime)
    before = tree(planning)

    for extra in (["--policy-only"], []):
        argv = [*init_args(planning, app), "--yes", *extra, "--policy-fix", "no-such-program-here"]
        assert main(argv) == 2

    assert tree(planning) == before


def test_policy_fix_is_recorded_after_a_yes_and_used_in_this_run(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    patched = policy_file(tmp_path / "policy.txt", AMEND_ROW)
    fix = [*patching(tmp_path, "patch.sh"), str(patched)]
    runtime = PolicyFileRuntime("unknown", patched, log=events)
    planning = configured(tmp_path, app, monkeypatch, runtime)
    monkeypatch.setattr(init_cmd, "ask", Operator(capfd, otherwise="y", log=events))
    real_fixes(monkeypatch)

    code = main(["init", str(planning), "--policy-only", "--policy-fix", " ".join(fix)])

    assert code == 0
    assert recorded(planning, "unknown")["policy_fix"] == fix
    assert patched.read_text() == ""


def test_policy_fix_is_not_recorded_on_a_no(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    patched = policy_file(tmp_path / "policy.txt", AMEND_ROW)
    fix = [*patching(tmp_path, "patch.sh"), str(patched)]
    runtime = PolicyFileRuntime("unknown", patched, log=[])
    planning = configured(tmp_path, app, monkeypatch, runtime)
    before = tree(planning)
    monkeypatch.setattr(init_cmd, "ask", Operator(capfd, otherwise="n"))
    real_fixes(monkeypatch)

    main(["init", str(planning), "--policy-only", "--policy-fix", " ".join(fix)])

    assert tree(planning) == before
    assert patched.read_text() != ""


def test_policy_fix_with_yes_is_recorded_and_run_without_policy_only(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patched = policy_file(tmp_path / "policy.txt", AMEND_ROW)
    fix = [*patching(tmp_path, "patch.sh"), str(patched)]
    runtime = PolicyFileRuntime("unknown", patched, log=[])
    planning = configured(tmp_path, app, monkeypatch, runtime)
    real_fixes(monkeypatch)

    main([*init_args(planning, app), "--yes", "--policy-fix", " ".join(fix)])

    assert recorded(planning, "unknown")["policy_fix"] == fix
    assert patched.read_text() == ""


def test_yes_with_a_configured_fix_and_no_flag_runs_no_fix_and_exits_one(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    patched = policy_file(tmp_path / "policy.txt", AMEND_ROW)
    fix = [*patching(tmp_path, "patch.sh"), str(patched)]
    runtime = PolicyFileRuntime("known", patched, log=events)
    planning = configured(tmp_path, app, monkeypatch, runtime, policy_fix=fix)
    events.clear()
    real_fixes(monkeypatch)

    assert main(["init", str(planning), "--policy-only", "--yes"]) == 1

    shown = capfd.readouterr()
    assert AMEND in shown.out + shown.err
    assert "patching the agent policy" not in shown.out
    assert patched.read_text() != ""
    assert events == ["check"]


def test_yes_with_run_policy_fix_runs_the_configured_fix_unasked(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patched = policy_file(tmp_path / "policy.txt", AMEND_ROW)
    fix = [*patching(tmp_path, "patch.sh"), str(patched)]
    runtime = PolicyFileRuntime("known", patched, log=events)
    planning = configured(tmp_path, app, monkeypatch, runtime, policy_fix=fix)
    events.clear()
    real_fixes(monkeypatch)

    assert main(["init", str(planning), "--policy-only", "--yes", "--run-policy-fix"]) == 0

    assert patched.read_text() == ""
    assert events == ["check", "check"]


def test_a_fix_that_changes_nothing_exits_one_and_says_what_is_still_open(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    patched = policy_file(tmp_path / "policy.txt", AMEND_ROW)
    fix = [*changing_nothing(tmp_path), str(patched)]
    runtime = PolicyFileRuntime("known", patched, log=[])
    planning = configured(tmp_path, app, monkeypatch, runtime, policy_fix=fix)
    real_fixes(monkeypatch)

    code = main(["init", str(planning), "--policy-only", "--yes", "--run-policy-fix"])

    said = capfd.readouterr().out
    assert code == 1
    assert "the fix made no change; still not refused: " in said
