"""`abk redact-history`: the temporary command that redacts what was saved before the
boundaries existed (spec: secrets-never-reach-stored-or-posted-output)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.forges import github
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.run_log import run_log_dir
from agent_build_kit.pipeline.transcript import transcript_dir
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from tests.conftest import make_installation
from tests.factories import new_unit
from tests.forges.mock_host import MockHost, ok
from tests.ledger_lines import agent_line
from tests.redaction_fakes import known
from tests.scrub_store_support import pause

NAME = "STACK_KEY"
SECRET = "history-value-0001"
REPLACEMENT = "[redacted:" + NAME + "]"
SUFFIX = ".pre-redact"


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    monkeypatch.delenv("ABK_CONFIG", raising=False)
    installation = make_installation(
        tmp_path / "planning",
        verify={"env": {NAME: {"from": "literal", "value": SECRET}}},
    )
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    return installation


@pytest.fixture
def no_code_host() -> Iterator[MockHost]:
    """A code host that records every request; the command must send none."""
    host = MockHost(ok({"message": "Not Found"}, 404))
    forges.names()  # load the built-ins before one is replaced
    forges.register(GitHubForge(http=host))
    yield host
    assert host.requests == []
    forges.register(github.FORGE)


def saved_history(inst: Installation) -> dict[str, Path]:
    """The four kinds of saved file, each holding the secret as it was written before."""
    state = inst.state_dir
    with known({}):
        store = UnitStore(state / "units.json")
        store.upsert([new_unit("add-marker/1")])
        store.set_feedback("add-marker/1", "e2e-test failed with " + SECRET + " in the output")
    log = run_log_dir(state) / "add-marker-01-20260101T100000.log"
    log.parent.mkdir(parents=True)
    log.write_text("started\nenv held " + SECRET + "\n")
    transcript = transcript_dir(state) / "add-marker-01-20260101T100000.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(json.dumps({"kind": "tool_result", "text": "key=" + SECRET}) + "\n")
    ledger = state / LEDGER_NAME
    ledger.write_text(json.dumps(agent_line(outcome="failed: " + SECRET)) + "\n")
    return {
        "units": state / "units.json",
        "log": log,
        "transcript": transcript,
        "ledger": ledger,
    }


def run(inst: Installation, *argv: str) -> int:
    return main(["--config", str(inst.root / "abk.yaml"), "redact-history", *argv])


def shown_by(capsys: pytest.CaptureFixture[str]) -> str:
    out = capsys.readouterr()
    return out.out + out.err


def test_a_dry_run_reports_files_and_names_and_writes_nothing(
    inst: Installation, no_code_host: MockHost, capsys: pytest.CaptureFixture[str]
) -> None:
    files = saved_history(inst)
    before = {name: path.read_text() for name, path in files.items()}

    assert run(inst) == 0

    shown = shown_by(capsys)
    for path in files.values():
        assert path.name in shown
    assert NAME in shown
    assert SECRET not in shown
    assert {name: path.read_text() for name, path in files.items()} == before
    assert not list(inst.state_dir.rglob("*" + SUFFIX))


def test_apply_replaces_the_value_in_every_saved_file_and_keeps_a_copy(
    inst: Installation, no_code_host: MockHost, capsys: pytest.CaptureFixture[str]
) -> None:
    files = saved_history(inst)
    before = {name: path.read_text() for name, path in files.items()}
    pause(inst)

    assert run(inst, "--apply") == 0

    shown = shown_by(capsys)
    assert SECRET not in shown
    warning = [line for line in shown.splitlines() if SUFFIX in line and "commit" in line]
    assert len(warning) == 1
    for name, path in files.items():
        text = path.read_text()
        assert SECRET not in text
        assert REPLACEMENT in text
        assert path.with_name(path.name + SUFFIX).read_text() == before[name]
    feedback = UnitStore(files["units"]).all()[0].feedback
    assert feedback == "e2e-test failed with " + REPLACEMENT + " in the output"


def test_a_second_run_finds_nothing_and_adds_no_copies(
    inst: Installation, no_code_host: MockHost, capsys: pytest.CaptureFixture[str]
) -> None:
    files = saved_history(inst)
    pause(inst)
    assert run(inst, "--apply") == 0
    shown_by(capsys)
    copies = sorted(inst.state_dir.rglob("*" + SUFFIX))
    after = {name: path.read_text() for name, path in files.items()}

    assert run(inst, "--apply") == 0

    shown = shown_by(capsys)
    assert NAME not in shown
    for path in files.values():
        assert path.name not in shown
    assert sorted(inst.state_dir.rglob("*" + SUFFIX)) == copies
    assert {name: path.read_text() for name, path in files.items()} == after


def test_apply_without_a_pause_in_force_changes_nothing_and_fails(
    inst: Installation, no_code_host: MockHost, capsys: pytest.CaptureFixture[str]
) -> None:
    files = saved_history(inst)
    before = {name: path.read_text() for name, path in files.items()}

    assert run(inst, "--apply") != 0

    shown = shown_by(capsys)
    assert "pause" in shown
    assert SECRET not in shown
    assert {name: path.read_text() for name, path in files.items()} == before
    assert not list(inst.state_dir.rglob("*" + SUFFIX))


def test_a_file_holding_only_a_token_shaped_string_is_reported_as_token_shape(
    inst: Installation, no_code_host: MockHost, capsys: pytest.CaptureFixture[str]
) -> None:
    log = run_log_dir(inst.state_dir) / "add-marker-01-20260101T100000.log"
    log.parent.mkdir(parents=True)
    log.write_text("token ghp_" + "a1" * 20 + "\n")

    assert run(inst) == 0

    shown = shown_by(capsys)
    assert log.name in shown
    assert "token-shape" in shown
    assert NAME not in shown
