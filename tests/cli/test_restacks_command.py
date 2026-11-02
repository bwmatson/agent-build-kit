"""`abk restacks [--since TIME]` prints the ledger's restack records as counts and hours by
point and by re-test kind (spec: restack-points, each restack decision is recorded and
summarised). A line is `<point or kind>: <n> moves, <n> re-tests, <hours> hours`."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.spans import RestackRecord
from tests.conftest import make_installation


def installation(tmp_path: Path) -> Installation:
    inst = make_installation(tmp_path / "planning", planning={"state_dir": "."})
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    return inst


def keep(inst: Installation, *records: RestackRecord, other: tuple[dict, ...] = ()) -> None:
    lines = [record.model_dump_json() for record in records] + [json.dumps(o) for o in other]
    (inst.state_dir / "usage-ledger.jsonl").write_text("\n".join(lines) + "\n")


def restack(point: str, at: str, retest: str = "none", seconds: float = 0.0) -> RestackRecord:
    return RestackRecord(
        at=at,
        unit="feature/1",
        point=point,
        moved=True,
        retest=retest,
        retest_seconds=seconds,
        retest_result="passed" if retest != "none" else "",
    )


def run(inst: Installation, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    args = build_parser().parse_args(["restacks", *argv])
    status = args.func(args, inst)
    return status, capsys.readouterr().out


def line_of(out: str, label: str) -> str:
    (line,) = [line for line in out.splitlines() if line.startswith(f"{label}:")]
    return line


def test_it_counts_moves_and_re_tests_and_hours_for_each_point_and_each_kind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    keep(
        inst,
        restack("prepare", "2030-01-01T09:00:00+00:00"),
        restack("before_review", "2030-01-01T10:00:00+00:00", "lite", 1800),
        restack("before_pr", "2030-01-01T11:00:00+00:00", "full", 1800),
        restack("before_pr", "2030-01-01T12:00:00+00:00", "full", 1800),
    )

    status, out = run(inst, capsys)

    assert status == 0
    assert re.search(r"\b1 move", line_of(out, "prepare"))
    assert re.search(r"\b0 re-test", line_of(out, "prepare"))
    before_pr = line_of(out, "before_pr")
    assert re.search(r"\b2 moves", before_pr) and re.search(r"\b2 re-tests", before_pr)
    assert re.search(r"\b1\.0+ hours", before_pr)
    assert re.search(r"\b1 re-test", line_of(out, "lite"))
    assert re.search(r"\b2 re-tests", line_of(out, "full"))
    assert re.search(r"\b1\.0+ hours", line_of(out, "full"))


def test_since_leaves_out_what_was_recorded_before_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    keep(
        inst,
        restack("before_pr", "2030-01-01T09:00:00+00:00", "full", 600),
        restack("before_pr", "2030-01-03T09:00:00+00:00", "lite", 60),
    )

    status, out = run(inst, capsys, "--since", "2030-01-02T00:00:00+00:00")

    assert status == 0
    assert re.search(r"\b1 move", line_of(out, "before_pr"))
    assert "full:" not in out


def test_a_ledger_with_no_restack_records_reads_as_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    keep(
        inst,
        other=(
            {"kind": "span", "at": "2030-01-01T09:00:00+00:00", "unit": "feature/1"},
            {"kind": "affected", "at": "2030-01-01T09:00:00+00:00", "unit": "feature/1"},
        ),
    )

    status, out = run(inst, capsys)

    assert status == 0
    assert "before_pr:" not in out and "prepare:" not in out


def test_a_missing_ledger_reads_as_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out = run(installation(tmp_path), capsys)

    assert status == 0
    assert "before_pr:" not in out
