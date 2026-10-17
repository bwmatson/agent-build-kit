"""What the `abk scrub-store` tests share: a store whose feedback holds home paths in
the three spellings the command rewrites, a paused pipeline, and the command run in process."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.pause import PAUSE_MARKER, pause_until
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation
from tests.factories import new_unit

UNIT = "add-marker/1"
# Assembled, so that this file does not itself look like a leaked path.
LINUX = "/" + "home" + "/someone/work/app/src/x.py"
MACOS = "/" + "Users" + "/someone/work/app/y.py"
TILDE = "~" + "/work/app/z.py"
FEEDBACK = f"e2e-test failed in {LINUX} and {MACOS}, also {TILDE}, in repo platform"
SCRUBBED = (
    "e2e-test failed in <home>/work/app/src/x.py and <home>/work/app/y.py, "
    "also <home>/work/app/z.py, in repo platform"
)


def planning_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides
) -> Installation:
    """A planning root with its `abk.yaml` written, as the cwd."""
    monkeypatch.delenv("ABK_CONFIG", raising=False)
    installation = make_installation(tmp_path / "planning", **overrides)
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    return installation


def store_of(inst: Installation) -> UnitStore:
    return UnitStore(inst.state_dir / "units.json")


def seed(inst: Installation, feedback: str = FEEDBACK) -> Path:
    """A store holding one unit with `feedback`; the path of its file."""
    store = store_of(inst)
    store.upsert([new_unit(UNIT)])
    store.set_feedback(UNIT, feedback)
    return store.path


def pause(inst: Installation) -> None:
    """The pipeline paused, as `--apply` requires."""
    pause_until(
        datetime.now(UTC) + timedelta(hours=3),
        reason="scrubbing history",
        marker=inst.state_dir / PAUSE_MARKER,
        kind="rate_limit",
    )


def run(inst: Installation, command: str, *argv: str) -> int:
    return main(["--config", str(inst.root / "abk.yaml"), command, *argv])
