"""`abk usage replay` compares the flat and the cost estimate walk-forward on the same gaps and
ends with the adoption verdict, read-only (spec: usage-pause).

Twenty session gaps start at 50, cost 1 to 4 dollars in turn and gain 3 points a dollar. With
the pause at 65 and a margin of 5 an estimate lets a start through under 60. The flat figure,
calibrated to 12 points a unit, estimates 62 for every gap after the first eight and so pauses
a start that was safe; the cost fit estimates each gap exactly. The last gap is a surprise
that gained 17 for a dollar.

A gap after the first eight carries `cost=$<n> cost_estimate=<n>`; per window a
`<window> flat:` and a `<window> cost:` line give the counts over those gaps, and a
`<window> cost basis ...` line is the verdict."""

import re
from pathlib import Path

import pytest

from agent_build_kit import claude_account
from agent_build_kit.cli import build_parser
from agent_build_kit.installation import Installation
from tests.conftest import make_installation
from tests.usage_allowance_records import START, STEP, keep
from tests.usage_cost_records import Gap, cost_gaps

ACCOUNT = "/accounts/kit"


def installation(tmp_path: Path) -> Installation:
    limits = {"session": {"usage_pause_pct": 65, "usage_estimate_intercept": False}}
    return make_installation(
        tmp_path / "planning",
        planning={"state_dir": "."},
        runtimes={"claude_code": {"limits": limits, "accounts": {"kit": {"config_dir": ACCOUNT}}}},
    )


def replay(inst: Installation, capsys: pytest.CaptureFixture[str], *argv: str) -> list[str]:
    args = build_parser().parse_args(["usage", "replay", *argv])
    assert args.func(args, inst) == 0
    return capsys.readouterr().out.splitlines()


def steady(index: int, *, rate: int = 3) -> Gap:
    """A gap of one unit from 50 that gained `rate` points for each of 1 to 4 dollars in turn."""
    cost = float(index % 4 + 1)
    return Gap(before=50, gain=round(rate * cost), cost=cost)


SURPRISE = Gap(before=50, gain=17, cost=1.0)


def kept(tmp_path: Path, gaps: list[Gap], *, account: str | None = None) -> Installation:
    inst = installation(tmp_path)
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    calls, ledger = cost_gaps("session", gaps, account=account)
    label = None if account is None else claude_account.resolve(inst, "kit")
    keep(inst.state_dir, calls, ledger, account=label)
    return inst


def twenty(tmp_path: Path, *, surprise: bool = True) -> Installation:
    return kept(tmp_path, [steady(i) for i in range(19)] + [SURPRISE if surprise else steady(19)])


def rows(lines: list[str]) -> list[dict[str, str]]:
    return [
        dict(token.split("=", 1) for token in line.split()[1:] if "=" in token)
        for line in lines
        if line.startswith("session ") and " at=" in line
    ]


def counts(lines: list[str], label: str) -> dict[str, int]:
    """The counts of the line that starts `label` (`session flat:`), the overshoot left out."""
    (line,) = [line for line in lines if line.startswith(f"{label}:")]
    figures = line.split(":", 1)[1].split(", mean overshoot")[0]
    return {name.strip(): int(n) for name, n in re.findall(r"([a-z ]+?) (\d+)", figures)}


def overshoot(lines: list[str], label: str) -> str:
    (line,) = [line for line in lines if line.startswith(f"{label}:")]
    return line.rsplit("mean overshoot ", 1)[1]


def verdict(lines: list[str], window: str = "session") -> str:
    (line,) = [line for line in lines if line.startswith(f"{window} cost basis")]
    return line


def test_the_twelve_gaps_after_the_first_eight_carry_the_cost_and_the_cost_estimate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = twenty(tmp_path)
    files = {p: p.read_bytes() for p in inst.state_dir.iterdir()}

    shown = rows(replay(inst, capsys))

    assert {p: p.read_bytes() for p in inst.state_dir.iterdir()} == files
    assert len(shown) == 20
    assert all("cost" not in row and "cost_estimate" not in row for row in shown[:8])
    assert [float(row["cost"].lstrip("$")) for row in shown[8:]] == [
        float(i % 4 + 1) for i in range(8, 19)
    ] + [1.0]
    assert [float(row["cost_estimate"]) for row in shown[8:]] == [
        50 + 3 * (i % 4 + 1) for i in range(8, 19)
    ] + [53]


