"""The dump never shows a secret, withholds itself when redaction fails, and runs no git command
with a secret in its arguments; a failing source is named and hides nothing else."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import FAILED
from tests import scratch_dump
from tests.redaction_fakes import known
from tests.scratch_dump_support import (
    TICK_LINE,
    add_ledger,
    add_units,
    bare_scratch,
    filled_scratch,
    stand_in_tick,
)

NAME = "FAKE_API_KEY"
SECRET = "sk-live-9f8e7d6c5b4a3210"


def secret_scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A scratch whose environment holds the secret and whose tick output, ledger tail and a
    unit's failure reason repeat it."""
    scratch = bare_scratch(tmp_path, env={"ABK_RUNTIME": "claude_code", NAME: SECRET})
    add_units(scratch, ["feature/1"])
    UnitStore(scratch.state / "units.json").set_state(
        "feature/1", FAILED, branch="spec/feature/1", note=f"failed with {SECRET}"
    )
    add_ledger(scratch, [f"role-{SECRET}"])
    stand_in_tick(scratch, monkeypatch, [f"{TICK_LINE} {SECRET}"])
    return scratch


def test_a_secret_named_variables_value_appears_nowhere_and_its_name_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = secret_scratch(tmp_path, monkeypatch)

    with known({}):
        text = scratch_dump.scratch_state(scratch)

    assert SECRET not in text
    assert NAME in text
    assert TICK_LINE in text and "feature/1" in text


def test_a_redactor_that_raises_leaves_one_line_saying_the_dump_was_withheld(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = secret_scratch(tmp_path, monkeypatch)

    def broken(text: str, *, where: str) -> str:
        raise RuntimeError(f"boom quoting {text}")

    monkeypatch.setattr(
        scratch_dump, "redactor", SimpleNamespace(redact_text=broken, register=lambda *_: None)
    )

    text = scratch_dump.scratch_state(scratch)

    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 1 and "withheld" in lines[0]
    assert SECRET not in text and TICK_LINE not in text and "feature/1" not in text


def test_no_secret_value_is_in_an_argument_of_a_git_command_it_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = secret_scratch(tmp_path, monkeypatch)
    argvs: list[list[str]] = []

    def run(argv, **kwargs):
        argvs.append([str(part) for part in argv])
        return subprocess.run(argv, **kwargs)

    monkeypatch.setattr(scratch_dump, "runner", SimpleNamespace(**{**vars(subprocess), "run": run}))

    with known({}):
        scratch_dump.scratch_state(scratch)

    assert argvs and all(argv[0] == "git" for argv in argvs)
    assert not any(SECRET in part for argv in argvs for part in argv)


def test_an_unreadable_source_is_named_for_that_item_and_the_rest_stays_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = filled_scratch(tmp_path, env={"ABK_RUNTIME": "claude_code", NAME: SECRET})
    stand_in_tick(scratch, monkeypatch, [f"{TICK_LINE} {SECRET}"])
    (scratch.state / "units.json").unlink()
    (scratch.state / "units.json").mkdir()

    with known({}):
        text = scratch_dump.scratch_state(scratch)

    assert "scratch state unavailable: IsADirectoryError" in text
    assert TICK_LINE in text and SECRET not in text
