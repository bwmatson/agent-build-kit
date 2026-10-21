"""`abk requeue --help` and `cmd_requeue`'s docstring say a unit parked on a held split is
requeued with `--rework` (and a note) or `--restart` (spec:
a-unit-parked-on-a-split-can-be-requeued)."""

from __future__ import annotations

import inspect

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as cli
from tests.prompt_text import flat


def help_text(capsys: pytest.CaptureFixture[str]) -> str:
    with pytest.raises(SystemExit) as stop:
        main(["requeue", "--help"])
    assert stop.value.code == 0
    return flat(capsys.readouterr().out)


def test_the_requeue_help_names_a_unit_parked_on_a_held_split_and_the_options(
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = help_text(capsys)

    assert "parked" in text and "split" in text
    assert "--rework" in text and "--restart" in text


def test_the_note_help_no_longer_says_failed_or_held_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = help_text(capsys)

    note = text[text.rindex("--note TEXT") :].split("--note-file")[0]
    assert "parked" in note


def test_the_docstring_names_a_unit_parked_on_a_held_split_and_the_options() -> None:
    doc = flat(inspect.getdoc(cli.cmd_requeue) or "")

    assert "parked" in doc and "split" in doc
    assert "--rework" in doc and "--restart" in doc
