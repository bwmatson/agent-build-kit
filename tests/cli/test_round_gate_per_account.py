"""A round is paused for usage only when no account that has a unit able to start has room (spec:
claude-accounts, usage and slots are per account).

The usage endpoint is faked at the HTTP boundary and the guard's own reading, cache and decision
run for real (`tests/usage_host.py`). `app` runs on the default account and `platform` on `kit`;
each account's reading is the one Claude Code keeps in its own state file.
"""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit import claude_account
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.pause import is_paused
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import MERGED
from agent_build_kit.pipeline.wiring import build_usage_gate
from tests.conftest import make_installation
from tests.factories import own_group
from tests.pipeline.test_cli_pipeline import argv_namespace, stored
from tests.usage_host import Host, editor_block

MINUTE = timedelta(minutes=1)
HOURS = timedelta(hours=2)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("poll_all", "fetch_all", "plan_all"):
        monkeypatch.setattr(cli, name, lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])


def installation(tmp_path: Path, host: Host, *, default: int, kit: int) -> Installation:
    """One unit on each account: the default account's session at `default`%, `kit`'s at `kit`%."""
    directory = tmp_path / "second-claude"
    directory.mkdir()
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": ".", "worktree_root": str(tmp_path / "trees")},
        repos={
            "app": {"path": str(tmp_path / "app"), "slug": "example/app"},
            "platform": {
                "path": str(tmp_path / "platform"),
                "slug": "example/platform",
                "account": "kit",
            },
        },
        runtimes={"claude_code": {"accounts": {"kit": {"config_dir": str(directory)}}}},
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    host.keep_editor_reading(MINUTE, session=default, resets_in=HOURS)
    (directory / ".claude.json").write_text(
        json.dumps(editor_block(MINUTE, session=kit, resets_in=HOURS))
    )
    UnitStore(inst.state_dir / "units.json").upsert(
        [
            stored("add-marker/1"),
            stored(
                "feature/1",
                change="feature",
                repo="platform",
                groups=own_group("feature/1", "feature"),
            ),
        ]
    )
    return inst


def test_a_full_default_account_does_not_pause_a_round_with_room_on_another(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, host, default=99, kit=10)

    assert cli.cmd_tick(argv_namespace(dry_run=True), inst) == 0

    assert is_paused(inst.state_dir / "paused.json") is None
    assert "pausing" not in capsys.readouterr().out
    # The default account's own unit is held by its gate, which names the window that is full.
    may_start, _ = build_usage_gate(account=claude_account.for_repo(inst.config, "app"))
    allowed, why = may_start()
    assert not allowed
    assert "session" in why
    assert "kit" not in why


def test_a_round_pauses_when_every_account_with_a_unit_is_full_and_the_pause_names_them(
    tmp_path: Path, host: Host
) -> None:
    inst = installation(tmp_path, host, default=99, kit=99)

    assert cli.cmd_tick(argv_namespace(dry_run=True), inst) == 0

    paused = is_paused(inst.state_dir / "paused.json")
    assert paused is not None
    assert "account kit" in paused.reason
    assert "session" in paused.reason


def test_an_account_with_no_unit_able_to_start_does_not_hold_the_round(
    tmp_path: Path, host: Host
) -> None:
    """The default account is full, but only `kit` has a unit left to start."""
    inst = installation(tmp_path, host, default=99, kit=10)
    UnitStore(inst.state_dir / "units.json").set_state("add-marker/1", MERGED)

    assert cli.cmd_tick(argv_namespace(dry_run=True), inst) == 0

    assert is_paused(inst.state_dir / "paused.json") is None