def test_the_cost_estimate_of_a_gap_is_fitted_from_the_pairs_before_it_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Three points a dollar for twelve gaps, then five: only the later gaps may know it.
    gaps = [steady(i) for i in range(12)] + [steady(i, rate=5) for i in range(12, 20)]
    inst = kept(tmp_path, gaps)

    shown = rows(replay(inst, capsys))

    assert float(shown[8]["cost_estimate"]) == 50 + 3 * 1.0
    assert float(shown[12]["cost_estimate"]) == 50 + 3 * 1.0
    assert float(shown[19]["cost_estimate"]) > 50 + 3 * 4.0


def test_the_flat_and_cost_lines_count_the_same_twelve_gaps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = replay(twenty(tmp_path), capsys)

    assert counts(lines, "session flat") == {
        "underestimates": 1,
        "misses beyond margin": 0,
        "false pauses": 11,
        "false allows": 0,
    }
    assert overshoot(lines, "session flat") == "6.0"
    assert counts(lines, "session cost") == {
        "underestimates": 1,
        "misses beyond margin": 1,
        "false pauses": 2,
        "false allows": 1,
    }
    assert overshoot(lines, "session cost") == "none"


def test_the_verdict_is_the_one_the_calibration_reaches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    surprise = replay(twenty(tmp_path / "surprise"), capsys)
    steady_run = replay(twenty(tmp_path / "steady", surprise=False), capsys)

    assert "not adopted" in verdict(surprise)
    assert "more false allows than flat" in verdict(surprise)
    assert "not adopted" not in verdict(steady_run)
    assert "adopted" in verdict(steady_run)


def test_the_verdict_comes_after_the_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = replay(twenty(tmp_path), capsys)

    assert lines.index(verdict(lines)) > lines.index(
        next(line for line in lines if line.startswith("session cost:"))
    )


def test_seven_cost_pairs_print_no_cost_estimate_or_line_and_say_seven_of_eight_are_held(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = replay(kept(tmp_path, [steady(i) for i in range(7)]), capsys)

    assert all("cost_estimate" not in row for row in rows(lines))
    assert not [line for line in lines if line.startswith("session cost:")]
    said = verdict(lines)
    assert "not adopted" in said
    assert "too few pairs with cost" in said
    assert "7 held" in said
    assert "8 needed" in said


def test_since_limits_both_estimates_to_the_gaps_it_shows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    since = (START + 14 * STEP).isoformat()

    lines = replay(twenty(tmp_path), capsys, "--since", since)

    shown = rows(lines)
    assert len(shown) == 6
    assert all("cost_estimate" in row for row in shown)
    assert counts(lines, "session flat")["false pauses"] == 5
    assert counts(lines, "session cost")["false allows"] == 1


def test_the_margin_applies_to_both_estimates(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = replay(twenty(tmp_path), capsys, "--margin", "0")

    for label in ("session flat", "session cost"):
        assert counts(lines, label) == {
            "underestimates": 1,
            "misses beyond margin": 1,
            "false pauses": 0,
            "false allows": 1,
        }


def test_a_fixed_allowance_applies_to_the_flat_estimate_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = twenty(tmp_path)
    free = replay(inst, capsys)

    fixed = replay(inst, capsys, "--session-allowance", "5")

    assert counts(fixed, "session flat") == {
        "underestimates": 9,
        "misses beyond margin": 3,
        "false pauses": 0,
        "false allows": 1,
    }
    assert overshoot(fixed, "session flat") == "2.0"
    assert [row["cost_estimate"] for row in rows(fixed)[8:]] == [
        row["cost_estimate"] for row in rows(free)[8:]
    ]
    assert counts(fixed, "session cost") == counts(free, "session cost")


def test_the_account_flag_replays_that_accounts_cost_gaps_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = kept(tmp_path, [steady(i) for i in range(20)], account=ACCOUNT)

    default = replay(inst, capsys)
    second = replay(inst, capsys, "--account", "kit")

    assert not rows(default)
    assert len(rows(second)) == 20
    assert counts(second, "session cost")["false allows"] == 0
