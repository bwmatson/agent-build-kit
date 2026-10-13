"""`abk usage replay` re-runs the estimator over the recorded readings and ledger, read-only
(spec: usage-pause).

A row is one usable gap, printed as `<window> at=<time> before=<n> after=<n> units=<n>
estimate=<n> ...`; each window then ends with one line of counts, `<window>: underestimates
<n>, misses beyond margin <n>, false pauses <n>, false allows <n>`."""

import re
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.installation import Installation
from tests.conftest import make_installation
from tests.usage_allowance_records import START, gaps, keep, segments
from tests.usage_host import Host

DAY = timedelta(days=1)


def installation(tmp_path: Path, **limits: object) -> Installation:
    runtimes = {"claude_code": {"limits": limits}}
    inst = make_installation(tmp_path / "planning", planning={"state_dir": "."}, runtimes=runtimes)
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    return inst


def replay(
    inst: Installation, capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, str, str]:
    """The command's exit status, standard output and standard error. A refusal by the parser
    is the exit status it raises."""
    try:
        args = build_parser().parse_args(["usage", "replay", *argv])
        status = args.func(args, inst)
    except SystemExit as stop:
        status = stop.code if isinstance(stop.code, int) else 1
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def rows(out: str, window: str) -> list[dict[str, str]]:
    return [
        dict(token.split("=", 1) for token in line.split()[1:] if "=" in token)
        for line in out.splitlines()
        if line.startswith(f"{window} ") and " at=" in line
    ]


def counts(out: str, window: str) -> dict[str, int]:
    (line,) = [line for line in out.splitlines() if line.startswith(f"{window}:")]
    figures = line.split(":", 1)[1].split(", mean overshoot")[0]
    return {label.strip(): int(n) for label, n in re.findall(r"([a-z ]+?) (\d+)", figures)}


def overshoot(out: str, window: str) -> str:
    (line,) = [line for line in out.splitlines() if line.startswith(f"{window}:")]
    return line.rsplit("mean overshoot ", 1)[1]


def estimates(out: str, window: str) -> list[float]:
    return [float(row["estimate"]) for row in rows(out, window)]


def test_five_weekly_gaps_count_one_underestimate_and_two_false_pauses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    # Weekly allowance 2, margin 5, pause at 70.
    calls, ledger = gaps(
        "weekly",
        [
            (50, 52, 1),  # estimate 52, actual 52: ample, as it proved
            (50, 53, 1),  # estimate 52, actual 53: an underestimate, within the margin
            (63, 64, 1),  # estimate 65, 65 + 5 is not under 70, actual 64: a false pause
            (64, 65, 1),  # estimate 66, refused, actual 65: a false pause
            (20, 24, 2),  # estimate 24, actual 24: ample, as it proved
        ],
    )
    keep(inst.state_dir, calls, ledger)

    status, out, _ = replay(inst, capsys)

    assert status == 0
    assert counts(out, "weekly") == {
        "underestimates": 1,
        "misses beyond margin": 0,
        "false pauses": 2,
        "false allows": 0,
    }


def test_a_row_shows_the_reading_before_and_after_the_units_and_the_estimate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    calls, ledger = gaps("weekly", [(50, 53, 1), (20, 24, 2)])
    keep(inst.state_dir, calls, ledger)

    _, out, _ = replay(inst, capsys)

    shown = [{k: r[k] for k in ("before", "after", "units")} for r in rows(out, "weekly")]
    assert shown == [
        {"before": "50", "after": "53", "units": "1"},
        {"before": "20", "after": "24", "units": "2"},
    ]
    assert estimates(out, "weekly") == [52, 24]


def test_an_actual_reading_beyond_the_estimate_and_margin_is_a_miss_and_may_be_a_false_allow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    calls, ledger = gaps("weekly", [(50, 72, 1)])  # estimate 52, 52 + 5 is under 70, actual 72
    keep(inst.state_dir, calls, ledger)

    _, out, _ = replay(inst, capsys)

    assert counts(out, "weekly") == {
        "underestimates": 1,
        "misses beyond margin": 1,
        "false pauses": 0,
        "false allows": 1,
    }


def test_the_first_gaps_use_the_configured_allowance_and_the_later_ones_the_calibrated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    # Half a point a unit in each: calibrated to the floor of 1 once eight gaps are behind.
    calls, ledger = gaps("weekly", [(10, 11, 2)] * 12)
    keep(inst.state_dir, calls, ledger)

    _, out, _ = replay(inst, capsys)

    assert estimates(out, "weekly") == [14] * 8 + [12] * 4


