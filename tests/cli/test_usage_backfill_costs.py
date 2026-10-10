"""`abk usage backfill-costs`: the temporary command that turns legacy cost rows into
incremental ones (spec: usage-accounting)."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest

from agent_build_kit.cli import main, usage_cmd
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.usage_ledger import UsageRecord, append_record
from agent_build_kit.pipeline.usage_report import roll_up_change
from tests.conftest import make_installation
from tests.ledger_lines import costed_line, legacy_line, span_line, write_ledger

LEDGER = "usage-ledger.jsonl"


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    # The pipeline's environment names the live installation, and the command prefers it to
    # the cwd: nothing here may reach it.
    monkeypatch.delenv("ABK_CONFIG", raising=False)
    installation = make_installation(tmp_path / "planning")
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    return installation


def backfill(inst: Installation, *argv: str) -> int:
    """The command on `inst`, named by `--config`, never by the environment."""
    return main(["--config", str(inst.root / "abk.yaml"), "usage", "backfill-costs", *argv])


def at(minute: int) -> str:
    return f"2026-01-01T10:{minute:02d}:00+00:00"


def mixed_ledger(path: Path) -> Path:
    """Three units: a Claude Code session stored as running totals, ACP and gateway calls
    stored per call, and a session whose stored figure falls."""
    return write_ledger(
        path,
        legacy_line(2.63, at=at(0), node="tests", session_id="cc"),
        legacy_line(5.49, at=at(1), node="implement", session_id="cc", resumed=True),
        legacy_line(13.18, at=at(2), node="rework", round=1, session_id="cc", resumed=True),
        legacy_line(
            1.0, at=at(3), unit="add-marker/2", node="implement", runtime="acp", session_id="acp"
        ),
        legacy_line(
            2.0,
            at=at(4),
            unit="add-marker/2",
            node="rework",
            round=1,
            runtime="acp",
            session_id="acp",
            resumed=True,
        ),
        legacy_line(
            0.5,
            at=at(5),
            unit="add-marker/2",
            node="review",
            session_id="gw",
            usage_source="gateway",
        ),
        legacy_line(5.0, at=at(6), unit="feature/1", change="feature", session_id="falls"),
        legacy_line(
            3.0,
            at=at(7),
            unit="feature/1",
            change="feature",
            node="rework",
            session_id="falls",
            resumed=True,
        ),
        span_line(),
    )


def lines_of(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x]


def session_lines(path: Path, session_id: str) -> list[dict]:
    found = [x for x in lines_of(path) if x.get("session_id") == session_id]
    return sorted(found, key=lambda x: x["at"])


def run(inst: Installation, capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    assert backfill(inst, *argv) == 0
    return capsys.readouterr().out


def count_after(label: str, out: str) -> int:
    found = re.search(rf"{label}\D*(\d+)", out, re.IGNORECASE)
    assert found, f"no {label!r} count in {out!r}"
    return int(found.group(1))


def line_with(out: str, text: str) -> str:
    (found,) = [x for x in out.splitlines() if text in x]
    return found


def test_a_dry_run_prints_the_totals_and_counts_and_writes_nothing(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = mixed_ledger(inst.state_dir / LEDGER)
    before = ledger.read_bytes()
    files = sorted(p.name for p in inst.state_dir.iterdir())

    out = run(inst, capsys)

    assert ledger.read_bytes() == before
    assert sorted(p.name for p in inst.state_dir.iterdir()) == files
    unit_one = line_with(out, "add-marker/1")
    assert "21.30" in unit_one
    assert "13.18" in unit_one
    assert line_with(out, "add-marker/2").count("3.50") == 2
    assert "8.00" in line_with(out, "feature/1")
    overall = line_with(out, "overall")
    assert "32.80" in overall
    assert "16.68" in overall
    assert count_after("changed", out) == 6
    assert count_after("unknown", out) == 2


def test_apply_writes_a_timestamped_copy_then_rewrites_the_ledger(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = mixed_ledger(inst.state_dir / LEDGER)
    original = ledger.read_text()

    run(inst, capsys, "--apply")

    copies = [
        p
        for p in inst.state_dir.iterdir()
        if p.name.startswith("usage-ledger")
        and p.name != LEDGER
        and p.suffix not in {".lock", ".tmp"}
    ]
    assert [p.read_text() for p in copies] == [original]
    assert re.search(r"\d{8}|\d{4}-\d{2}-\d{2}", copies[0].name)
    assert ledger.read_text() != original
    assert not ledger.with_name(LEDGER + ".tmp").exists()
    assert all("cost_usd" not in x for x in lines_of(ledger) if x["kind"] == "agent")


def test_a_second_run_finds_no_legacy_rows_and_changes_nothing(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = mixed_ledger(inst.state_dir / LEDGER)
    run(inst, capsys, "--apply")
    rewritten = ledger.read_bytes()
    files = sorted(p.name for p in inst.state_dir.iterdir())

    out = run(inst, capsys, "--apply")

    assert ledger.read_bytes() == rewritten
    assert sorted(p.name for p in inst.state_dir.iterdir()) == files
    assert count_after("changed", out) == 0
    assert "no legacy rows" in out.lower()


def test_a_record_appended_while_it_runs_is_not_lost(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A writer starts appending just after the command has read the ledger. Under the
    ledger lock the append waits for the rewrite and lands after it; without the lock it
    lands between the read and the rewrite and the rewrite drops it."""
    ledger = mixed_ledger(inst.state_dir / LEDGER)
    late = costed_line(0.75, 0.75, at=at(30), unit="late/1", change="late", session_id="late")
    read_done = threading.Event()
    appended = threading.Event()
    real_read = usage_cmd.read_lines

    def append() -> None:
        read_done.wait(timeout=30)
        append_record(ledger, UsageRecord.model_validate(late))
        appended.set()

    def read_then_signal(path: Path) -> list[str]:
        lines = real_read(path)
        read_done.set()
        appended.wait(timeout=1.0)  # returns at once when nothing holds the append back
        return lines

    monkeypatch.setattr(usage_cmd, "read_lines", read_then_signal)
    writer = threading.Thread(target=append)
    writer.start()

    assert backfill(inst, "--apply") == 0
    writer.join(timeout=30)

    assert len(session_lines(ledger, "late")) == 1
    assert len(session_lines(ledger, "cc")) == 3
    assert all("cost" in x for x in session_lines(ledger, "cc"))


