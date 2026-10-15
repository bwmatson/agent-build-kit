"""A tier 2 run leaves the blocked runtimes out through the one expression, parks the ones
that hold a test it would have run, never reports that as a complete pass, and names the
runtime group of each failed test (spec: tier2-runtime-parking)."""

from __future__ import annotations

import subprocess
from collections.abc import Collection
from pathlib import Path

from agent_build_kit.config import Tier2UnitScope
from agent_build_kit.pipeline.tier2 import (
    STATUS_CONTEXT,
    UNKNOWN_GROUP,
    post_status,
    stack_lock,
    tier2_selection,
)
from agent_build_kit.pipeline.wiring import Tier2Session
from tests.forges.stand_in import StandInForge
from tests.tier2_base_fakes import pytest_output
from tests.tier2_scope_fakes import PASSED, Ran, branch, session

MARKER = "local_stack"
PLAIN = "tests/live/test_plain.py::test_plain"
CLAUDE = "tests/live/test_claude.py::test_claude"
ACP = "tests/live/test_acp.py::test_acp"
# The runtime tag each test of the fixture repository carries; all of them have the marker.
TAGS: dict[str, tuple[str, ...]] = {PLAIN: (), CLAUDE: ("claude_code",), ACP: ("acp",)}
FILES = {
    f"tests/live/test_{name}.py": f"def test_{name}():\n    assert True\n"
    for name in ("plain", "claude", "acp")
}
EDITED = "def test_{name}():\n    assert 1 == 1\n"
SOURCE = {"src/app.py": "x = 1\n"}


class Tags(dict[str, bool]):
    """The names a marker expression is read with: the marker and the test's runtime tags."""

    def __init__(self, tags: Collection[str]) -> None:
        super().__init__()
        self.tags = {MARKER, *(f"runtime_{tag}" for tag in tags)}

    def __missing__(self, name: str) -> bool:
        return name in self.tags


def selected(expression: str, among: list[str]) -> list[str]:
    """The tests of the fixture repository `expression` selects, as pytest's `-m` would."""
    return [
        test
        for test, tags in TAGS.items()
        if eval(expression, {"__builtins__": {}}, Tags(tags))  # noqa: S307
        and (not among or test in among)
    ]


class Groups(Ran):
    """A pytest-shaped runner over the fixture repository: it lists what a command's `-m`
    expression selects when asked to collect, and otherwise runs it, the tests named in
    `failing` failing. `cannot_list` makes every listing fail."""

    def __init__(self, *, failing: Collection[str] = (), cannot_list: bool = False) -> None:
        super().__init__()
        self.failing, self.cannot_list = set(failing), cannot_list

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.calls.append((command, Path(str(kwargs["cwd"]))))
        chosen = selected(command[command.index("-m") + 1], [w for w in command if "::" in w])
        if "--collect-only" in command:
            if self.cannot_list:
                return subprocess.CompletedProcess(command, 2, "", "collection failed")
            return subprocess.CompletedProcess(
                command, 0 if chosen else 5, "".join(f"{test}\n" for test in chosen), ""
            )
        failed = {test: "assert False" for test in chosen if test in self.failing}
        passed = tuple(test for test in chosen if test not in failed)
        return subprocess.CompletedProcess(
            command, 1 if failed else 0, pytest_output(failed=failed, passed=passed), ""
        )

    @property
    def listings(self) -> list[list[str]]:
        return [command for command in self.commands if "--collect-only" in command]

    @property
    def runs(self) -> list[list[str]]:
        return [command for command in self.commands if "--collect-only" not in command]


def expression_of(command: list[str]) -> str:
    return command[command.index("-m") + 1]


def only_plain_changed(tmp_path: Path) -> tuple[Path, str]:
    """A branch whose one own test is the untagged one; the tagged ones are in the repo."""
    return branch(
        tmp_path,
        {"tests/live/test_plain.py": EDITED.format(name="plain")},
        base_files=FILES,
    )


