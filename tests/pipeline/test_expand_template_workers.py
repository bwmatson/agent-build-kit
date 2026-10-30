"""The `{workers}` placeholder of `checks.affected.command` (spec:
testmon-selection-honours-markers)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_build_kit.config import AffectedConfig
from agent_build_kit.pipeline.wiring import expand_template


def test_workers_expands_to_the_option_words() -> None:
    template = "uv run pytest {workers} {changed_files}"

    assert expand_template(template, ["a.py", "b c.py"], [], workers="4", max_workers=6) == [
        "uv",
        "run",
        "pytest",
        "-n",
        "4",
        "--maxprocesses=6",
        "a.py",
        "b c.py",
    ]


def test_auto_and_the_default_cap_expand_as_the_full_run_writes_them() -> None:
    assert expand_template("pytest {workers}", [], [], workers="auto", max_workers=8) == [
        "pytest",
        "-n",
        "auto",
        "--maxprocesses=8",
    ]


def test_the_other_placeholders_still_expand_beside_it() -> None:
    template = "pytest {workers} {failed_ids} {changed_files}"

    assert expand_template(template, ["a.py"], ["a.py::t"], workers="2", max_workers=3) == [
        "pytest",
        "-n",
        "2",
        "--maxprocesses=3",
        "a.py::t",
        "a.py",
    ]


def test_a_workers_placeholder_inside_a_word_is_refused() -> None:
    with pytest.raises(ValidationError, match="word of its own"):
        AffectedConfig(mode="command", command="pytest --numprocesses={workers}")
