"""The summary page: rewritten whenever the unit store is written, as the graph
page is, and never able to fail that write (spec: usage-reporting)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli.pipeline import store_for
from agent_build_kit.installation import Installation
from tests.conftest import make_installation
from tests.factories import unit
from tests.ledger_lines import agent_line, fixture_ledger, write_ledger


def test_the_page_is_written_when_the_store_is(installation: Installation) -> None:
    fixture_ledger(installation.state_dir / "usage-ledger.jsonl")

    store_for(installation).upsert(
        [
            unit("add-marker/1"),
            unit("add-marker/2", repo="platform"),
            unit("feature/1", change="feature"),
        ]
    )

    page = installation.usage_page.read_text()
    assert "add-marker" in page
    assert "feature" in page
    assert "1.75" in page, "a change's total cost"


def test_the_page_names_the_most_expensive_units_first(installation: Installation) -> None:
    write_ledger(
        installation.state_dir / "usage-ledger.jsonl",
        agent_line(unit="add-marker/1", cost_usd=0.5),
        agent_line(unit="add-marker/2", session_id="sess-2", cost_usd=9.5),
        agent_line(unit="feature/1", change="feature", session_id="sess-3", cost_usd=3.5),
    )

    store_for(installation).upsert(
        [unit("add-marker/1"), unit("add-marker/2"), unit("feature/1", change="feature")]
    )

    page = installation.usage_page.read_text()
    assert page.index("add-marker/2") < page.index("feature/1") < page.index("add-marker/1")


def test_the_page_follows_the_ledger_on_the_next_write(installation: Installation) -> None:
    store = store_for(installation)
    store.upsert([unit("add-marker/1")])
    write_ledger(installation.state_dir / "usage-ledger.jsonl", agent_line(cost_usd=4.25))

    store.set_state("add-marker/1", "running")

    assert "4.25" in installation.usage_page.read_text()


def test_the_page_comes_from_the_configured_path(tmp_path: Path) -> None:
    inst = make_installation(tmp_path, planning={"usage_page": "reports/spend.md"})
    fixture_ledger(inst.state_dir / "usage-ledger.jsonl")

    store_for(inst).upsert([unit("add-marker/1")])

    assert (tmp_path / "reports" / "spend.md").exists()
    assert not (tmp_path / "docs" / "unit_cost.md").exists()


def test_a_ledger_line_cut_off_inside_a_multibyte_character_does_not_fail_the_store_write(
    installation: Installation,
) -> None:
    ledger = write_ledger(installation.state_dir / "usage-ledger.jsonl", agent_line(cost_usd=6.5))
    with ledger.open("ab") as handle:
        handle.write(b'{"kind":"agent","outcome":"\xe2\x80')
    store = store_for(installation)

    store.upsert([unit("add-marker/1")])

    assert [u.id for u in store.all()] == ["add-marker/1"]
    assert "6.50" in installation.usage_page.read_text()


def test_a_page_that_fails_for_any_reason_does_not_fail_the_store_write(
    installation: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the page could not be built")

    monkeypatch.setattr("agent_build_kit.pipeline.usage_report.write_page", broken)
    store = store_for(installation)

    store.upsert([unit("add-marker/1")])

    assert [u.id for u in store.all()] == ["add-marker/1"]


def test_an_unwritable_page_does_not_fail_the_store_write_and_is_reported_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(tmp_path, planning={"usage_page": "reports/unit_cost.md"})
    (tmp_path / "reports").write_text("a file where the page's directory should be")
    fixture_ledger(inst.state_dir / "usage-ledger.jsonl")
    store = store_for(inst)
    capsys.readouterr()

    store.upsert([unit("add-marker/1")])

    assert [u.id for u in store.all()] == ["add-marker/1"]
    said = [x for x in capsys.readouterr().out.splitlines() if "unit_cost.md" in x or "usage" in x]
    assert len(said) == 1
