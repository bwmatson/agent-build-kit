"""The earlier rounds a reviewer is shown are sections of one budget.

Open findings are required: they are kept whole however long they are. What else
the rounds carry (a round's prose, the builder's responses, findings already
reported fixed) shares what is left of `ROUND_CHARS`, and a note says how many
findings were left out. The runner is the public surface: the note is part of
the context its review step is handed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.pipeline import stack_runner
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import unit
from tests.runner_fakes import Recorder, make_runner

BUDGET = 1_400


def finding(number: int, status: str, filler: int = 150) -> dict:
    return {
        "id": f"1.{number}",
        "file": "src/pkg/units.py",
        "line": 182,
        "summary": f"S{number}",
        "consequence": f"C{number} " + "x" * filler,
        "done": "iterate through_satisfied() as base_of does",
        "required": True,
        "status": status,
    }


def context_of(tmp_path: Path, rounds: tuple[dict, ...]) -> str:
    """The context the reviewer is handed after `rounds`."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    runner = make_runner(store, Recorder(store), tmp_path)
    notes = runner.review_notes(
        unit(), round_number=len(rounds), total=5, review_boundary="", rounds=rounds
    )
    return notes["context"]


def test_long_responses_share_the_budget_and_are_reduced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stack_runner, "ROUND_CHARS", BUDGET)

    def rounds(response: str) -> tuple[dict, ...]:
        return tuple(
            {
                "asked": "r",
                "response": response,
                "judged": f"sha-{n}",
                "findings": [finding(1, "fixed")],
            }
            for n in range(1, 4)
        )

    bare = context_of(tmp_path, rounds("z"))
    context = context_of(tmp_path, rounds("z" * 1_200))

    assert len(context) - len(bare) <= BUDGET
    assert 3 < context.count("z") < 3 * 1_200


def test_open_findings_stay_whole_when_they_alone_pass_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stack_runner, "ROUND_CHARS", BUDGET)
    statuses = ["fixed", "fixed", "fixed", "open", "open", "open"]
    findings = [finding(n, status, filler=500) for n, status in enumerate(statuses, start=1)]
    rounds = ({"asked": "r", "response": "z" * 1_200, "judged": "sha-abc", "findings": findings},)

    context = context_of(tmp_path, rounds)

    for n in (4, 5, 6):
        assert f"C{n} " + "x" * 500 in context
    shown = [n for n in (1, 2, 3) if f"C{n} " + "x" * 500 in context]
    left_out = 3 - len(shown)
    assert left_out >= 1, "findings already fixed are what is left out"
    assert re.search(rf"\b{left_out}\b[^\n]*(left out|omitted)", context)
    assert context.count("z") < 1_200, "the response is reduced where the findings need the room"