def test_the_allowances_given_replace_the_ones_in_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    weekly, weekly_ledger = gaps("weekly", [(10, 11, 2)] * 12)
    session, session_ledger = gaps("session", [(10, 40, 2)], start=START + 20 * DAY)
    keep(inst.state_dir, weekly + session, weekly_ledger + session_ledger)

    _, out, _ = replay(inst, capsys, "--weekly-allowance", "3", "--session-allowance", "3")

    assert estimates(out, "weekly") == [16] * 12
    assert estimates(out, "session") == [16]


def test_the_margin_given_replaces_the_one_in_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    calls, ledger = gaps("weekly", [(10, 18, 1)])  # estimate 12, actual 18
    keep(inst.state_dir, calls, ledger)

    _, in_force, _ = replay(inst, capsys)  # a margin of 5: 18 is above 12 + 5
    _, wide, _ = replay(inst, capsys, "--margin", "6")  # 18 is not above 12 + 6

    assert counts(in_force, "weekly")["misses beyond margin"] == 1
    assert counts(wide, "weekly")["misses beyond margin"] == 0


def test_since_keeps_the_gaps_whose_first_reading_is_at_or_after_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    calls, ledger = [], []
    for day in range(3):
        more_calls, more_ledger = segments("weekly", [(3, 1)], start=START + day * DAY)
        calls, ledger = calls + more_calls, ledger + more_ledger
    keep(inst.state_dir, calls, ledger)

    _, out, _ = replay(inst, capsys, "--since", (START + 2 * DAY).isoformat())

    assert [r["at"] for r in rows(out, "weekly")] == [(START + 2 * DAY).isoformat()]


def test_a_record_with_no_usable_gap_says_so_and_exits_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    calls, ledger = segments("weekly", [(3, 1)])
    keep(inst.state_dir, calls, ledger)

    status, out, _ = replay(inst, capsys, "--since", (START + 5 * DAY).isoformat())

    assert status == 0
    assert "no usable gap" in out
    assert rows(out, "weekly") == []


def test_an_empty_state_directory_has_no_usable_gap(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, out, _ = replay(installation(tmp_path), capsys)

    assert status == 0
    assert "no usable gap" in out


def test_a_since_that_is_not_a_time_is_refused_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    calls, ledger = segments("weekly", [(3, 1)])
    keep(inst.state_dir, calls, ledger)

    status, out, err = replay(inst, capsys, "--since", "last-tuesday")

    assert status != 0
    assert "last-tuesday" in out + err
    assert rows(out, "weekly") == []


def test_a_run_writes_nothing_and_asks_nobody_and_names_the_threshold_it_judges_by(
    tmp_path: Path, host: Host, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path, weekly={"usage_pause_pct": 65})
    host.keep_in(inst.state_dir)
    calls, ledger = gaps("weekly", [(50, 53, 1)] * 9)
    keep(inst.state_dir, calls, ledger)
    before = {p: p.read_bytes() for p in inst.state_dir.rglob("*") if p.is_file()}

    status, out, _ = replay(inst, capsys)

    assert status == 0
    assert {p: p.read_bytes() for p in inst.state_dir.rglob("*") if p.is_file()} == before
    assert host.asked == 0
    assert any("usage_pause_pct" in line and "65" in line for line in out.splitlines())


def test_the_mean_overshoot_is_the_estimate_over_the_actual_averaged_where_it_was_over(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    spent = [(50, 52, 1), (50, 53, 1), (63, 64, 1), (64, 65, 1), (20, 24, 2)]
    calls, ledger = gaps("weekly", spent)
    keep(inst.state_dir, calls, ledger)

    _, out, _ = replay(inst, capsys)

    assert overshoot(out, "weekly") == "1.0"  # the two false pauses, each one point over


def test_no_overshoot_is_none(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    inst = installation(tmp_path)
    calls, ledger = gaps("weekly", [(50, 53, 1)])
    keep(inst.state_dir, calls, ledger)

    _, out, _ = replay(inst, capsys)

    assert overshoot(out, "weekly") == "none"


def test_the_output_ends_with_the_allowances_line_and_says_when_there_is_too_little_to_judge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    calls, ledger = gaps("weekly", [(50, 53, 1)] * 3)
    keep(inst.state_dir, calls, ledger)

    _, out, _ = replay(inst, capsys)

    lines = out.splitlines()
    assert lines[-1].startswith("usage allowances:")
    assert any("weekly not enough to judge" in line and "3" in line for line in lines)


def test_a_row_shows_the_allowance_it_used(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation(tmp_path)
    calls, ledger = gaps("weekly", [(10, 11, 2)] * 12)
    keep(inst.state_dir, calls, ledger)

    _, out, _ = replay(inst, capsys)

    assert [r["allowance"] for r in rows(out, "weekly")] == ["2"] * 8 + ["1"] * 4


def test_a_negative_margin_is_refused_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, _, err = replay(installation(tmp_path), capsys, "--margin=-3")

    assert status != 0
    assert "-3" in err
