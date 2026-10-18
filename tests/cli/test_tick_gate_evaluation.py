"""Each tick round evaluates every split that has a gate, before planning and the e2e-test
selection, and a dry run only reports (spec: split-gate-usage).

The gate is a real command, a small script that counts its runs, so the round reaches it
through the same process boundary a configured gate does."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e_holds import SOURCE_GATE, repo_holds, write_hold
from agent_build_kit.pipeline.pause import is_paused
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import RUNNING
from tests.factories import stored_unit
from tests.parked_split_support import installation, stub_round

pytestmark = pytest.mark.usefixtures("scripted_engine")

SCRIPT = """\
import sys
from pathlib import Path

with Path(sys.argv[1]).open("a") as runs:
    runs.write("run\\n")
print("quota spent")
sys.exit(int(sys.argv[2]))
"""

TASKS = (
    "# Tasks\n\n## 1. [app] [unit-test] Register the marker\n\n"
    "- [ ] 1.1 Test: it\n- [ ] 1.2 Make it\n"
)


class Probe:
    """A gate command that exits `code` printing `quota spent`, and counts how often it ran."""

    def __init__(self, directory: Path, name: str, code: int) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        script = directory / f"{name}.py"
        script.write_text(SCRIPT)
        self.counter = directory / f"{name}.runs"
        self.argv = [sys.executable, str(script), str(self.counter), str(code)]

    @property
    def runs(self) -> int:
        return len(self.counter.read_text().splitlines()) if self.counter.exists() else 0


def installed(tmp_path: Path, gates: dict[str, Probe], **overrides: Any) -> Installation:
    """`acp` and `claude_code` declared; those named in `gates` carry a command gate."""
    command = {name: {"command": probe.argv} for name, probe in gates.items()}
    return installation(
        tmp_path,
        acp=None,
        gate=command.get("acp"),
        claude_code_gate=command.get("claude_code"),
        **overrides,
    )


def round_of(inst: Installation, *, submit: bool = False) -> list[str]:
    ready = cli.run_round(
        inst, UnitStore(inst.state_dir / "units.json"), building=(), only=frozenset(), submit=submit
    )
    return [unit.id for unit in ready]


def held_now(inst: Installation) -> dict[str, Any]:
    return repo_holds(inst.config, inst.repo("app"), inst.state_dir).held


@pytest.fixture(autouse=True)
def stubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_round(monkeypatch)


@pytest.mark.parametrize("runtime", ["claude_code", "acp"])
def test_a_round_holds_a_gated_split_whichever_runtime_the_pipeline_builds_on(
    tmp_path: Path, runtime: str
) -> None:
    probe = Probe(tmp_path / "bin", "acp", 3)
    extra = {} if runtime == "claude_code" else {"runtimes": {"acp": {"command": ["agent", "acp"]}}}
    inst = installed(tmp_path, {"acp": probe}, runtime=runtime, **extra)

    round_of(inst)

    hold = held_now(inst).get("acp")
    assert hold is not None
    assert hold.source == SOURCE_GATE
    assert hold.reason == "quota spent"
    assert hold.until is not None and hold.until > datetime.now(UTC)
    assert probe.runs == 1


def test_a_round_evaluates_every_split_that_has_a_gate_and_leaves_the_rest(
    tmp_path: Path,
) -> None:
    acp, claude_code = Probe(tmp_path / "bin", "acp", 3), Probe(tmp_path / "bin", "cc", 0)
    inst = installed(tmp_path, {"acp": acp, "claude_code": claude_code})

    round_of(inst)

    assert (acp.runs, claude_code.runs) == (1, 1)
    assert set(held_now(inst)) == {"acp"}


def test_a_split_with_no_gate_is_not_touched(tmp_path: Path) -> None:
    probe = Probe(tmp_path / "bin", "acp", 3)
    inst = installed(tmp_path, {"acp": probe})
    write_hold(
        inst.state_dir,
        "claude_code",
        reason="by hand",
        source="command",
        by="someone",
        now=datetime.now(UTC) - timedelta(hours=1),
    )

    round_of(inst)

    assert "acp" in held_now(inst)
    assert held_now(inst)["claude_code"].reason == "by hand"


def test_the_evaluation_comes_before_planning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installed(tmp_path, {"acp": Probe(tmp_path / "bin", "acp", 3)})
    seen: list[set[str]] = []
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: seen.append(set(held_now(inst))))

    round_of(inst)

    assert seen == [{"acp"}]


def test_a_round_whose_only_gate_is_cached_runs_no_command(tmp_path: Path) -> None:
    probe = Probe(tmp_path / "bin", "acp", 3)
    inst = installed(tmp_path, {"acp": probe})

    round_of(inst)
    round_of(inst)

    assert probe.runs == 1
    assert "acp" in held_now(inst)


def test_a_dry_run_says_what_it_would_hold_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installed(tmp_path, {"acp": Probe(tmp_path / "bin", "acp", 3)})
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    monkeypatch.chdir(inst.root)
    UnitStore(inst.state_dir / "units.json").upsert([stored_unit("feature/1", change="feature")])
    capsys.readouterr()

    assert cli.cmd_tick(argparse.Namespace(dry_run=True), inst) == 0

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "would hold: acp" in out
    assert "quota spent" in out
    assert held_now(inst) == {}
    written = {path.name for path in inst.state_dir.iterdir()}
    assert not any(name.startswith("e2e-held") for name in written)
    assert "gate-usage.json" not in written


def test_a_dry_run_says_what_it_would_lift_and_leaves_the_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installed(tmp_path, {"acp": Probe(tmp_path / "bin", "acp", 0)})
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    monkeypatch.chdir(inst.root)
    UnitStore(inst.state_dir / "units.json").upsert([stored_unit("feature/1", change="feature")])
    write_hold(
        inst.state_dir,
        "acp",
        reason="quota spent",
        source=SOURCE_GATE,
        by="gate evaluation",
        until=datetime.now(UTC) + timedelta(hours=1),
        now=datetime.now(UTC) - timedelta(minutes=30),
    )
    capsys.readouterr()

    assert cli.cmd_tick(argparse.Namespace(dry_run=True), inst) == 0

    out = capsys.readouterr().out
    assert "would lift: acp" in out
    assert "acp" in held_now(inst)


def test_a_unit_already_running_is_not_interrupted_by_a_hold_written_meanwhile(
    tmp_path: Path,
) -> None:
    inst = installed(tmp_path, {"acp": Probe(tmp_path / "bin", "acp", 3)})
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([stored_unit("running/1", change="running")])
    store.set_state("running/1", RUNNING, branch="spec/running/1")

    cli.run_round(
        inst, store, building={"running/1"}, started={"running/1"}, only=frozenset(), submit=False
    )

    assert "acp" in held_now(inst)
    assert store.get("running/1").state == RUNNING


def test_a_gate_over_its_threshold_pauses_nothing_on_a_bring_your_own_model_runtime(
    tmp_path: Path,
) -> None:
    inst = installed(
        tmp_path,
        {"acp": Probe(tmp_path / "bin", "acp", 3)},
        runtime="acp",
        runtimes={"acp": {"command": ["agent", "acp"]}},
    )
    change = inst.changes_dir / "feature"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text(TASKS)
    UnitStore(inst.state_dir / "units.json").upsert([stored_unit("feature/1", change="feature")])

    ready = round_of(inst, submit=True)

    assert "acp" in held_now(inst)
    assert ready == ["feature/1"]
    assert is_paused(inst.state_dir / "paused.json") is None
    assert not (inst.state_dir / "paused.json").exists()
