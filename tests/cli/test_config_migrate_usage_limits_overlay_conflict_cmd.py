"""`abk config --migrate --include-defaults` does not move `usage_limits` into an overlay that
still spells the key `limits`: it reports the conflict as the overlay spells it and leaves the
overlay, so the pair still loads."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from tests.cli.config_migrate_fakes import run_migrate
from tests.cli.config_migrate_machine_fakes import tracked

BASE = (
    "version: 1\n"
    "runtimes:\n"
    "  claude_code:\n"
    "    limits:\n"
    "      session:\n"
    "        usage_pause_pct: 70\n"
)
OVERLAY = "runtimes:\n  claude_code:\n    limits:\n      weekly:\n        usage_pause_pct: 80\n"


def test_the_overlay_keeps_one_spelling_and_the_conflict_names_the_key_it_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path, BASE, local=OVERLAY)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--include-defaults", "--yes")

    assert code == 0
    assert (tmp_path / "abk.local.yaml").read_text() == OVERLAY
    assert (
        "left runtimes.claude_code.usage_limits in abk.yaml: abk.local.yaml already sets "
        "runtimes.claude_code.limits"
    ) in terminal.out
    capsys.readouterr()

    assert main(["--config", str(path), "config"]) == 0
