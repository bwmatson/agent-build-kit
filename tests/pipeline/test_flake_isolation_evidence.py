"""Each serial rerun keeps its own evidence in the failing run's bundle, and a flake, a storm and a
pre-existing failure point at it (spec: test-failure-evidence).

Unit-test runs over the fake machine of `tests/failure_bundle_fakes.py`, which answers as the
processes would. The records are read back from their files as they are written. A row written
before the evidence existed is a JSON line without its three fields.
"""

from __future__ import annotations

import contextlib
import json
import shlex
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import Flake, FlakeFound, flake_record
from agent_build_kit.pipeline.run_log import RUNS_KEPT
from agent_build_kit.pipeline.untouched_failures import preexisting_record
from agent_build_kit.pipeline.wiring import build_on_preexisting, build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from tests.conftest import make_installation
from tests.e2e_gate_fakes import Planning
from tests.e2e_wait_fakes import OLD, verdict_of
from tests.failure_bundle_fakes import START, BundleMachine, BundleProfile, storms
from tests.pipeline.test_run_log_load_flag import CPUS, THRESHOLD, sampling
from tests.redaction_fakes import SECRET, known

RERUN_FILES = {"output.txt", "context.json", "machine.json", "worktree.json"}


def unit_test_of(scratch: Path, machine: BundleMachine, directory: Path):
    loads = iter(range(1, 100))
    clock = iter(START + timedelta(seconds=10 * n) for n in range(100))
    return build_unit_test(
        profile=cast(ToolchainProfile, BundleProfile()),
        run=machine,
        changed=lambda *a: ["tests/test_one.py"],
        failures_dir=directory,
        now=lambda: next(clock),
        machine=lambda: {"load": [float(next(loads))] * 3},
    )


def flakes_of(scratch: Path, directory: Path, *, reruns: list[int]) -> tuple[Flake, ...]:
    with pytest.raises(FlakeFound) as found:
        unit_test_of(scratch, BundleMachine(scratch, reruns=reruns), directory)(
            cwd=scratch, base="main"
        )
    return found.value.flakes


def only_bundle(directory: Path) -> Path:
    (bundle,) = directory.iterdir()
    return bundle


def read(path: Path) -> dict:
    return json.loads(path.read_text())


# --- the reruns in the bundle ---------------------------------------------------------


def test_each_rerun_keeps_its_command_output_exit_times_and_its_own_machine_and_worktree(
    scratch: Path, tmp_path: Path
) -> None:
    directory = tmp_path / "bundles"
    machine = BundleMachine(scratch, reruns=[0, 0])

    with pytest.raises(FlakeFound):
        unit_test_of(scratch, machine, directory)(cwd=scratch, base="main")

    reruns = only_bundle(directory) / "reruns"
    assert sorted(path.name for path in reruns.iterdir()) == ["1", "2"]
    serial = [c for c in machine.commands if any("::" in argument for argument in c)]
    for number, command in enumerate(serial, start=1):
        folder = reruns / str(number)
        assert {path.name for path in folder.iterdir()} == RERUN_FILES
        assert (folder / "output.txt").read_text().strip() == "1 passed"
        context = read(folder / "context.json")
        assert context["command"] == shlex.join(command)
        assert context["exit"] == 0
        assert datetime.fromisoformat(context["started"]) < datetime.fromisoformat(context["ended"])
        assert context["seconds"] > 0
        assert "load" in read(folder / "machine.json")["start"]
        assert "load" in read(folder / "machine.json")["end"]
        worktree = read(folder / "worktree.json")
        assert "status" in worktree["before"]
        assert "status" in worktree["after"]
        assert {"vanished", "appeared"} <= set(worktree), "as the run's own worktree lines"


def test_a_rerun_that_fails_is_kept_too_and_is_not_reduced_to_its_exit(
    scratch: Path, tmp_path: Path
) -> None:
    directory = tmp_path / "bundles"

    passed, _ = unit_test_of(scratch, BundleMachine(scratch, reruns=[1, 1]), directory)(
        cwd=scratch, base="main"
    )

    assert not passed
    first = only_bundle(directory) / "reruns" / "1"
    assert read(first / "context.json")["exit"] == 1
    assert (first / "output.txt").read_text().strip() == "1 passed"


