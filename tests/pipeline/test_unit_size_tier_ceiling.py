"""A pull request's actual size is compared with the ceiling of its unit's expected review tier
with per-tier sizing on, and with the old ceiling with it off; the log line and the `abk status`
entry name the ceiling used (spec: review-tier-ceilings)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.wiring import build_open_pr
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.factories import unit as plan_unit
from tests.sized_forge import REPO, SizedForge
from tests.tier_ceiling_support import configure


def over_lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    output = capsys.readouterr()
    return [line for line in (output.out + output.err).splitlines() if "over the ceiling" in line]


def open_at(
    tmp_path: Path, lines: int, tier: str | None, capsys: pytest.CaptureFixture[str]
) -> list[str]:
    """The over-the-ceiling lines logged when a pull request of `lines` lines is opened for a
    unit expected to get `tier`."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("a/1", change="a", estimated_lines=600, review_tier=tier)])
    store.set_state("a/1", IN_REVIEW, pr=1, branch="spec/a/1")
    open_pr = build_open_pr(for_repo=lambda repo: (SizedForge(lines), REPO), store=store)
    capsys.readouterr()

    unit = plan_unit("a/1", change="a", estimated_lines=600, review_tier=tier)
    open_pr(unit, body="b", base="main", cwd=tmp_path)

    return over_lines(capsys)


def test_a_light_unit_landing_over_its_ceiling_is_logged_with_that_ceiling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(enabled=True)

    logged = open_at(tmp_path, 2300, "light", capsys)

    assert len(logged) == 1
    assert "a/1" in logged[0] and "2300" in logged[0] and "over the ceiling of 2000" in logged[0]


def test_a_unit_under_its_own_tiers_ceiling_says_nothing_of_its_size(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(enabled=True)

    assert open_at(tmp_path, 2300, "auto", capsys) == []


def test_a_light_unit_under_2000_is_not_over_although_over_the_old_ceiling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(enabled=True)

    assert open_at(tmp_path, 1900, "light", capsys) == []


def test_a_unit_with_no_expected_tier_is_compared_with_the_full_ceiling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(enabled=True)

    logged = open_at(tmp_path, 800, None, capsys)

    assert len(logged) == 1 and "over the ceiling of 750" in logged[0]


def test_a_repos_override_is_the_ceiling_its_units_are_compared_with(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(enabled=True, repo_ceilings={"auto": 3000})

    logged = open_at(tmp_path, 3200, "auto", capsys)

    assert len(logged) == 1 and "over the ceiling of 3000" in logged[0]


def listed_in_status(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    tier: str | None,
    lines: int,
    enabled: bool,
    repo: str = "app",
) -> list[str]:
    inst = make_installation(tmp_path)
    configure(enabled=enabled)
    store = cli.store_for(inst)
    store.upsert([stored_unit("a/1", estimated_lines=600, review_tier=tier, repo=repo)])
    store.set_actual_lines("a/1", lines)
    capsys.readouterr()

    cli.cmd_status(argparse.Namespace(), inst)

    return over_lines(capsys)


def test_status_names_the_ceiling_of_the_units_tier_when_it_lists_a_unit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listed = listed_in_status(tmp_path, capsys, "light", 2300, True)

    assert len(listed) == 1
    assert "a/1" in listed[0] and "2300" in listed[0] and "2000" in listed[0]


def test_status_lists_no_unit_under_its_tiers_ceiling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert listed_in_status(tmp_path, capsys, "auto", 2300, True) == []


@pytest.mark.parametrize("enabled", [True, False])
def test_status_lists_a_unit_of_a_repo_no_longer_configured_against_the_workspace_ceiling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], enabled: bool
) -> None:
    listed = listed_in_status(tmp_path, capsys, None, 800, enabled, repo="removed")

    assert len(listed) == 1 and "a/1" in listed[0] and "800" in listed[0]
