"""The output file passes through the redaction the result text does."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.config import ProjectConfig
from agent_build_kit.pipeline.run_log import tier2_output_dir
from agent_build_kit.pipeline.wiring import Tier2Session
from tests.factories import unit
from tests.redaction_fakes import NAME, NOTICE, SECRET, known
from tests.tier2_failure_fakes import checkout, run_returning

OUTPUT = f"FAILED tests/t.py::test_a - key {SECRET}\ntoken={SECRET}\n1 failed in 1s\n"


def _run(tmp_path: Path, *, broken: bool = False) -> tuple[Tier2Session, str]:
    root = checkout(tmp_path)
    session = Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        timeout=5,
        run=run_returning(OUTPUT),
        sha=lambda cwd: "abc1234",
        output_dir=tier2_output_dir(tmp_path / "state"),
        now=lambda: datetime(2026, 10, 11, tzinfo=UTC),
    )
    with known(broken=broken):
        _, snapshot = session.run(cwd=root)
    return session, snapshot


def test_a_known_secret_is_replaced_in_the_file(tmp_path: Path) -> None:
    session, _ = _run(tmp_path)

    assert session.result is not None
    text = Path(session.result.output_file).read_text()
    assert f"[redacted:{NAME}]" in text
    assert SECRET not in text


def test_a_raising_redaction_leaves_the_notice_and_says_so_without_changing_the_outcome(
    tmp_path: Path,
) -> None:
    session, snapshot = _run(tmp_path, broken=True)

    assert session.result is not None
    assert session.result.failed == 1
    text = Path(session.result.output_file).read_text()
    assert NOTICE in text
    assert SECRET not in text
    assert "withheld" in snapshot.split("<details>")[0]


def test_each_commands_withheld_notice_stays_on_its_own_line(tmp_path: Path) -> None:
    root = checkout(tmp_path, "api", "web")
    session = Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        timeout=5,
        run=run_returning(OUTPUT),
        sha=lambda cwd: "abc1234",
        projects=[ProjectConfig(path="api"), ProjectConfig(path="web")],
        output_dir=tier2_output_dir(tmp_path / "state"),
        now=lambda: datetime(2026, 10, 11, tzinfo=UTC),
    )
    with known(broken=True):
        session.run(cwd=root)

    assert session.result is not None
    lines = Path(session.result.output_file).read_text().splitlines()
    assert lines == [NOTICE, NOTICE]