def test_a_rerun_s_files_are_redacted_like_the_rest_of_the_bundle(
    scratch: Path, tmp_path: Path
) -> None:
    directory = tmp_path / "bundles"

    class Leaking(BundleMachine):
        def __call__(self, command: list[str], **kwargs: object):
            done = super().__call__(command, **kwargs)
            if any("::" in argument for argument in command):
                done.stdout = f"token={SECRET}\n"
            return done

    with known():
        with pytest.raises(FlakeFound):
            unit_test_of(scratch, Leaking(scratch, reruns=[0, 0]), directory)(
                cwd=scratch, base="main"
            )

    files = [path for path in (only_bundle(directory) / "reruns").rglob("*") if path.is_file()]
    assert files
    for path in files:
        assert SECRET not in path.read_text(), path


# --- the records ------------------------------------------------------------------------


def test_a_flake_row_names_the_bundle_the_start_and_the_conditions_and_keeps_its_clipped_fields(
    scratch: Path, tmp_path: Path
) -> None:
    directory = tmp_path / "bundles"

    flakes = flakes_of(scratch, directory, reruns=[0, 0])

    bundle = only_bundle(directory)
    machine = read(bundle / "machine.json")
    assert len(flakes) == 5
    for flake in flakes:
        assert Path(flake.evidence) == bundle
        assert flake.ran_at == START, "when the first run started, not the verdict's time"
        assert flake.conditions["load_before"] == machine["start"]["load"][0]
        assert cast(float, flake.conditions["load_after"]) > cast(
            float, flake.conditions["load_before"]
        )
        assert flake.conditions["rerun_exits"] == [0, 0]
        seconds = cast(list[float], flake.conditions["rerun_seconds"])
        assert len(seconds) == 2 and all(taken > 0 for taken in seconds)
        assert "short test summary info" in flake.output, "the clipped output stays"
        assert flake.failure, "and the test's own section"


def test_the_bundle_is_pointed_at_so_it_is_kept(scratch: Path, tmp_path: Path) -> None:
    installation = make_installation(scratch)
    directory = tmp_path / "bundles"
    unit_test = unit_test_of(
        scratch, BundleMachine(scratch, reruns=[0, 0] * (RUNS_KEPT + 2)), directory
    )
    with pytest.raises(FlakeFound) as found:
        unit_test(cwd=scratch, base="main")
    (flake, *_) = found.value.flakes
    assert Path(flake.evidence).parent == directory
    flake_record(installation).append(flake)

    for _ in range(RUNS_KEPT + 1):
        with pytest.raises(FlakeFound):
            unit_test(cwd=scratch, base="main")

    assert Path(flake.evidence).is_dir(), "the record's bundle outlives the newest ones"
    assert len(list(directory.iterdir())) == RUNS_KEPT + 1, "and the newest are kept beside it"


def test_a_second_run_of_the_same_round_that_storms_again_is_isolated_and_recorded_again(
    scratch: Path, tmp_path: Path
) -> None:
    installation = make_installation(scratch, global_limits=dict(max_flakes_per_run=2))
    machine = BundleMachine(scratch, reruns=[0, 0, 0, 0])
    unit_test = unit_test_of(scratch, machine, tmp_path / "bundles")

    for _ in range(2):
        passed, _ = unit_test(cwd=scratch, base="main")
        assert passed

    assert len(storms(installation)) == 2
    serial = [c for c in machine.commands if any("::" in argument for argument in c)]
    assert len(serial) == 4, "each run issued its own serial reruns"


def test_a_second_command_failing_the_stormed_tests_is_not_rerun_nor_recorded_again(
    scratch: Path, tmp_path: Path
) -> None:
    installation = make_installation(scratch, global_limits=dict(max_flakes_per_run=2))
    directory = tmp_path / "bundles"
    machine = BundleMachine(scratch, reruns=[0, 0])

    passed, _ = unit_test_of(scratch, machine, directory)(cwd=scratch, base="main")

    assert passed
    failing_runs = [
        c for c in machine.commands if c[-4:-1] == ["-q", "--durations=15", "--durations-min=3.0"]
    ]
    assert len(failing_runs) == 2, "the profile's two test commands both ran and failed"
    assert len(storms(installation)) == 1
    serial = [c for c in machine.commands if any("::" in argument for argument in c)]
    assert len(serial) == 2, "the reruns were issued once"
    assert len(list(directory.iterdir())) == 1, "the repeat of the same failure adds no bundle"