def only_acp_changed(tmp_path: Path) -> tuple[Path, str]:
    return branch(tmp_path, {"tests/live/test_acp.py": EDITED.format(name="acp")}, base_files=FILES)


def whole_run(tmp_path: Path, ran: Groups, **kwargs) -> tuple[Tier2Session, Path, str]:
    repo, base = branch(tmp_path, SOURCE, base_files=FILES)
    return session(tmp_path, ran, scope=Tier2UnitScope.FULL, **kwargs), repo, base


# --- the groups that can run, and the ones parked ----------------------------------------


def test_with_acp_blocked_every_command_leaves_it_out_and_the_group_is_parked(
    tmp_path: Path,
) -> None:
    ran = Groups()
    gate, repo, base = whole_run(tmp_path, ran, blocked=["acp"])

    ok, _ = gate.run(cwd=repo, base=base)

    assert ok
    assert gate.result is not None
    assert gate.result.parked == ["acp"]
    [command] = ran.runs
    assert expression_of(command) == tier2_selection(MARKER, ["acp"]).expression
    assert "runtime_acp" in expression_of(command)


def test_the_blocked_group_is_listed_under_the_opposite_expression(tmp_path: Path) -> None:
    ran = Groups()
    gate, repo, base = whole_run(tmp_path, ran, blocked=["acp"])

    gate.run(cwd=repo, base=base)

    [listing] = ran.listings
    assert expression_of(listing) == tier2_selection(MARKER, [], only="acp").expression


def test_under_own_scope_the_listing_is_narrowed_to_the_units_own_tests(tmp_path: Path) -> None:
    repo, base = branch(
        tmp_path,
        {
            "tests/live/test_plain.py": EDITED.format(name="plain"),
            "tests/live/test_acp.py": EDITED.format(name="acp"),
        },
        base_files=FILES,
    )
    ran = Groups()

    gate = session(tmp_path, ran, blocked=["acp"])
    gate.run(cwd=repo, base=base)

    assert gate.result is not None
    assert gate.result.parked == ["acp"]
    [listing] = ran.listings
    assert ACP in listing
    assert CLAUDE not in listing


def test_a_blocked_runtime_with_no_own_test_parks_nothing_and_the_run_is_complete(
    tmp_path: Path,
) -> None:
    # The acp test is in the repository but is not one the unit added or changed.
    repo, base = only_plain_changed(tmp_path)
    ran = Groups()
    gate = session(tmp_path, ran, blocked=["acp"])

    ok, snapshot = gate.run(cwd=repo, base=base)

    assert ok
    assert gate.result is not None
    assert gate.result.parked == []
    assert [expression_of(command) for command in ran.runs] == [
        tier2_selection(MARKER, ["acp"]).expression
    ]
    assert "parked" not in snapshot


# --- a parked run is not a complete pass -------------------------------------------------


def test_a_result_with_a_parked_runtime_names_it_in_the_snapshot_and_not_as_a_pass(
    tmp_path: Path,
) -> None:
    gate, repo, base = whole_run(tmp_path, Groups(), blocked=["acp"])

    _, snapshot = gate.run(cwd=repo, base=base)

    [result_line] = [line for line in snapshot.splitlines() if line.startswith("- **Result:**")]
    assert "parked" in result_line
    assert "acp" in result_line


def test_the_status_description_of_a_parked_result_names_the_runtime_and_says_no_pass(
    tmp_path: Path,
) -> None:
    gate, repo, base = whole_run(tmp_path, Groups(), blocked=["acp"])
    gate.run(cwd=repo, base=base)
    assert gate.result is not None
    forge = StandInForge()

    post_status(forge, forge.repo_id(), gate.result)

    [posted] = forge.statuses
    assert posted["context"] == STATUS_CONTEXT
    assert "acp" in posted["description"]
    assert "parked" in posted["description"]
    assert "passed" not in posted["description"]


