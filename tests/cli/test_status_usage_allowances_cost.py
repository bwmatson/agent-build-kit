"""`abk status` prints the basis in force for each window and why, no call (spec: usage-pause).

A window on the cost basis reads `<n> points/$ [+ <n> points/h] (<n> pairs with cost, scale <n>)`;
a window whose cost fit is not in force keeps its flat part and says why after a semicolon."""

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit import claude_account
from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.usage_allowances import (
    ALLOWANCES_NAME,
    Calibrated,
    allowances_path,
    write_allowances,
)
from tests.conftest import make_installation
from tests.usage_allowance_records import calibrated
from tests.usage_host import Host, payload, refused


def cost_basis(
    flat: float | None,
    pairs: int,
    *,
    per_usd: float,
    per_hour: float,
    scale: float,
    held: int,
    judged: int = 12,
) -> Calibrated:
    """A kept window on the cost basis: the flat figure it falls back to and the cost fit."""
    return calibrated(flat, pairs).model_copy(
        update={
            "basis": "cost",
            "points_per_usd": per_usd,
            "intercept_per_hour": per_hour,
            "safety_scale": scale,
            "cost_pairs_held": held,
            "cost_pairs_judged": judged,
        }
    )


def not_adopted(flat: float | None, pairs: int, reason: str, **kept: object) -> Calibrated:
    """A kept window left on the units basis for `reason`."""
    return calibrated(flat, pairs).model_copy(update={"reason": reason, **kept})


def allowance_lines(
    tmp_path: Path,
    host: Host,
    capsys: pytest.CaptureFixture[str],
    found: dict[str, Calibrated] | str,
    **limits: object,
) -> list[str]:
    """The allowance lines of `abk status` with `found` kept (or, as text, the file as it is),
    the endpoint refusing."""
    runtimes = {"claude_code": {"limits": limits}}
    inst = make_installation(tmp_path / "planning", planning={"state_dir": "."}, runtimes=runtimes)
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    host.keep_reading(timedelta(minutes=89), payload(session=0.0, weekly=65.0))
    refused(host, cooling=timedelta(minutes=3))
    if isinstance(found, str):
        (inst.state_dir / ALLOWANCES_NAME).write_text(found)
    else:
        write_allowances(inst.state_dir / ALLOWANCES_NAME, found)

    assert cli.cmd_status(build_parser().parse_args(["status"]), inst) == 0

    assert host.asked == 0
    lines = capsys.readouterr().out.splitlines()
    return [line.split("] ", 1)[-1] for line in lines if "usage allowances:" in line]


def test_a_window_on_the_cost_basis_shows_its_fit_and_the_other_why_it_is_not(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    found = {
        "session": cost_basis(9, 31, per_usd=2.65, per_hour=5.1, scale=1.2, held=31),
        "weekly": not_adopted(
            1, 24, "more_false_allows", points_per_usd=0.3, safety_scale=1.1, cost_pairs_held=24
        ),
    }

    lines = allowance_lines(tmp_path, host, capsys, found)

    assert lines == [
        "usage allowances: session 2.65 points/$ + 5.1 points/h (31 pairs with cost, scale 1.2), "
        "weekly 1/unit (24 pairs; cost basis not adopted: more false allows than flat), calibrated"
    ]


def test_a_window_without_an_intercept_shows_no_hourly_part(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    found = {
        "session": calibrated(9, 24),
        "weekly": cost_basis(1, 24, per_usd=0.3, per_hour=0.0, scale=1.1, held=24),
    }

    lines = allowance_lines(tmp_path, host, capsys, found)

    assert lines == [
        "usage allowances: session 9/unit (24 pairs), "
        "weekly 0.30 points/$ (24 pairs with cost, scale 1.1), calibrated"
    ]


def test_too_few_pairs_with_cost_say_how_many_are_needed_and_held(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    found = {
        "session": not_adopted(9, 24, "too_few_pairs", cost_pairs_held=3),
        "weekly": calibrated(1, 24),
    }

    lines = allowance_lines(tmp_path, host, capsys, found)

    assert lines == [
        "usage allowances: session 9/unit "
        "(24 pairs; cost basis needs 8 pairs with cost, 3 held), weekly 1/unit (24 pairs), "
        "calibrated"
    ]


def test_too_few_gaps_judged_say_how_many_are_needed_and_held(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    found = {
        "session": not_adopted(
            9, 24, "too_few_judged", points_per_usd=2.65, cost_pairs_held=12, cost_pairs_judged=4
        ),
        "weekly": calibrated(1, 24),
    }

    lines = allowance_lines(tmp_path, host, capsys, found)

    assert lines == [
        "usage allowances: session 9/unit "
        "(24 pairs; cost basis needs 8 gaps judged, 4 held), weekly 1/unit (24 pairs), calibrated"
    ]


def test_a_cost_fit_that_could_not_be_made_says_so(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    found = {
        "session": not_adopted(9, 24, "no_fit", cost_pairs_held=20),
        "weekly": calibrated(1, 24),
    }

    lines = allowance_lines(tmp_path, host, capsys, found)

    assert lines == [
        "usage allowances: session 9/unit (24 pairs; cost basis not adopted: no fit), "
        "weekly 1/unit (24 pairs), calibrated"
    ]


def test_a_file_of_the_previous_shape_shows_the_flat_figures_and_says_so(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    kept = {"session": calibrated(9, 24), "weekly": calibrated(1, 24)}
    previous = "{" + ",".join(f'"{name}": {each.model_dump_json()}' for name, each in kept.items())

    lines = allowance_lines(tmp_path, host, capsys, previous + "}")

    assert lines == [
        "usage allowances: session 9/unit (24 pairs; from the previous file), "
        "weekly 1/unit (24 pairs; from the previous file), calibrated"
    ]


def test_a_labelled_accounts_line_comes_from_its_own_file_and_shows_the_cost_basis(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "second-claude"
    directory.mkdir()
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": "."},
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
    write_allowances(
        allowances_path(inst.state_dir, claude_account.resolve(inst, "kit")),
        {"weekly": cost_basis(1, 24, per_usd=0.3, per_hour=0.0, scale=1.1, held=24)},
    )

    assert cli.cmd_status(build_parser().parse_args(["status"]), inst) == 0

    lines = [each for each in capsys.readouterr().out.splitlines() if "usage allowances" in each]
    (second,) = [each for each in lines if "account kit" in each]
    assert "weekly 0.30 points/$ (24 pairs with cost, scale 1.1)" in second
    (default,) = [each for each in lines if "account kit" not in each]
    assert "points/$" not in default


def test_a_window_set_to_the_units_basis_prints_the_flat_line_as_it_was(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    found = {
        "session": cost_basis(9, 31, per_usd=2.65, per_hour=5.1, scale=1.2, held=31),
        "weekly": not_adopted(1, 24, "more_false_allows"),
    }

    lines = allowance_lines(
        tmp_path,
        host,
        capsys,
        found,
        session={"usage_estimate_basis": "units"},
        weekly={"usage_estimate_basis": "units"},
    )

    assert lines == [
        "usage allowances: session 9/unit (31 pairs), weekly 1/unit (24 pairs), calibrated"
    ]