def test_a_row_written_before_the_evidence_existed_still_loads_with_it_empty(
    installation: Installation,
) -> None:
    old = {
        "test": "tests/test_a.py::test_x",
        "change": "",
        "command": "uv run pytest -n auto -q",
        "output": "FAILED tests/test_a.py::test_x\n",
        "failure": "",
        "at": "2026-03-01T09:30:00Z",
        "unit": "feature/1",
        "directory": "",
        "failing": False,
    }
    record = flake_record(installation)
    record.path.parent.mkdir(parents=True, exist_ok=True)
    record.path.write_text(json.dumps(old) + "\n")

    (row,) = record.entries()

    assert row.evidence == ""
    assert row.ran_at is None
    assert row.conditions == {}


def test_a_storm_row_names_the_bundle_the_start_and_the_conditions(
    scratch: Path, tmp_path: Path
) -> None:
    installation = make_installation(scratch, global_limits=dict(max_flakes_per_run=2))
    directory = tmp_path / "bundles"

    passed, _ = unit_test_of(scratch, BundleMachine(scratch, reruns=[0, 0]), directory)(
        cwd=scratch, base="main"
    )

    assert passed
    (row,) = storms(installation)
    assert Path(row["evidence"]) == only_bundle(directory)
    assert datetime.fromisoformat(row["ran_at"]) == START
    assert row["conditions"]["rerun_exits"] == [0, 0]
    assert row["conditions"]["load_after"] > row["conditions"]["load_before"]
    assert row["failures"], "its clipped failures stay"


def test_a_pre_existing_row_carries_the_evidence_of_its_verdict(tmp_path: Path) -> None:
    planning = Planning(tmp_path)
    planning.open_fix(OLD)
    unit = planning.store.get("feature/1")
    verdict = verdict_of(old=(OLD,)).model_copy(
        update={
            "evidence": "runs/e2e-output/feature-01-20260301-093000",
            "ran_at": datetime(2026, 3, 1, 9, 20, tzinfo=UTC),
            "conditions": {"load_before": 3.0, "load_after": 4.5},
        }
    )

    build_on_preexisting(planning.store, planning.installation, log=lambda m: None)(
        unit, verdict, verdict.pre_existing[0], wait=False
    )

    recorded = preexisting_record(planning.installation).entries()[-1]
    assert recorded.evidence == verdict.evidence
    assert recorded.ran_at == verdict.ran_at
    assert recorded.conditions == verdict.conditions
    assert recorded.base_output, "its clipped fields stay"


# --- ids pytest cannot find ---------------------------------------------------------------

FAILED = [
    "test_one.py::test_plain",
    "test_one.py::TestGroup::test_method",
    "test_one.py::test_cases[2]",
    "test_two.py::test_other",
    "test_one.py::test_setup_error",
]
LOST = "test_one.py::test_cases[2]"


class NotFoundMachine(BundleMachine):
    """A serial rerun naming a test of `missing` ends as pytest's usage error does: the
    absolute path and names without the parametrization, and why on the next line."""

    def __init__(self, root: Path, *, missing: list[str], reruns: list[int]) -> None:
        super().__init__(root, reruns=reruns)
        self.missing = missing

    def __call__(self, command: list[str], **kwargs: object):
        if absent := [test for test in self.missing if test in command]:
            self.commands.append(command)
            lines = "".join(
                f"ERROR: not found: {self.root / test.split('[')[0]}\n"
                "(no match in any of [<Module test_one.py>])\n"
                for test in dict.fromkeys(absent)
            )
            return subprocess.CompletedProcess(command, 4, "", lines)
        return super().__call__(command, **kwargs)


def test_a_rerun_names_the_ids_left_out_in_its_evidence(scratch: Path, tmp_path: Path) -> None:
    directory = tmp_path / "bundles"
    machine = NotFoundMachine(scratch, missing=[LOST], reruns=[1, 1])

    passed, _ = unit_test_of(scratch, machine, directory)(cwd=scratch, base="main")

    assert not passed
    context = read(only_bundle(directory) / "reruns" / "1" / "context.json")
    assert context["left_out"] == [LOST]
    assert LOST not in context["command"]


