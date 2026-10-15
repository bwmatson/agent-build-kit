"""A tier 2 run leaves the held splits out through the one selection, parks the ones that
hold a test it would have run, never reports that as a complete pass, and names the split of
each failed test (spec: tier2-split-runs)."""

from __future__ import annotations

import subprocess
from collections.abc import Collection
from functools import partial
from pathlib import Path

from agent_build_kit.config import (
    REST_SPLIT,
    ProjectConfig,
    Tier2Split,
    Tier2UnitScope,
    known_runtime_names,
)
from agent_build_kit.pipeline.tier2 import (
    UNKNOWN_SPLIT,
    TestFailure,
    Tier2Result,
    build_selection,
    stack_lock,
)
from agent_build_kit.pipeline.wiring import Tier2Session
from agent_build_kit.profiles.python_uv import PROFILE
from tests.tier2_base_fakes import pytest_output
from tests.tier2_scope_fakes import PASSED, Ran, branch
from tests.tier2_scope_fakes import session as shared_session

MARKER = "local_stack"
# The repo's two declared splits, and `rest`, the tests in neither.
SPLITS = (
    Tier2Split(name="acp", marker="runtime_acp"),
    Tier2Split(name="claude_code", marker="runtime_claude_code"),
    Tier2Split(name=REST_SPLIT),
)
PLAIN = "tests/live/test_plain.py::test_plain"
CLAUDE = "tests/live/test_claude.py::test_claude"
ACP = "tests/live/test_acp.py::test_acp"
# The split marker each test of the fixture repository carries; all of them have the marker.
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
    `failing` failing. `cannot_list` makes every listing fail, and a listing names the tests
    of `parametrized` once per parameter, as pytest does."""

    def __init__(
        self,
        *,
        failing: Collection[str] = (),
        cannot_list: bool = False,
        parametrized: Collection[str] = (),
    ) -> None:
        super().__init__()
        self.failing, self.cannot_list = set(failing), cannot_list
        self.parametrized = set(parametrized)

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.calls.append((command, Path(str(kwargs["cwd"]))))
        chosen = selected(command[command.index("-m") + 1], [w for w in command if "::" in w])
        if "--collect-only" in command:
            if self.cannot_list:
                return subprocess.CompletedProcess(command, 2, "", "collection failed")
            names = [
                f"{test}[{p}]" if test in self.parametrized else test
                for test in chosen
                for p in (("a", "b") if test in self.parametrized else ("",))
            ]
            return subprocess.CompletedProcess(
                command, 0 if chosen else 5, "".join(f"{name}\n" for name in names), ""
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


def expected(held: Collection[str], *, only: str | None = None) -> str:
    """The `-m` text of a run that leaves out `held` or runs the split `only` alone."""
    return PROFILE.expression(MARKER, build_selection(MARKER, SPLITS, held=held, only=only))


session = partial(shared_session, splits=SPLITS)


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


def test_with_acp_held_every_command_leaves_it_out_and_the_split_is_parked(
    tmp_path: Path,
) -> None:
    ran = Groups()
    gate, repo, base = whole_run(tmp_path, ran, held=["acp"])

    ok, _ = gate.run(cwd=repo, base=base)

    assert ok
    assert gate.result is not None
    assert gate.result.parked == ["acp"]
    [command] = ran.runs
    assert expression_of(command) == expected(["acp"])
    assert "runtime_acp" in expression_of(command)


def test_the_held_split_is_listed_under_the_opposite_expression(tmp_path: Path) -> None:
    ran = Groups()
    gate, repo, base = whole_run(tmp_path, ran, held=["acp"])

    gate.run(cwd=repo, base=base)

    [listing] = ran.listings
    assert expression_of(listing) == expected([], only="acp")


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

    gate = session(tmp_path, ran, held=["acp"])
    gate.run(cwd=repo, base=base)

    assert gate.result is not None
    assert gate.result.parked == ["acp"]
    acp_expression = expected([], only="acp")
    [listing] = [c for c in ran.listings if expression_of(c) == acp_expression]
    assert ACP in listing
    assert CLAUDE not in listing


def test_a_held_split_with_no_own_test_parks_nothing_and_the_run_is_complete(
    tmp_path: Path,
) -> None:
    # The acp test is in the repository but is not one the unit added or changed.
    repo, base = only_plain_changed(tmp_path)
    ran = Groups()
    gate = session(tmp_path, ran, held=["acp"])

    ok, snapshot = gate.run(cwd=repo, base=base)

    assert ok
    assert gate.result is not None
    assert gate.result.parked == []
    assert [expression_of(command) for command in ran.runs] == [expected(["acp"])]
    assert "parked" not in snapshot


# --- a parked run is not a complete pass -------------------------------------------------


def test_a_result_with_a_parked_runtime_names_it_in_the_snapshot_and_not_as_a_pass(
    tmp_path: Path,
) -> None:
    gate, repo, base = whole_run(tmp_path, Groups(), held=["acp"])

    _, snapshot = gate.run(cwd=repo, base=base)

    [result_line] = [line for line in snapshot.splitlines() if line.startswith("- **Result:**")]
    assert "parked" in result_line
    assert "acp" in result_line


def test_a_parked_group_with_nothing_else_to_run_runs_no_command_and_takes_no_lock(
    tmp_path: Path,
) -> None:
    repo, base = only_acp_changed(tmp_path)
    ran = Groups()
    gate = session(tmp_path, ran, held=["acp"], timeout=0.1)

    with stack_lock(gate.lock, timeout=1, holder="another/1"):
        gate.run(cwd=repo, base=base)

    assert ran.runs == []
    assert gate.result is not None
    assert gate.result.parked == ["acp"]


def test_a_parametrized_parked_test_is_still_nothing_else_to_run(tmp_path: Path) -> None:
    repo, base = only_acp_changed(tmp_path)
    ran = Groups(parametrized=[ACP])
    gate = session(tmp_path, ran, held=["acp"], timeout=0.1)

    with stack_lock(gate.lock, timeout=1, holder="another/1"):
        gate.run(cwd=repo, base=base)

    assert ran.runs == []
    assert gate.result is not None
    assert gate.result.parked == ["acp"]


def test_a_parked_test_in_a_project_is_still_nothing_else_to_run(tmp_path: Path) -> None:
    repo, base = branch(
        tmp_path,
        {"api/tests/live/test_acp.py": EDITED.format(name="acp")},
        base_files={f"api/{name}": text for name, text in FILES.items()},
    )
    ran = Groups()
    gate = session(tmp_path, ran, held=["acp"], timeout=0.1, projects=[ProjectConfig(path="api")])

    with stack_lock(gate.lock, timeout=1, holder="another/1"):
        gate.run(cwd=repo, base=base)

    assert ran.runs == []
    assert gate.result is not None
    assert gate.result.parked == ["acp"]


def test_a_listing_that_fails_parks_the_group_and_says_why(tmp_path: Path) -> None:
    log: list[str] = []
    gate, repo, base = whole_run(tmp_path, Groups(cannot_list=True), held=["acp"], log=log)

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
    assert {f.test: f.split for f in gate.result.failures} == {
        PLAIN: "rest",
        CLAUDE: "claude_code",
    }


def test_the_failures_of_one_command_are_listed_once_per_declared_split(tmp_path: Path) -> None:
    ran = Groups(failing=[PLAIN, CLAUDE])
    gate, repo, base = whole_run(tmp_path, ran)

    gate.run(cwd=repo, base=base)

    assert len(ran.listings) == len([s for s in SPLITS if s.marker])
    assert gate.result is not None
    assert {f.split for f in gate.result.failures} == {REST_SPLIT, "claude_code"}


def test_a_failure_in_a_project_is_attributed_to_its_group(tmp_path: Path) -> None:
    repo, base = branch(
        tmp_path,
        {"src/app.py": "x = 1\n"},
        base_files={f"api/{name}": text for name, text in FILES.items()},
    )
    ran = Groups(failing=[PLAIN, CLAUDE])
    gate = session(tmp_path, ran, scope=Tier2UnitScope.FULL, projects=[ProjectConfig(path="api")])

    gate.run(cwd=repo, base=base)

    assert gate.result is not None
    assert {f.test: f.split for f in gate.result.failures} == {
        f"api/{PLAIN}": "rest",
        f"api/{CLAUDE}": "claude_code",
    }


def test_a_failure_whose_group_cannot_be_found_is_unknown_and_is_not_classified(
    tmp_path: Path,
) -> None:
    ran = Groups(failing=[CLAUDE], cannot_list=True)
    gate, repo, base = whole_run(tmp_path, ran)

    gate.run(cwd=repo, base=base)

    assert gate.result is not None
    assert [f.split for f in gate.result.failures] == [UNKNOWN_SPLIT]
    assert gate.verdict is None or gate.verdict.pre_existing == []
    assert [where for _, where in ran.calls if where != repo] == []


def test_the_base_rerun_of_a_failed_test_keeps_the_expression_of_the_run(
    tmp_path: Path,
) -> None:
    ran = Groups(failing=[PLAIN])
    gate, repo, base = whole_run(tmp_path, ran, held=["acp"])

    gate.run(cwd=repo, base=base)

    [rerun] = [command for command, where in ran.calls if where != repo and "-m" in command]
    assert expression_of(rerun) == expected(["acp"])
    assert PLAIN in rerun


# --- a repo that cannot leave a runtime out, and a run of one group ----------------------


def test_a_repo_running_tier_2_through_its_dev_stack_script_runs_whole_and_says_so(
    tmp_path: Path,
) -> None:
    script = "scripts/dev-stack.sh"
    repo, base = branch(tmp_path, SOURCE, base_files={**FILES, script: "#!/bin/sh\n"})
    ran = Ran(PASSED)
    log: list[str] = []

    session(tmp_path, ran, log=log, dev_stack=script, held=["acp"]).run(cwd=repo, base=base)

    assert ran.commands == [[script, "up"], [script, "test"], [script, "down"]]
    [why] = [line for line in log if "cannot leave" in line]
    assert "acp" in why


def test_a_run_limited_to_one_split_runs_only_that_splits_selection(tmp_path: Path) -> None:
    ran = Groups(failing=[ACP])
    gate, repo, base = whole_run(tmp_path, ran, only="acp")

    gate.run(cwd=repo, base=base)

    # The head run and the base re-run of the failed test, each under the limited selection.
    assert len(ran.runs) == 2
    assert [expression_of(c) for c in ran.runs] == [expected([], only="acp")] * len(ran.runs)
    assert gate.result is not None
    assert [f.split for f in gate.result.failures] == ["acp"]


def test_a_held_split_is_left_out_by_the_marker_the_repo_declared_for_it(tmp_path: Path) -> None:
    splits = (Tier2Split(name="acp", marker="slow_acp"), Tier2Split(name="rest"))
    ran = Groups()
    repo, base = branch(tmp_path, SOURCE, base_files=FILES)
    gate = session(tmp_path, ran, scope=Tier2UnitScope.FULL, held=["acp"], splits=splits)

    gate.run(cwd=repo, base=base)

    [command] = ran.runs
    assert expression_of(command) == "local_stack and not slow_acp"
    assert "runtime_acp" not in " ".join(command)


def test_with_every_split_held_nothing_runs_and_no_expression_is_built(tmp_path: Path) -> None:
    ran = Groups()
    log: list[str] = []
    held = [split.name for split in SPLITS]
    gate, repo, base = whole_run(tmp_path, ran, held=held, log=log)

    ok, _ = gate.run(cwd=repo, base=base)

    assert ok
    assert ran.commands == []
    assert gate.result is not None
    assert gate.result.ran_no_tests
    assert any("every split is held" in line for line in log)


def test_a_run_limited_to_rest_leaves_every_declared_split_out(tmp_path: Path) -> None:
    ran = Groups(failing=[PLAIN])
    gate, repo, base = whole_run(tmp_path, ran, only=REST_SPLIT)

    gate.run(cwd=repo, base=base)

    # The head run and the base re-run of the failed test, each under the limited selection.
    assert len(ran.runs) == 2
    assert [expression_of(c) for c in ran.runs] == [expected([], only=REST_SPLIT)] * len(ran.runs)
    assert gate.result is not None
    assert [f.split for f in gate.result.failures] == [REST_SPLIT]


# --- a held `rest`, and a result stored with the older key -------------------------------


def test_a_held_rest_is_parked_when_tests_belong_to_none_of_the_splits(tmp_path: Path) -> None:
    ran = Groups()
    gate, repo, base = whole_run(tmp_path, ran, held=[REST_SPLIT])

    gate.run(cwd=repo, base=base)

    assert gate.result is not None
    assert gate.result.parked == [REST_SPLIT]
    [command] = ran.runs
    assert expression_of(command) == expected([REST_SPLIT])


def test_a_held_rest_parks_nothing_when_every_own_test_is_in_a_split(tmp_path: Path) -> None:
    repo, base = only_acp_changed(tmp_path)
    ran = Groups()
    gate = session(tmp_path, ran, held=[REST_SPLIT])

    gate.run(cwd=repo, base=base)

    assert gate.result is not None
    assert gate.result.parked == []
    assert [expression_of(command) for command in ran.runs] == [expected([REST_SPLIT])]


def test_a_failure_stored_with_the_older_group_key_reads_it_as_its_split() -> None:
    stored = {"test": CLAUDE, "line": "assert False", "group": "claude_code"}

    assert TestFailure.model_validate(stored).split == "claude_code"


def test_a_result_stored_with_failures_under_the_older_group_key_reads_their_splits() -> None:
    stored = {
        "sha": "abc1234",
        "passed": 0,
        "failed": 1,
        "skipped": 0,
        "duration_seconds": 1.0,
        "command": "pytest",
        "output": "",
        "failures": [{"test": ACP, "line": "assert False", "group": "acp"}],
    }

    [failure] = Tier2Result.model_validate(stored).failures

    assert failure.split == "acp"


# --- the groups a run executes, which the open-fix gate asks --------------------


def test_the_groups_a_run_executes_leave_out_the_blocked_runtimes(tmp_path: Path) -> None:
    gate = session(tmp_path, Groups(), scope=Tier2UnitScope.FULL, held=["acp"])

    groups = gate.runtimes()

    assert groups[0] == "base"
    assert "acp" not in groups
    assert set(groups[1:]) == known_runtime_names() - {"acp"}


def test_the_groups_a_run_executes_are_every_one_when_nothing_is_blocked(tmp_path: Path) -> None:
    gate = session(tmp_path, Groups(), scope=Tier2UnitScope.FULL)

    groups = gate.runtimes()

    assert groups[0] == "base"
    assert set(groups[1:]) == known_runtime_names()
    assert "acp" in groups


def test_a_run_limited_to_one_group_executes_only_that_group(tmp_path: Path) -> None:
    only_acp = session(tmp_path, Groups(), scope=Tier2UnitScope.FULL, only="acp")
    only_base = session(tmp_path, Groups(), scope=Tier2UnitScope.FULL, only="base")

    assert only_acp.runtimes() == ("acp",)
    assert only_base.runtimes() == ("base",)


def test_one_call_limited_to_a_group_runs_only_its_expression_and_the_next_call_runs_whole(
    tmp_path: Path,
) -> None:
    ran = Groups()
    gate, repo, base = whole_run(tmp_path, ran)

    gate.run(cwd=repo, base=base, only="acp")

    [command] = ran.runs
    assert expression_of(command) == expected([], only="acp")
    assert gate.result is not None and gate.result.only == "acp"

    gate.run(cwd=repo, base=base)

    assert [expression_of(c) for c in ran.runs[1:]] == [MARKER]
    assert gate.result.only == ""


def test_a_call_limited_to_a_group_that_is_still_blocked_parks_it_without_running_or_locking(
    tmp_path: Path,
) -> None:
    ran = Groups()
    gate, repo, base = whole_run(tmp_path, ran, held=["acp"], timeout=0.1)

    with stack_lock(gate.lock, timeout=1, holder="another/1"):
        ok, _ = gate.run(cwd=repo, base=base, only="acp")

    assert ok
    assert ran.commands == []
    assert gate.result is not None and gate.result.parked == ["acp"]
