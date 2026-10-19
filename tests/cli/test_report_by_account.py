"""`abk report --by account` groups the ledger by the account each call ran under, showing the
label (spec: claude-accounts, usage and slots are per account)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.settings import reload
from tests.conftest import make_installation
from tests.ledger_lines import agent_line, write_ledger


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    kit_home = str(tmp_path / "second-home")
    installation = make_installation(tmp_path / "planning")
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    # A machine path is never in the committed file; the account's directory is the overlay's.
    (installation.root / "abk.local.yaml").write_text(
        yaml.safe_dump(
            {"runtimes": {"claude_code": {"accounts": {"kit": {"config_dir": kit_home}}}}}
        )
    )
    monkeypatch.chdir(installation.root)
    write_ledger(
        installation.state_dir / "usage-ledger.jsonl",
        agent_line(round=0, session_id="s1", account=kit_home),
        agent_line(round=1, session_id="s2", account=kit_home),
        agent_line(round=2, session_id="s3", account=None),
    )
    return installation


def test_report_by_account_has_a_row_for_each_account_with_its_calls(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["report", "--by", "account", "--json"]) == 0

    document = json.loads(capsys.readouterr().out)
    calls = {row["key"]: row["measured"]["calls"] for row in document["rows"]}
    assert calls.pop("kit") == 2
    assert list(calls.values()) == [1]
    assert document["total"]["measured"]["calls"] == 3


def test_the_table_by_account_names_the_label(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["report", "--by", "account"]) == 0

    rows = [line.split()[0] for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert "kit" in rows
    assert "second-home" not in " ".join(rows)


def test_a_row_keyed_by_the_environments_directory_reads_default(
    inst: Installation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "env-home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    reload(None)
    request.addfinalizer(lambda: reload(None))
    write_ledger(
        inst.state_dir / "usage-ledger.jsonl",
        agent_line(round=0, session_id="s1", account=str(home)),
    )

    assert main(["report", "--by", "account", "--json"]) == 0

    keys = [row["key"] for row in json.loads(capsys.readouterr().out)["rows"]]
    assert keys == ["default"]