def test_a_rerun_that_finds_none_of_its_ids_still_keeps_its_evidence(
    scratch: Path, tmp_path: Path
) -> None:
    directory = tmp_path / "bundles"
    machine = NotFoundMachine(scratch, missing=FAILED, reruns=[])

    passed, _ = unit_test_of(scratch, machine, directory)(cwd=scratch, base="main")

    assert not passed
    context = read(only_bundle(directory) / "reruns" / "1" / "context.json")
    assert context["left_out"] == FAILED
    assert context["exit"] == 4


# --- the class a failure that passes alone is given --------------------------------------

HIGH_LOAD = THRESHOLD * CPUS
IDLE_LOAD = 0.5
LIMIT = "Failed: Timeout >60.0s"
IN_USE = "OSError: [Errno 98] Address already in use"
SLOW = "tests/test_slow.py::test_slow_0"

# status, test id, the worker that ran it, why
Entry = tuple[str, str, str, str]


def xdist_output(entries: list[Entry]) -> str:
    """A `-n` run's console output for `entries`, in the order given in the short summary: the
    block of each failed test opens with the `[gwN]` line xdist writes."""

    def block(status: str, test: str, worker: str, reason: str) -> str:
        name = test.rsplit("::", 1)[-1]
        title = f"ERROR at setup of {name}" if status == "ERROR" else name
        return (
            f"_____ {title} _____\n[{worker}] linux -- Python 3.14.7 /env/bin/python\n"
            f"tests/test_x.py:3: in {name}\nE   {reason}\n"
        )

    parts = []
    for status, heading in (("ERROR", "ERRORS"), ("FAILED", "FAILURES")):
        chosen = [entry for entry in entries if entry[0] == status]
        if chosen:
            parts.append(f"===== {heading} =====\n" + "".join(block(*entry) for entry in chosen))
    summary = "".join(f"{status} {test} - {why}\n" for status, test, _, why in entries)
    parts.append(f"===== short test summary info =====\n{summary}{len(entries)} failed in 0.01s\n")
    return "\n".join(parts)


def hit(test: str = SLOW, worker: str = "gw0") -> Entry:
    return ("FAILED", test, worker, LIMIT)


def setup_errors(worker: str, count: int, module: str = "test_cases") -> list[Entry]:
    return [
        ("ERROR", f"tests/{module}.py::test_case_{worker}_{n:03}", worker, "RuntimeError: no db")
        for n in range(count)
    ]


class OutputMachine(BundleMachine):
    """The bundle machine whose parallel test run prints `output`."""

    def __init__(self, root: Path, output: str, *, reruns: list[int]) -> None:
        super().__init__(root, reruns=reruns)
        self.output = output

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        done = super().__call__(command, **kwargs)
        if done.returncode == 1 and not any("::" in argument for argument in command):
            return subprocess.CompletedProcess(command, 1, self.output, "")
        return done

    @property
    def reruns_made(self) -> list[list[str]]:
        return [c for c in self.commands if any("::" in argument for argument in c)]


class Classified:
    """One unit-test run over `OutputMachine`, its ledger and the installation it ran in."""

    def __init__(
        self, scratch: Path, tmp_path: Path, entries: list[Entry], *, reruns: list[int], load: float
    ) -> None:
        self.installation = make_installation(
            scratch,
            tests=dict(load_high_per_cpu=THRESHOLD),
            global_limits=dict(max_flakes_per_run=2),
        )
        self.machine = OutputMachine(scratch, xdist_output(entries), reruns=reruns)
        self.ledger = tmp_path / "test-runs.jsonl"
        clock = iter(START + timedelta(seconds=10 * n) for n in range(100))
        self.unit_test = build_unit_test(
            profile=cast(ToolchainProfile, BundleProfile()),
            run=self.machine,
            changed=lambda *a: ["tests/test_one.py"],
            failures_dir=tmp_path / "bundles",
            test_runs=self.ledger,
            installation=self.installation,
            now=lambda: next(clock),
            machine=sampling(load),
        )
        self.scratch = scratch

    def run(self) -> tuple[bool, str]:
        return self.unit_test(cwd=self.scratch, base="main")

    def recorded(self) -> list[Flake]:
        return flake_record(self.installation).entries()

    def ledger_detail(self) -> dict[str, bool]:
        """Whether each failed test of the run's ledger row is marked a consequence."""
        row = json.loads(self.ledger.read_text().splitlines()[0])
        return {entry["test"]: entry["consequence"] for entry in row["failed_detail"]}