def test_a_parked_group_with_nothing_else_to_run_runs_no_command_and_takes_no_lock(
    tmp_path: Path,
) -> None:
    repo, base = only_acp_changed(tmp_path)
    ran = Groups()
    gate = session(tmp_path, ran, blocked=["acp"], timeout=0.1)

    with stack_lock(gate.lock, timeout=1, holder="another/1"):
        gate.run(cwd=repo, base=base)

    assert ran.runs == []
    assert gate.result is not None
    assert gate.result.parked == ["acp"]


def test_a_listing_that_fails_parks_the_group_and_says_why(tmp_path: Path) -> None:
    log: list[str] = []
    gate, repo, base = whole_run(tmp_path, Groups(cannot_list=True), blocked=["acp"], log=log)

    gate.run(cwd=repo, base=base)

    assert gate.result is not None
    assert gate.result.parked == ["acp"]
    [why] = [line for line in log if "acp" in line and "list" in line]
    assert "parked" in why


# --- a failure's runtime group -----------------------------------------------------------


def test_each_failed_test_carries_the_group_found_by_listing_it_under_each_tag(
    tmp_path: Path,
) -> None:
    ran = Groups(failing=[PLAIN, CLAUDE])
    gate, repo, base = whole_run(tmp_path, ran)

    gate.run(cwd=repo, base=base)

    assert gate.result is not None
    assert {f.test: f.group for f in gate.result.failures} == {
        PLAIN: "base",
        CLAUDE: "claude_code",
    }


def test_a_failure_whose_group_cannot_be_found_is_unknown_and_is_not_classified(
    tmp_path: Path,
) -> None:
    ran = Groups(failing=[CLAUDE], cannot_list=True)
    gate, repo, base = whole_run(tmp_path, ran)

    gate.run(cwd=repo, base=base)

    assert gate.result is not None
    assert [f.group for f in gate.result.failures] == [UNKNOWN_GROUP]
    assert gate.verdict is None or gate.verdict.pre_existing == []
    assert [where for _, where in ran.calls if where != repo] == []


def test_the_base_rerun_of_a_failed_test_keeps_the_expression_of_the_run(
    tmp_path: Path,
) -> None:
    ran = Groups(failing=[PLAIN])
    gate, repo, base = whole_run(tmp_path, ran, blocked=["acp"])

    gate.run(cwd=repo, base=base)

    [rerun] = [command for command, where in ran.calls if where != repo and "-m" in command]
    assert expression_of(rerun) == tier2_selection(MARKER, ["acp"]).expression
    assert PLAIN in rerun


# --- a repo that cannot leave a runtime out, and a run of one group ----------------------


def test_a_repo_running_tier_2_through_its_dev_stack_script_runs_whole_and_says_so(
    tmp_path: Path,
) -> None:
    script = "scripts/dev-stack.sh"
    repo, base = branch(tmp_path, SOURCE, base_files={**FILES, script: "#!/bin/sh\n"})
    ran = Ran(PASSED)
    log: list[str] = []

    session(tmp_path, ran, log=log, dev_stack=script, blocked=["acp"]).run(cwd=repo, base=base)

    assert ran.commands == [[script, "up"], [script, "test"], [script, "down"]]
    [why] = [line for line in log if "cannot leave" in line]
    assert "acp" in why


def test_a_run_limited_to_one_runtime_runs_only_that_groups_expression(tmp_path: Path) -> None:
    ran = Groups()
    gate, repo, base = whole_run(tmp_path, ran, only="acp")

    gate.run(cwd=repo, base=base)

    [command] = ran.runs
    assert expression_of(command) == tier2_selection(MARKER, [], only="acp").expression


def test_a_run_limited_to_the_base_group_leaves_every_runtime_out(tmp_path: Path) -> None:
    ran = Groups()
    gate, repo, base = whole_run(tmp_path, ran, only="base")

    gate.run(cwd=repo, base=base)

    [command] = ran.runs
    assert expression_of(command) == tier2_selection(MARKER, [], only="base").expression
