"""`abk report --trusted`: the cost per trusted change and each breach, read from the store, the
ledger and the repos' checkouts (specs: trusted-change-cost, health-thresholds)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from tests.conftest import make_installation
from tests.factories import commit_files, git, init_repo, stored_unit
from tests.forges.mock_host import MockHost, ok
from tests.ledger_lines import agent_line, write_ledger

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)


def ago(days: float) -> str:
    return (NOW - timedelta(days=days)).isoformat()


@dataclass(frozen=True)
class Trusted:
    installation: Installation
    repo: Path
    # The ledger's calls of the first change and the plan review that carries it, written
    # `days` days before the report.
    write_ledger: Callable[[float], None]


def merged_unit(change: str, days: float, **fields):
    stamp = {"state": "merged", "at": ago(days), "cause": "merged"}
    return stored_unit(
        f"{change}/1", change=change, state=UnitState.MERGED, history=(stamp,), **fields
    )


@pytest.fixture
def trusted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Trusted:
    """Five merged changes on one repository: `kept` (45 days, no revert), `undone` (50 days,
    reverted 2 days later by commit), `recent` (5 days), `by-number` (60 days, a pull request
    and no merge commit, reverted 3 days later by a `Reverts` line) and `unknown` (61 days,
    neither a merge commit nor a pull request)."""
    app = init_repo(tmp_path / "app")
    commit_files(app, "base", {"base.txt": "base"}, when=ago(70))
    commit_files(app, "feature (#77)", {"by-number.txt": "x"}, when=ago(60))
    commit_files(app, "Revert feature\n\nReverts example/app#77", {"r1.txt": "x"}, when=ago(57))
    commit_files(app, "undone", {"undone.txt": "x"}, when=ago(50))
    undone = git(app, "rev-parse", "HEAD")
    commit_files(
        app, f"Revert undone\n\nThis reverts commit {undone}.", {"r2.txt": "x"}, when=ago(48)
    )
    commit_files(app, "kept", {"kept.txt": "x"}, when=ago(45))
    kept = git(app, "rev-parse", "HEAD")

    installation = make_installation(
        tmp_path / "planning",
        repos={
            "platform": {"path": str(tmp_path / "platform"), "slug": "example/platform"},
            "app": {"path": str(app), "slug": "example/app", "consumes": ["platform"]},
        },
    )
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    UnitStore(installation.state_dir / "units.json").import_units(
        [
            merged_unit("kept", 45, pr=11, merge_sha=kept),
            merged_unit("undone", 50, pr=22, merge_sha=undone),
            merged_unit("recent", 5, pr=33),
            merged_unit("by-number", 60, pr=77),
            merged_unit("unknown", 61),
        ]
    )
    monkeypatch.chdir(installation.root)
    # The command reloads the settings, so the token is in the environment; no `gh` login is read.
    monkeypatch.setenv("GH_TOKEN", "stand-in")
    monkeypatch.setattr(spans.clock, "now", lambda: NOW)

    summary = {
        "kind": "summary",
        "at": ago(40),
        "unit": "undone/1",
        "change": "undone",
        "repo": "app",
        "measured": {"calls": 1, "cost_usd": 5.0},
        "estimated": {"calls": 0},
        "breakdown": [
            {
                "node": "implement",
                "role": "implement",
                "model": "model-a",
                "measured": {"calls": 1, "cost_usd": 5.0},
                "estimated": {"calls": 0},
            }
        ],
    }

    def write(days: float) -> None:
        write_ledger(
            installation.state_dir / LEDGER_NAME,
            agent_line(unit="kept/1", change="kept", session_id="s1", at=ago(days), cost_usd=1.0),
            agent_line(
                unit="",
                change="kept",
                node="plan",
                role="plan",
                session_id="s2",
                at=ago(days),
                cost_usd=2.0,
            ),
            agent_line(unit="recent/1", change="recent", session_id="s3", at=ago(10), cost_usd=4.0),
            summary,
        )

    return Trusted(installation, app, write)


def run_json(capsys: pytest.CaptureFixture[str]) -> dict:
    code = main(["report", "--trusted", "--json"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert out.strip(), "nothing was printed"
    return json.loads(out)


def snapshot(*roots: Path) -> dict[str, str]:
    return {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_the_json_reports_each_verdict_with_its_cost_and_the_trunk_each_repo_was_read_at(
    trusted: Trusted, capsys: pytest.CaptureFixture[str]
) -> None:
    trusted.write_ledger(20)

    document = run_json(capsys)

    verdicts = {c["change"]: c["verdict"] for c in document["changes"]}
    assert verdicts == {
        "kept": "trusted",
        "undone": "reverted",
        "recent": "pending",
        "by-number": "reverted",
        "unknown": "unchecked",
    }
    costs = {c["change"]: c["cost"] for c in document["changes"]}
    assert costs["kept"] == pytest.approx(3.0)
    assert costs["undone"] == pytest.approx(5.0)
    assert document["latest"]["cost_per_trusted_change"] == pytest.approx(3.0)
    assert document["latest"]["costed"] == 1
    assert document["pending_count"] == 1
    assert document["pending_cost"] == pytest.approx(4.0)
    assert document["unchecked"] == ["unknown"]
    app = json.dumps(document["repos"]["app"])
    assert "main" in app
    assert ago(45)[:10] in app


def test_the_table_names_each_verdict_and_a_breach_with_its_correction(
    trusted: Trusted, capsys: pytest.CaptureFixture[str]
) -> None:
    trusted.write_ledger(1)
    row = trusted.installation.config.health.thresholds.plan_review_share

    code = main(["report", "--trusted"])

    out = capsys.readouterr().out
    assert code == 0
    for pair in (
        "trusted kept",
        "reverted undone",
        "pending recent",
        "reverted by-number",
        "unchecked unknown",
    ):
        assert pair in out
    assert "plan_review_share" in out
    assert row.correction in out
    assert f"{row.limit}" in out


def test_a_unit_the_code_host_cannot_answer_for_is_unchecked_and_the_report_still_succeeds(
    trusted: Trusted, capsys: pytest.CaptureFixture[str]
) -> None:
    trusted.write_ledger(20)
    forges.register(GitHubForge(http=MockHost(ok({"message": "Bad credentials"}, 401))))

    document = run_json(capsys)

    verdicts = {c["change"]: c["verdict"] for c in document["changes"]}
    assert verdicts["by-number"] == "unchecked"
    assert "by-number" in document["unchecked"]


def test_the_table_says_no_threshold_is_breached_when_none_is(
    trusted: Trusted, capsys: pytest.CaptureFixture[str]
) -> None:
    trusted.write_ledger(20)
    row = trusted.installation.config.health.thresholds.plan_review_share

    code = main(["report", "--trusted"])

    out = capsys.readouterr().out
    assert code == 0
    assert "no threshold is breached" in out.lower()
    assert row.correction not in out


def test_the_report_writes_no_file_under_the_installation_or_the_repository(
    trusted: Trusted, capsys: pytest.CaptureFixture[str]
) -> None:
    trusted.write_ledger(1)
    before = snapshot(trusted.installation.root, trusted.repo)

    code = main(["report", "--trusted"])

    assert code == 0
    assert capsys.readouterr().out.strip(), "nothing was printed"
    assert snapshot(trusted.installation.root, trusted.repo) == before


@pytest.mark.parametrize("other", ["--waits", "--context"])
def test_trusted_with_another_report_mode_exits_2_and_prints_neither(
    trusted: Trusted, capsys: pytest.CaptureFixture[str], other: str
) -> None:
    trusted.write_ledger(1)

    code = main(["report", "--trusted", other])

    out = capsys.readouterr().out
    assert code == 2
    assert "plan_review_share" not in out
    assert "pending" not in out
