"""A failed live test prints the scratch installation's state: the section's contents, who gets
it, where it sits in the failure block, and that a source or the hook failing changes nothing."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests import scratch_dump
from tests.scratch_dump_support import (
    BRANCH,
    FAILURE_NOTE,
    HOLDER,
    PARENT,
    PAUSE_REASON,
    REQUESTS,
    TICK_EXIT,
    TICK_LINE,
    filled_scratch,
    run_children,
    sections,
    stand_in_tick,
    tree_state,
    without_section,
)
from tests.scratch_tick import TickResult, commits_on_unit_branch

FAILS = """\

@pytest.mark.local_stack
def test_fails(tmp_path, monkeypatch):
    ticked_scratch(tmp_path, monkeypatch, env={"ABK_RUNTIME": "claude_code", "AB_TOKEN": "x"})
    print("CAPTURED-STDOUT")
    pytest.fail("the plain failure")
"""


def only_section(result: pytest.RunResult) -> list[str]:
    found = sections(result.outlines)
    assert len(found) == 1, result.outlines
    return found[0]


def test_a_failed_live_test_with_a_scratch_gets_a_section_holding_every_source(
    pytester: pytest.Pytester,
) -> None:
    result = run_children(pytester, FAILS)

    section = only_section(result)
    text = "\n".join(section)
    assert section[0].startswith("cause hints:")
    assert TICK_LINE in text and str(TICK_EXIT) in section[0]
    assert "blocked, waits on " + PARENT in text and "backoff" in text
    for unit_id in ("feature/1", "feature/2"):
        assert unit_id in text
    assert "held" in text and "review" in text and "failed" in text
    assert BRANCH in text and "spec/feature/2" in text
    assert FAILURE_NOTE in text
    assert PAUSE_REASON in text
    assert HOLDER in text
    assert re.search(r"refs/heads/main\b", text) and re.search(rf"refs/heads/{BRANCH}\b", text)
    assert "run log line 40" in text
    assert "implementer" in text
    for _, path in REQUESTS:
        assert path in text
    assert "ABK_RUNTIME" in text
    assert "AB_TOKEN" in text and "AB_TOKEN=" not in text


def test_the_section_is_the_last_part_of_the_failure_block(pytester: pytest.Pytester) -> None:
    result = run_children(pytester, FAILS)

    outlines = result.outlines
    start = next(i for i, line in enumerate(outlines) if "SCRATCH STATE" in line)
    stdout = next(i for i, line in enumerate(outlines) if "Captured stdout call" in line)
    after = outlines[start + 1 :]
    block_end = next(i for i, line in enumerate(after) if re.match(r"^(_{3,}|={3,})", line))
    assert stdout < start
    assert not any("Captured" in line for line in after[:block_end])


def test_a_scratch_fixture_argument_is_found_without_registering_it(
    pytester: pytest.Pytester,
) -> None:
    body = """\

@pytest.fixture
def scratch(tmp_path, monkeypatch):
    made = filled_scratch(tmp_path)
    stand_in_tick(made, monkeypatch)
    return made


@pytest.mark.local_stack
def test_fails(scratch):
    pytest.fail("the plain failure")
"""
    result = run_children(pytester, body)

    section = only_section(result)
    assert section[0].startswith("cause hints:")
    assert TICK_LINE in "\n".join(section)


def test_a_test_that_passes_is_skipped_is_unmarked_or_has_no_scratch_gets_no_section(
    pytester: pytest.Pytester,
) -> None:
    body = """\

@pytest.mark.local_stack
def test_passes(tmp_path, monkeypatch):
    ticked_scratch(tmp_path, monkeypatch)


@pytest.mark.local_stack
def test_skipped(tmp_path, monkeypatch):
    ticked_scratch(tmp_path / "again", monkeypatch)
    pytest.skip("not today")


def test_unmarked_fails(tmp_path, monkeypatch):
    ticked_scratch(tmp_path / "third", monkeypatch)
    pytest.fail("unmarked")


@pytest.mark.local_stack
def test_with_no_scratch_fails():
    pytest.fail("no scratch of its own, though earlier tests registered theirs")
"""
    result = run_children(pytester, body)

    result.assert_outcomes(passed=1, skipped=1, failed=2)
    assert sections(result.outlines) == []
    assert not any("SCRATCH STATE" in line for line in result.outlines)


def test_a_failure_in_setup_and_one_in_teardown_each_get_a_section(
    pytester: pytest.Pytester,
) -> None:
    body = """\

