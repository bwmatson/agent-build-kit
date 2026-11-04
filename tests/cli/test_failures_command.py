"""`abk failures [TEST]` lists the recorded failures of tests, and `--show` prints the newest
bundle's lines (spec: test-failure-evidence, "Failures can be read with one command").

The records are written as the pipeline writes them, and the bundles with the writer the unit-test
run uses; the command reads both back.
"""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.cli.failures_cmd import cmd_failures
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.failure_record import Storm
from agent_build_kit.pipeline.flakes import Flake, flake_record
from agent_build_kit.pipeline.product_defect import ProductDefectEntry, product_defect_record
from agent_build_kit.pipeline.run_log import failure_bundles_dir, write_failure_bundle
from agent_build_kit.pipeline.untouched_failures import PreExisting, preexisting_record

FLAKY = "tests/test_a.py::test_x"
PRE_EXISTING = "tests/test_b.py::test_y"
DEFECT = "tests/test_c.py::test_z"
STORMED = ["tests/test_d.py::test_s1", "tests/test_d.py::test_s2"]


def at(day: int) -> datetime:
    return datetime(2026, 3, day, 9, 30, tzinfo=UTC)


def flake(unit: str, day: int, load: tuple[float, float], bundle: Path | None = None) -> Flake:
    return Flake(
        test=FLAKY,
        unit=unit,
        command="uv run pytest -n auto -q",
        output="FAILED",
        at=at(day),
        evidence="" if bundle is None else str(bundle),
        conditions={"load_before": load[0], "load_after": load[1]},
    )


def record_everything(inst: Installation) -> None:
    flakes = flake_record(inst)
    flakes.append(flake("one/1", 1, (14.0, 18.0)))
    flakes.append(flake("one/1", 3, (12.0, 22.0)))
    flakes.append(flake("two/1", 5, (15.0, 16.0)))
    flakes.append(
        Storm(unit="three/1", at=at(4), count=2, tests=STORMED, command="uv run pytest -q")
    )
    for day in (2, 4):
        preexisting_record(inst).append(
            PreExisting(test=PRE_EXISTING, unit="four/1", command="c", line="l", at=at(day))
        )
    product_defect_record(inst).append(
        ProductDefectEntry(
            test=DEFECT, unit="five/1", files=["src/app.py"], reproduction="run it", at=at(6)
        )
    )


def listing(inst: Installation, capsys: pytest.CaptureFixture[str], test: str | None = None) -> str:
    assert cmd_failures(argparse.Namespace(test=test, show=False), inst) == 0
    return capsys.readouterr().out


def line_of(out: str, test: str) -> str:
    (found,) = [line for line in out.splitlines() if test in line]
    return found


def test_the_command_is_registered_and_takes_an_optional_test_and_show() -> None:
    args = build_parser().parse_args(["failures", FLAKY, "--show"])

    assert args.func is cmd_failures
    assert args.test == FLAKY and args.show is True
    bare = build_parser().parse_args(["failures"])
    assert bare.test is None and bare.show is False


def test_it_lists_a_test_with_its_count_first_and_last_time_units_and_load(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    record_everything(installation)

    line = line_of(listing(installation, capsys), FLAKY)

    assert re.search(r"\b3\b", line), "flaked three times"
    assert "2026-03-01" in line and "2026-03-05" in line, "first and last"
    assert "one/1" in line and "two/1" in line
    assert re.search(r"\b12\b.*\b22\b", line), "the lowest and the highest load seen"


def test_it_lists_each_kind_of_record_by_its_kind(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    record_everything(installation)

    out = listing(installation, capsys)

    assert "flake" in line_of(out, FLAKY)
    assert "pre-existing" in line_of(out, PRE_EXISTING)
    assert "product-defect" in line_of(out, DEFECT)
    for stormed in STORMED:
        assert "storm" in line_of(out, stormed)
        assert "three/1" in line_of(out, stormed)


def test_a_test_with_no_load_on_its_records_shows_none(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    record_everything(installation)

    line = line_of(listing(installation, capsys), PRE_EXISTING)

    assert re.search(r"\b2\b", line)
    assert "four/1" in line
    assert "load" not in line, "a record that has none says nothing of load"


def test_a_test_argument_limits_the_listing_to_that_test(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    record_everything(installation)

    out = listing(installation, capsys, test=FLAKY)

    assert FLAKY in out
    for other in (PRE_EXISTING, DEFECT, *STORMED):
        assert other not in out


def test_nothing_recorded_is_not_an_error(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cmd_failures(argparse.Namespace(test=None, show=False), installation) == 0
    assert FLAKY not in capsys.readouterr().out


# --- --show -------------------------------------------------------------------------


def bundle_of(inst: Installation, day: int, mark: str) -> Path:
    return write_failure_bundle(
        failure_bundles_dir(inst.state_dir),
        "one/1",
        "one",
        at(day),
        output=f"FAILED {FLAKY} {mark}\n",
        context={"command": f"uv run pytest {mark}", "workers": "auto"},
        machine={"start": {"load": [14.0, 13.0, 12.0]}, "processes": {"pytest": 6, "mark": mark}},
        worktree={"before": {"status": []}, "after": {"vanished": [f"tests/test_{mark}.py"]}},
    )


def shown(inst: Installation, capsys: pytest.CaptureFixture[str]) -> str:
    assert cmd_failures(argparse.Namespace(test=FLAKY, show=True), inst) == 0
    return capsys.readouterr().out


def test_show_prints_the_newest_bundles_context_machine_and_worktree_and_the_output_path(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    older = bundle_of(installation, 1, "older")
    newer = bundle_of(installation, 5, "newer")
    flakes = flake_record(installation)
    flakes.append(flake("one/1", 1, (14.0, 18.0), older))
    flakes.append(flake("two/1", 5, (15.0, 16.0), newer))

    out = shown(installation, capsys)

    assert "uv run pytest newer" in out, "the context"
    assert '"mark": "newer"' in out or "mark: newer" in out, "the machine"
    assert "tests/test_newer.py" in out, "the worktree, naming the vanished file"
    assert str(newer / "output.txt") in out, "where the output is, not the output"
    assert "older" not in out


def test_show_does_not_print_the_whole_output(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = bundle_of(installation, 5, "newer")
    flake_record(installation).append(flake("two/1", 5, (15.0, 16.0), bundle))

    out = shown(installation, capsys)

    assert f"FAILED {FLAKY} newer" not in out


def test_show_of_a_test_whose_records_name_no_bundle_says_so_and_lists_it(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    flake_record(installation).append(flake("one/1", 1, (14.0, 18.0)))

    out = shown(installation, capsys)

    assert FLAKY in out
    assert "no bundle" in out