def test_a_time_limit_hit_under_high_load_that_passes_alone_is_load_and_writes_no_fix_change(
    scratch: Path, tmp_path: Path
) -> None:
    run = Classified(scratch, tmp_path, [hit()], reruns=[0, 0], load=HIGH_LOAD)

    raised: FlakeFound | None = None
    passed = False
    try:
        passed, _ = run.run()
    except FlakeFound as found:
        raised = found

    assert raised is None, "a flake was raised, so a unit would wait on a fix change"
    assert passed
    (entry,) = run.recorded()
    assert (entry.test, entry.classification) == (SLOW, "load")
    assert entry.change == ""
    assert entry.conditions["load_high"] is True


def test_a_failure_on_a_shared_resource_on_an_idle_host_that_passes_alone_is_isolation(
    scratch: Path, tmp_path: Path
) -> None:
    entries: list[Entry] = [("FAILED", "tests/test_net.py::test_bind", "gw0", IN_USE)]
    run = Classified(scratch, tmp_path, entries, reruns=[0, 0], load=IDLE_LOAD)

    with pytest.raises(FlakeFound) as found:
        run.run()

    assert [(f.test, f.classification) for f in found.value.flakes] == [
        ("tests/test_net.py::test_bind", "isolation")
    ]


def test_errors_after_the_first_hit_of_a_worker_are_consequences_and_are_not_rerun_or_counted(
    scratch: Path, tmp_path: Path
) -> None:
    errors = setup_errors("gw0", 3)
    run = Classified(scratch, tmp_path, [hit(), *errors], reruns=[0, 0], load=HIGH_LOAD)

    passed, _ = run.run()

    assert passed
    consequences = {test for _, test, _, _ in errors}
    assert run.machine.reruns_made, "the hit itself was rerun"
    for rerun in run.machine.reruns_made:
        assert SLOW in rerun
        assert not consequences & set(rerun)
    assert storms(run.installation) == [], "four failures would be a storm over the limit of two"
    assert [entry.test for entry in run.recorded()] == [SLOW]
    assert run.ledger_detail() == {SLOW: False, **dict.fromkeys(consequences, True)}


def test_an_error_in_a_worker_with_no_earlier_hit_is_judged_as_before(
    scratch: Path, tmp_path: Path
) -> None:
    other = setup_errors("gw1", 1, "test_other")
    cascade = setup_errors("gw0", 2)
    run = Classified(scratch, tmp_path, [hit(), *cascade, *other], reruns=[0, 0], load=HIGH_LOAD)

    with contextlib.suppress(FlakeFound):
        run.run()

    assert run.machine.reruns_made, "the failed tests were rerun"
    for rerun in run.machine.reruns_made:
        assert other[0][1] in rerun and SLOW in rerun
        assert not {test for _, test, _, _ in cascade} & set(rerun)
    assert run.ledger_detail()[other[0][1]] is False


def test_six_hits_and_five_hundred_nineteen_setup_errors_after_them_write_no_fix_change(
    scratch: Path, tmp_path: Path
) -> None:
    workers = [f"gw{n}" for n in range(6)]
    hits = [hit(f"tests/test_slow.py::test_slow_{n}", worker) for n, worker in enumerate(workers)]
    errors = [
        error
        for n, worker in enumerate(workers)
        for error in setup_errors(worker, 87 if n < 3 else 86)
    ]
    assert len(errors) == 519
    run = Classified(scratch, tmp_path, [*hits, *errors], reruns=[0, 0], load=HIGH_LOAD)

    passed, _ = run.run()

    assert passed, "no FlakeFound, no FailedOnBase: nothing is waited on"
    assert sorted(entry.test for entry in run.recorded()) == sorted(test for _, test, _, _ in hits)
    assert {entry.classification for entry in run.recorded()} == {"load"}
    assert {entry.change for entry in run.recorded()} == {""}
    assert storms(run.installation) == []
    for rerun in run.machine.reruns_made:
        assert not [argument for argument in rerun if "test_cases" in argument]
