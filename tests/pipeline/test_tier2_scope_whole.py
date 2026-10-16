"""Where a unit's tier 2 cannot be narrowed safely, or `full` is asked for, the whole marker
runs and the log says why; failing to narrow is never read as having no test of its own
(spec: tier2-scope)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.config import Tier2UnitScope
from agent_build_kit.pipeline import wiring
from agent_build_kit.profiles.python_uv import PROFILE
from tests.tier2_scope_fakes import NEW, OLD, WHOLE, Ran, branch, session

SKIPPED = "tier 2 skipped"


class Unselecting:
    """The python profile as one that cannot select tests by identifier."""

    name = "plain-profile"

    def __getattr__(self, attribute: str) -> Any:
        if attribute == "repeat_command":
            raise AttributeError(attribute)
        return getattr(PROFILE, attribute)


def adds_one_test(tmp_path: Path) -> tuple[Path, str]:
    return branch(tmp_path, {"tests/live/test_new.py": NEW}, base_files={"tests/t.py": OLD})


def changes_no_test(tmp_path: Path) -> tuple[Path, str]:
    return branch(tmp_path, {"src/app.py": "x = 1\n"}, base_files={"tests/t.py": OLD})


def test_a_repo_with_a_dev_stack_script_runs_it_as_before_and_logs_why(tmp_path: Path) -> None:
    repo, base = branch(
        tmp_path,
        {"src/app.py": "x = 1\n"},
        base_files={"tests/t.py": OLD, "scripts/dev-stack.sh": "#!/bin/sh\n"},
    )
    ran = Ran()
    log: list[str] = []

    session(tmp_path, ran, log=log, dev_stack="scripts/dev-stack.sh").run(cwd=repo, base=base)

    script = "scripts/dev-stack.sh"
    assert ran.commands == [[script, "up"], [script, "test"], [script, "down"]]
    assert "e2e-test runs whole: the repo's dev stack script runs it" in log


def test_a_profile_that_cannot_select_by_identifier_runs_the_whole_marker_and_names_itself(
    tmp_path: Path,
) -> None:
    repo, base = adds_one_test(tmp_path)
    ran = Ran()
    log: list[str] = []

    session(tmp_path, ran, log=log, profile=Unselecting()).run(cwd=repo, base=base)

    assert ran.commands == [WHOLE]
    [reason] = [line for line in log if "runs whole" in line]
    assert "plain-profile" in reason
    assert not any(SKIPPED in line for line in log)


def test_a_listing_that_raises_runs_the_whole_marker_with_the_error_and_is_not_no_tests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base = changes_no_test(tmp_path)

    def unreadable(tree: Path, ref: str) -> list[tuple[str, str]]:
        raise OSError("the tree cannot be read")

    monkeypatch.setattr(wiring, "touched_tests", unreadable)
    ran = Ran()
    log: list[str] = []
    gate = session(tmp_path, ran, log=log)

    gate.run(cwd=repo, base=base)

    assert ran.commands == [WHOLE]
    assert any("could not be listed" in line and "the tree cannot be read" in line for line in log)
    assert not any(SKIPPED in line for line in log)
    assert gate.result is not None
    assert not gate.result.ran_no_tests


def test_a_run_with_no_base_runs_the_whole_marker(tmp_path: Path) -> None:
    repo, _ = changes_no_test(tmp_path)
    ran = Ran()
    log: list[str] = []
    gate = session(tmp_path, ran, log=log)

    gate.run(cwd=repo, base=None)

    assert ran.commands == [WHOLE]
    assert any("runs whole" in line and "base" in line for line in log)
    assert gate.result is not None
    assert not gate.result.ran_no_tests


def test_under_full_the_whole_marker_runs_for_a_unit_that_added_one_test(tmp_path: Path) -> None:
    repo, base = adds_one_test(tmp_path)
    ran = Ran()

    log: list[str] = []

    session(tmp_path, ran, log=log, scope=Tier2UnitScope.FULL).run(cwd=repo, base=base)

    assert ran.commands == [WHOLE]
    assert any("runs whole" in line and "full" in line for line in log)
