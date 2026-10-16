"""A planning root with a written `abk.yaml` and the state file of held splits, and `abk` run over
them, for the tests of `abk tier2 hold`, `release` and `status`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import main
from agent_build_kit.pipeline.tier2_holds import HELD_FILE, SOURCE_GATE, write_hold

SPLITS = """\
tests:
  e2e_splits:
    # the live agent splits
    acp:
      marker: runtime_acp
    claude_code: {marker: runtime_claude_code}
"""

# `acp` released by the configuration.
SPLITS_ACP_RELEASED = SPLITS.replace(
    "marker: runtime_acp", "marker: runtime_acp\n      hold: false"
)


def planning(tmp_path: Path, tests: str = SPLITS) -> Path:
    """The path of an `abk.yaml` whose state directory is its own folder; `tests` is the text of
    its `tests` block."""
    root = tmp_path / "planning"
    root.mkdir()
    (root / "abk.yaml").write_text(
        "version: 1\n"
        "planning:\n"
        "  state_dir: .\n"
        f"  worktree_root: {tmp_path / 'trees'}\n"
        "repos:\n"
        f"  app: {{path: {tmp_path / 'app'}, slug: example/app}}\n" + tests
    )
    return root / "abk.yaml"


def abk(
    config: Path, capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, list[str], list[str]]:
    """`abk --config <config> <argv>`: the exit code, then what it printed and what it said as
    an error, as lines. An argument it refuses exits 2, as it does at the prompt."""
    capsys.readouterr()
    try:
        code = main(["--config", str(config), *argv])
    except SystemExit as stop:
        code = int(stop.code or 0)
    shown = capsys.readouterr()
    return code, shown.out.splitlines(), shown.err.splitlines()


def held_entries(config: Path) -> dict[str, Any]:
    """The state file's entries by split; empty when there is no file."""
    path = config.parent / HELD_FILE
    return json.loads(path.read_text()) if path.exists() else {}


def gate_entry(config: Path, split: str, until: datetime) -> None:
    """An entry as the split's gate writes it, with a deadline."""
    write_hold(
        config.parent,
        split,
        reason="out of budget",
        source=SOURCE_GATE,
        by="gate",
        until=until,
        now=datetime.now(UTC),
    )
