"""`abk status` lists units in review highest tier first, each with its tier (spec:
review-triage)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.conftest import make_installation, run_status
from tests.factories import new_unit
from tests.verdict_fakes import write_verdicts

AWAITING = re.compile(r"awaiting review: (\S+) \(app\) #(\d+)(.*)")
TIER_WORD = re.compile(r"\b(full|light|auto)\b")

# Arrival order; the tier each has recorded, none for `plain`.
ARRIVED = (
    ("lightfirst/1", ReviewTier.LIGHT),
    ("plain/1", None),
    ("autoone/1", ReviewTier.AUTO),
    ("fullone/1", ReviewTier.FULL),
    ("lightlast/1", ReviewTier.LIGHT),
)


def awaiting(lines: list[str]) -> list[tuple[str, str]]:
    """The unit id and the rest of the line of each `awaiting review` line, in print order."""
    found = (AWAITING.search(line) for line in lines)
    return [(match.group(1), match.group(3)) for match in found if match]


def status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    enabled: bool,
) -> list[str]:
    inst = make_installation(
        tmp_path,
        planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees")),
        review=dict(enabled=enabled),
    )
    write_verdicts(tmp_path / "verdicts.json", {uid: tier for uid, tier in ARRIVED if tier})
    store = UnitStore(tmp_path / "units.json")
    store.upsert([new_unit(uid) for uid, _ in ARRIVED])
    for number, (uid, _) in enumerate(ARRIVED, start=1):
        store.set_state(uid, IN_REVIEW, branch=f"spec/{uid}", pr=number)
    return run_status(inst, monkeypatch, capsys)


def test_units_are_printed_highest_tier_first_each_with_its_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    shown = awaiting(status(tmp_path, monkeypatch, capsys, enabled=True))

    assert [uid for uid, _ in shown] == [
        "fullone/1",
        "lightfirst/1",
        "lightlast/1",
        "plain/1",
        "autoone/1",
    ]
    tiers = {uid: TIER_WORD.search(rest) for uid, rest in shown}
    assert tiers["fullone/1"] and tiers["fullone/1"].group(1) == "full"
    assert tiers["lightfirst/1"] and tiers["lightfirst/1"].group(1) == "light"
    assert tiers["autoone/1"] and tiers["autoone/1"].group(1) == "auto"
    # A unit with no verdict is printed as before, with no tier.
    assert dict(shown)["plain/1"] == ""


def test_with_review_disabled_the_output_is_what_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    enabled = awaiting(status(tmp_path / "on", monkeypatch, capsys, enabled=True))
    disabled = awaiting(status(tmp_path / "off", monkeypatch, capsys, enabled=False))

    assert enabled != disabled
    assert disabled == [(uid, "") for uid, _ in ARRIVED]
