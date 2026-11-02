"""The change the regression agent writes carries the first failure's evidence in its `design.md`
(spec: regression-agent, test-failure-evidence): the test's recorded output, the conditions, the
ledger rows of the run, the bundle's `machine.json` and the bundle's path, so the cause can stand
on its own when a fix unit builds the change after the test no longer fails. The agent is a
stand-in that writes a canned change; no model runs.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.failure_evidence import EVIDENCE_HEADING
from agent_build_kit.pipeline.flakes import next_fix_name
from agent_build_kit.pipeline.regression_agent import FixOutcome
from agent_build_kit.pipeline.run_log import (
    TestRun,
    append_test_run,
    failure_bundles_dir,
    run_ledger_path,
    write_failure_bundle,
)
from agent_build_kit.runtimes import AgentRequest
from tests.failure_bundle_fakes import START
from tests.installation_leaks import ABSOLUTE_HOME_PATH
from tests.regression_agent_support import (
    FIX_THE_SOURCE,
    PROPOSAL,
    TASKS,
    TEST,
    UNDECIDED,
    Attempts,
    failure,
    group_tasks,
    refusal_of,
    run,
)
from tests.runtimes.stand_in import StandInRuntime

OUTPUT = "FAILED tests/test_widget.py::test_renders_the_label - assert 'a' == 'b'\n"
MACHINE: dict[str, object] = {"load": [11.5, 9.25, 7.0], "memory_available_kb": 123456, "cpus": 8}
CONDITIONS = {"load_before": 11.5, "load_after": 12.75, "rerun_exits": [0, 0]}
GOOD = {"proposal": PROPOSAL}


def a_run(unit: str, started: str, *, load_start: float, load_end: float, workers: str) -> TestRun:
    return TestRun(
        unit=unit,
        started=started,
        seconds=41.0,
        outcome="failed",
        failed=[TEST],
        load_start=load_start,
        load_end=load_end,
        workers=workers,
        tick="t1",
        units_running=[],
    )


def a_bundle(inst: Installation) -> Path:
    return write_failure_bundle(
        failure_bundles_dir(inst.state_dir),
        "feature/1",
        "feature",
        START,
        output=OUTPUT,
        context={"command": "uv run pytest -n auto -q"},
        machine=MACHINE,
        worktree={"status": [], "tests": [TEST]},
    )


def design_of(inst: Installation, name: str) -> str:
    return (inst.changes_dir / name / "design.md").read_text()


def evidence_of(inst: Installation, name: str) -> str:
    """The evidence section of the change's design.md: what follows its `Evidence` heading."""
    return design_of(inst, name).split("Evidence", 1)[1]


def test_the_design_records_the_output_and_the_conditions_of_the_first_failure(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, GOOD)

    outcome = run(
        installation,
        tmp_path,
        agent.runtime,
        failed=failure(output=OUTPUT, conditions=CONDITIONS, ran_at=START),
    )

    assert outcome == FixOutcome(change=name)
    evidence = evidence_of(installation, name)
    assert "assert 'a' == 'b'" in evidence
    assert "11.5" in evidence
    assert "12.75" in evidence
    assert "rerun_exits" in evidence


def test_the_design_keeps_what_the_agent_wrote_before_the_evidence(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, GOOD)

    run(installation, tmp_path, agent.runtime, failed=failure(ran_at=START))

    assert "The label is read too early." in design_of(installation, name)
    assert "Evidence" in design_of(installation, name)


def test_the_design_records_the_ledger_rows_of_the_run(
    installation: Installation, tmp_path: Path
) -> None:
    ledger = run_ledger_path(installation.state_dir)
    # The run started before its failing command did, as a real run does.
    began = (START - timedelta(seconds=10)).isoformat()
    append_test_run(
        ledger,
        a_run("feature/1", began, load_start=3.5, load_end=13.75, workers="auto"),
    )
    later = (START + timedelta(hours=1)).isoformat()
    append_test_run(ledger, a_run("feature/1", later, load_start=0.25, load_end=0.5, workers="3"))
    append_test_run(ledger, a_run("other/1", began, load_start=0.75, load_end=0.5, workers="5"))
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, GOOD)

    run(installation, tmp_path, agent.runtime, failed=failure(ran_at=START))

    evidence = evidence_of(installation, name)
    for field in ("load_start", "load_end", "workers"):
        assert field in evidence
    assert "13.75" in evidence
    assert "auto" in evidence
    assert "0.25" not in evidence, "another window of the same unit"
    assert "0.75" not in evidence, "the same window of another unit"


def test_the_prompt_holds_the_evidence_the_agent_is_told_to_read(
    installation: Installation, tmp_path: Path
) -> None:
    bundle = a_bundle(installation)
    append_test_run(
        run_ledger_path(installation.state_dir),
        a_run(
            "feature/1",
            (START - timedelta(seconds=10)).isoformat(),
            load_start=3.5,
            load_end=13.75,
            workers="auto",
        ),
    )
    agent = Attempts(installation, next_fix_name(installation, TEST), GOOD)

    run(
        installation,
        tmp_path,
        agent.runtime,
        failed=failure(output=OUTPUT, evidence=str(bundle), conditions=CONDITIONS, ran_at=START),
    )

    prompt = agent.runtime.requests[0].prompt
    assert "13.75" in prompt, "a ledger figure"
    assert "123456" in prompt, "a figure of the bundle's machine.json"
    assert "12.75" in prompt, "a condition"