def test_a_legacy_row_after_a_costed_one_of_its_session_continues_from_it(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    """A runner still on the old code appends a flat row after the session was backfilled."""
    ledger = write_ledger(
        inst.state_dir / LEDGER,
        costed_line(1.0, 1.0, basis="backfilled", at=at(0), session_id="s"),
        legacy_line(2.5, at=at(1), node="rework", session_id="s", resumed=True),
    )

    run(inst, capsys, "--apply")

    cost = session_lines(ledger, "s")[1]["cost"]
    assert cost["incremental_usd"] == pytest.approx(1.5)
    assert cost["cumulative_usd"] == 2.5


def test_a_summary_the_archive_wrote_is_left_alone(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = write_ledger(
        inst.state_dir / LEDGER,
        costed_line(2.0, 2.0, basis="first", at=at(0), session_id="s"),
    )
    roll_up_change(ledger, "add-marker")
    archived = ledger.read_bytes()
    files = sorted(p.name for p in inst.state_dir.iterdir())

    out = run(inst, capsys, "--apply")

    assert ledger.read_bytes() == archived
    assert sorted(p.name for p in inst.state_dir.iterdir()) == files
    assert "no legacy rows" in out.lower()
    assert "cumulative_summed" not in out


def test_a_claude_code_session_of_running_totals_becomes_increments(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = mixed_ledger(inst.state_dir / LEDGER)

    run(inst, capsys, "--apply")

    costs = [x["cost"] for x in session_lines(ledger, "cc")]
    assert [c["incremental_usd"] for c in costs] == pytest.approx([2.63, 2.86, 7.69])
    assert [c["cumulative_usd"] for c in costs] == pytest.approx([2.63, 5.49, 13.18])
    assert {c["basis"] for c in costs} == {"backfilled"}


def test_acp_and_gateway_rows_keep_their_figure_and_gain_a_running_cumulative(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = mixed_ledger(inst.state_dir / LEDGER)

    run(inst, capsys, "--apply")

    acp = [x["cost"] for x in session_lines(ledger, "acp")]
    assert [c["incremental_usd"] for c in acp] == [1.0, 2.0]
    assert [c["cumulative_usd"] for c in acp] == [1.0, 3.0]
    (gateway,) = [x["cost"] for x in session_lines(ledger, "gw")]
    assert gateway["incremental_usd"] == 0.5
    assert gateway["cumulative_usd"] == 0.5
    assert {c["basis"] for c in (*acp, gateway)} == {"backfilled"}


def test_a_gateway_claude_code_session_reports_increments_of_the_running_reported_total(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = write_ledger(
        inst.state_dir / LEDGER,
        legacy_line(0.9, reported_cost_usd=1.0, usage_source="gateway", at=at(0), session_id="gws"),
        legacy_line(2.1, reported_cost_usd=3.0, usage_source="gateway", at=at(1), session_id="gws"),
    )

    run(inst, capsys, "--apply")

    costs = [x["cost"] for x in session_lines(ledger, "gws")]
    assert [c["reported_usd"] for c in costs] == pytest.approx([1.0, 2.0])
    assert [c["incremental_usd"] for c in costs] == pytest.approx([0.9, 2.1])


def test_a_session_in_which_a_figure_falls_is_left_unknown_and_listed(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = mixed_ledger(inst.state_dir / LEDGER)

    out = run(inst, capsys, "--apply")

    costs = [x["cost"] for x in session_lines(ledger, "falls")]
    assert [c["basis"] for c in costs] == ["unknown", "unknown"]
    assert [c.get("incremental_usd") for c in costs] == [None, None]
    assert "falls" in out


def test_the_recorded_total_falls_to_the_session_increment_total(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    """A unit shaped like the worked session: nine calls whose stored totals sum to 147.80
    and whose own spends sum to the session's final 25.39."""
    stored = [2.63, 5.49, 13.18, 15.40, 19.77, 20.62, 21.40, 23.92, 25.39]
    ledger = write_ledger(
        inst.state_dir / LEDGER,
        *(
            legacy_line(total, at=at(n), node=f"step{n}", session_id="worked", resumed=n > 0)
            for n, total in enumerate(stored)
        ),
    )

    unit = line_with(run(inst, capsys), "add-marker/1")
    assert "147.80" in unit
    assert "25.39" in unit

    run(inst, capsys, "--apply")
    costs = [x["cost"] for x in session_lines(ledger, "worked")]
    assert sum(c["incremental_usd"] for c in costs) == pytest.approx(25.39)
    assert costs[-1]["cumulative_usd"] == 25.39


def summary_line(unit: str, change: str, cost: float, when: str = at(0)) -> dict:
    measured = {"calls": 1, "cost_usd": cost}
    return {
        "kind": "summary",
        "at": when,
        "unit": unit,
        "change": change,
        "repo": "app",
        **measured,
        "measured": measured,
        "estimated": {"calls": 0},
    }


def test_a_summary_whose_detail_survives_is_recomputed_through_the_roll_up(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = write_ledger(
        inst.state_dir / LEDGER,
        legacy_line(2.0, at=at(0), node="tests", session_id="s"),
        legacy_line(5.0, at=at(1), node="implement", session_id="s", resumed=True),
        summary_line("add-marker/1", "add-marker", 7.0, at(1)),
    )
    expected = write_ledger(
        inst.state_dir / "expected.jsonl",
        costed_line(2.0, 2.0, basis="backfilled", at=at(0), node="tests", session_id="s"),
        costed_line(
            3.0, 5.0, basis="backfilled", at=at(1), node="implement", session_id="s", resumed=True
        ),
    )
    roll_up_change(expected, "add-marker")
    (recomputed,) = [x for x in lines_of(expected) if x["kind"] == "summary"]

    run(inst, capsys, "--apply")

    (summary,) = [
        x for x in lines_of(ledger) if x["kind"] == "summary" and x["unit"] == "add-marker/1"
    ]
    assert summary["measured"]["cost_usd"] == pytest.approx(5.0)
    assert summary["measured"]["cost_usd"] == pytest.approx(recomputed["measured"]["cost_usd"])
    assert summary.get("cost_basis") != "cumulative_summed"


def test_a_summary_without_detail_is_marked_cumulative_summed_and_listed(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger = write_ledger(
        inst.state_dir / LEDGER,
        summary_line("gone/1", "gone", 12.5),
        legacy_line(2.0, at=at(0), session_id="s"),
    )

    out = run(inst, capsys, "--apply")

    (summary,) = [x for x in lines_of(ledger) if x["kind"] == "summary"]
    assert summary["cost_basis"] == "cumulative_summed"
    assert summary["measured"]["cost_usd"] == 12.5
    assert "gone/1" in out
    assert "cumulative_summed" in out


def test_a_summary_older_than_a_detail_row_keeps_its_cost_and_is_marked(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rows after an archived summary are not the ones it was built from: the roll-up folds
    them in rather than replacing the summary."""
    ledger = write_ledger(
        inst.state_dir / LEDGER,
        summary_line("add-marker/1", "add-marker", 10.0, at(5)),
        legacy_line(1.0, at=at(9), session_id="late"),
    )

    out = run(inst, capsys, "--apply")

    (summary,) = [x for x in lines_of(ledger) if x["kind"] == "summary"]
    assert summary["measured"]["cost_usd"] == pytest.approx(11.0)
    assert summary["cost_basis"] == "cumulative_summed"
    assert "add-marker/1" in out
    assert "cumulative_summed" in out