@pytest.fixture
def broken_setup(tmp_path, monkeypatch):
    ticked_scratch(tmp_path, monkeypatch)
    raise RuntimeError("setup broke")


@pytest.fixture
def broken_teardown(tmp_path, monkeypatch):
    ticked_scratch(tmp_path, monkeypatch)
    yield
    raise RuntimeError("teardown broke")


@pytest.mark.local_stack
def test_a(broken_setup):
    pass


@pytest.mark.local_stack
def test_b(broken_teardown):
    pass
"""
    result = run_children(pytester, body)

    result.assert_outcomes(passed=1, errors=2)
    found = sections(result.outlines)
    assert len(found) == 2
    assert all(section[0].startswith("cause hints:") for section in found)


def test_the_branch_check_opens_with_the_same_hints_line_as_the_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = filled_scratch(tmp_path)
    tick = stand_in_tick(scratch, monkeypatch)
    missing = "spec/feature/9"

    with pytest.raises(pytest.fail.Exception) as raised:
        commits_on_unit_branch(scratch, missing, tick)

    first = str(raised.value).splitlines()[0]
    assert first == scratch_dump.cause_hints(scratch, missing, tick)
    assert first.startswith("cause hints:")


def test_a_source_that_cannot_be_read_is_one_line_naming_the_error_and_hides_nothing_else(
    pytester: pytest.Pytester,
) -> None:
    body = """\

@pytest.mark.local_stack
def test_fails(tmp_path, monkeypatch):
    scratch = ticked_scratch(tmp_path, monkeypatch)
    (scratch.state / "units.json").unlink()
    (scratch.state / "units.json").mkdir()
    pytest.fail("the plain failure")
"""
    result = run_children(pytester, body)

    section = only_section(result)
    text = "\n".join(section)
    assert "scratch state unavailable: IsADirectoryError" in text
    assert TICK_LINE in text and HOLDER in text and PAUSE_REASON in text
    assert "blocked, waits on " + PARENT in text


def test_a_missing_remote_is_unavailable_for_the_remote_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = filled_scratch(tmp_path)
    stand_in_tick(scratch, monkeypatch)
    subprocess.run(["rm", "-rf", str(scratch.remote)], check=True)

    text = scratch_dump.scratch_state(scratch)

    assert re.search(r"scratch state unavailable: \w+", text)
    assert TICK_LINE in text and FAILURE_NOTE in text and HOLDER in text


def test_a_git_that_runs_out_of_time_is_unavailable_and_was_given_ten_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = filled_scratch(tmp_path)
    stand_in_tick(scratch, monkeypatch)
    calls: list[tuple[list[str], dict]] = []

    def run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    # No second elapses: the stand-in raises the timeout the moment git is asked.
    monkeypatch.setattr(scratch_dump, "runner", SimpleNamespace(**{**vars(subprocess), "run": run}))

    text = scratch_dump.scratch_state(scratch)

    assert calls and all(kwargs["timeout"] == 10 for _, kwargs in calls)
    assert "scratch state unavailable: TimeoutExpired" in text
    assert TICK_LINE in text and FAILURE_NOTE in text


def test_building_the_dump_creates_and_changes_no_file_in_the_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = filled_scratch(tmp_path)
    tick = stand_in_tick(scratch, monkeypatch)
    assert isinstance(tick, TickResult)
    before = tree_state(tmp_path)

    scratch_dump.scratch_state(scratch)

    assert tree_state(tmp_path) == before


def test_the_outcome_and_traceback_are_those_of_the_same_run_without_the_plugin(
    pytester: pytest.Pytester,
) -> None:
    body = """\

@pytest.mark.local_stack
def test_fails(tmp_path, monkeypatch):
    scratch = ticked_scratch(tmp_path, monkeypatch)
    (scratch.state / "units.json").unlink()
    (scratch.state / "units.json").mkdir()
    pytest.fail("the plain failure")


@pytest.mark.local_stack
def test_unreadable_scratch(monkeypatch):
    register_scratch(object())
    assert [1, 2] == [1, 3]
"""
    with_plugin = run_children(pytester, body)
    without_plugin = run_children(pytester, body, plugin=False)

    assert sections(with_plugin.outlines)
    assert with_plugin.ret == without_plugin.ret == 1
    with_plugin.assert_outcomes(failed=2)
    assert without_section(with_plugin.outlines) == without_section(without_plugin.outlines)