def test_an_undecided_agents_change_carries_the_evidence_and_is_held(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, GOOD)
    agent.runtime.answer = f"{UNDECIDED}\n"

    outcome = run(installation, tmp_path, agent.runtime, failed=failure(ran_at=START))

    assert outcome.held
    assert "could not decide" in outcome.reason
    assert "assert 'a' == 'b'" in evidence_of(installation, name)


def test_a_failure_whose_evidence_is_not_a_bundle_names_no_bundle(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, GOOD)

    run(
        installation,
        tmp_path,
        agent.runtime,
        failed=failure(evidence="e2e-test split: rest\n", ran_at=START),
    )

    assert "Bundle of the failing run" not in design_of(installation, name)


def test_a_pruned_bundle_names_no_bundle(installation: Installation, tmp_path: Path) -> None:
    gone = failure_bundles_dir(installation.state_dir) / "pruned"
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, GOOD)

    run(installation, tmp_path, agent.runtime, failed=failure(evidence=str(gone), ran_at=START))

    assert "Bundle of the failing run" not in design_of(installation, name)


# Built from parts so this file holds no literal home path for the leak scan to find.
WORK = "/" + "home/someone/work"
MAC_WORK = "/" + "Users/someone/work"
TILDE = "~"


def test_the_section_names_no_home_directory(installation: Installation, tmp_path: Path) -> None:
    bundle = a_bundle(installation)
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, GOOD)
    leaky = f"FAILED {WORK}/tests/test_widget.py::test_renders_the_label\n"

    run(
        installation,
        tmp_path,
        agent.runtime,
        failed=failure(
            output=leaky,
            evidence=str(bundle),
            conditions={"cwd": WORK},
            ran_at=START,
        ),
    )

    section = evidence_of(installation, name)
    assert ABSOLUTE_HOME_PATH.search(section) is None
    assert f"{TILDE}/work/tests/test_widget.py" in section


def test_the_section_names_no_macos_home_directory(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, GOOD)
    leaky = f"FAILED {MAC_WORK}/tests/test_widget.py::test_renders_the_label\n"

    run(
        installation,
        tmp_path,
        agent.runtime,
        failed=failure(output=leaky, conditions={"cwd": MAC_WORK}, ran_at=START),
    )

    section = evidence_of(installation, name)
    assert "/" + "Users/" not in section
    assert f"{TILDE}/work/tests/test_widget.py" in section


def test_the_design_records_the_bundles_machine_and_its_path(
    installation: Installation, tmp_path: Path
) -> None:
    bundle = a_bundle(installation)
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, GOOD)

    run(installation, tmp_path, agent.runtime, failed=failure(evidence=str(bundle), ran_at=START))

    evidence = evidence_of(installation, name)
    assert bundle.relative_to(installation.state_dir).as_posix() in evidence
    assert str(installation.state_dir) not in evidence, "no absolute path in a committed file"
    assert "memory_available_kb" in evidence
    assert "123456" in evidence


def test_a_failure_with_no_bundle_names_no_bundle_path(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, GOOD)

    run(installation, tmp_path, agent.runtime, failed=failure(evidence="", ran_at=START))

    evidence = evidence_of(installation, name)
    assert "assert 'a' == 'b'" in evidence
    assert str(failure_bundles_dir(installation.state_dir)) not in evidence


def test_the_evidence_is_there_once_after_the_change_is_rewritten(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    refused = {"tasks": group_tasks(f"Test: rerun `{TEST}` until it fails.", FIX_THE_SOURCE)}
    agent = Attempts(installation, name, {**refused, **GOOD})
    first_attempt = agent.act

    def act(request: AgentRequest) -> None:
        if len(agent.runtime.requests) == 1:
            first_attempt(request)
            return
        # A real agent answering a refusal about tasks.md edits that file and leaves the design,
        # with the section the kit appended, as it was.
        tasks = installation.changes_dir / name / "tasks.md"
        tasks.write_text(TASKS.format(flag=" [contract]", priority="Priority: 1\n\n", test=TEST))

    agent.runtime = StandInRuntime(act=act)

    run(installation, tmp_path, agent.runtime, failed=failure(output=OUTPUT, ran_at=START))

    assert len(agent.runtime.requests) == 2
    assert refusal_of(agent.runtime.requests[1])
    design = design_of(installation, name)
    assert design.count(EVIDENCE_HEADING) == 1
    assert design.count("assert 'a' == 'b'") == 1


def test_the_prompt_tells_the_agent_the_evidence_must_stand_on_its_own(
    installation: Installation, tmp_path: Path
) -> None:
    agent = Attempts(installation, next_fix_name(installation, TEST), GOOD)

    run(installation, tmp_path, agent.runtime, failed=failure(ran_at=START))

    prompt = agent.runtime.requests[0].prompt
    assert "no longer fails" in prompt
    assert "stand on their own" in prompt
    assert "what would show the cause is gone" in prompt


def test_the_prompt_asks_whether_the_cause_is_load_a_shared_resource_or_code(
    installation: Installation, tmp_path: Path
) -> None:
    agent = Attempts(installation, next_fix_name(installation, TEST), GOOD)

    run(installation, tmp_path, agent.runtime, failed=failure(ran_at=START))

    prompt = agent.runtime.requests[0].prompt
    assert "shared resource" in prompt
    assert "T8a" in prompt
