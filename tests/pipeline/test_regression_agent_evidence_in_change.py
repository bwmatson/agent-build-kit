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
from agent_build_kit.pipeline.flakes import next_fix_name
from agent_build_kit.pipeline.regression_agent import FixOutcome
from agent_build_kit.pipeline.run_log import (
    TestRun,
    append_test_run,
    failure_bundles_dir,
    run_ledger_path,
    write_failure_bundle,
)
from tests.failure_bundle_fakes import START
from tests.regression_agent_support import (
    FIX_THE_SOURCE,
    PROPOSAL,
    TEST,
    Attempts,
    failure,
    group_tasks,
    refusal_of,
    run,
)

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
    append_test_run(
        ledger,
        a_run("feature/1", START.isoformat(), load_start=3.5, load_end=13.75, workers="auto"),
    )
    other = (START + timedelta(hours=1)).isoformat()
    append_test_run(ledger, a_run("other/1", other, load_start=0.25, load_end=0.5, workers="3"))
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, GOOD)

    run(installation, tmp_path, agent.runtime, failed=failure(ran_at=START))

    evidence = evidence_of(installation, name)
    for field in ("load_start", "load_end", "workers"):
        assert field in evidence
    assert "13.75" in evidence
    assert "auto" in evidence
    assert "0.25" not in evidence


def test_the_design_records_the_bundles_machine_and_its_path(
    installation: Installation, tmp_path: Path
) -> None:
    bundle = a_bundle(installation)
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, GOOD)

    run(installation, tmp_path, agent.runtime, failed=failure(evidence=str(bundle), ran_at=START))

    evidence = evidence_of(installation, name)
    assert str(bundle) in evidence
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
    agent = Attempts(installation, name, {**refused, **GOOD}, GOOD)

    run(installation, tmp_path, agent.runtime, failed=failure(output=OUTPUT, ran_at=START))

    assert len(agent.runtime.requests) == 2
    assert refusal_of(agent.runtime.requests[1])
    assert design_of(installation, name).count("assert 'a' == 'b'") == 1


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
