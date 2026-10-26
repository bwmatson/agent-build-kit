"""`--scrub` also replaces issue and pull-request references in moved text and records
(spec: stored-text-scrub)."""

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.split import scrubbing
from agent_build_kit.split.copy import carry_out
from agent_build_kit.split.scrubbing import scrub_counts
from agent_build_kit.split.select import plan_split
from tests.factories import new_unit
from tests.split_sources import source_installation, write_change, write_units

REFERENCE = "example/app#15"


@pytest.fixture(autouse=True)
def no_terms(monkeypatch):
    """Only the reference rule is under test: the installation has no identifying terms."""
    monkeypatch.setattr(scrubbing, "terms_for", lambda installation, *, target=None: [])


def installations(tmp_path):
    destination = source_installation(tmp_path / "destination")
    return source_installation(tmp_path / "source"), destination


def test_a_moved_file_and_a_moved_record_lose_their_references(tmp_path):
    source, destination = installations(tmp_path)
    change = write_change(source, "moves", ["app"])
    (change / "proposal.md").write_text(f"# moves\n\nSee {REFERENCE}.\n")
    write_units(source, new_unit("moves/1", state="failed", feedback=f"closed {REFERENCE}"))

    carry_out(source, destination, plan_split(source, "app"), scrub=True)

    moved = (destination.changes_dir / "moves" / "proposal.md").read_text()
    assert "app#15" not in moved
    assert "<ref>" in moved
    feedback = UnitStore(destination.state_dir / "units.json").get("moves/1").feedback
    assert "app#15" not in feedback
    assert "<ref>" in feedback


def test_the_dry_run_counts_the_references(tmp_path):
    source, destination = installations(tmp_path)
    change = write_change(source, "moves", ["app"])
    (change / "proposal.md").write_text(f"# moves\n\nSee {REFERENCE}.\n")
    write_units(source, new_unit("moves/1", state="merged", feedback=f"closed {REFERENCE}"))

    counts = scrub_counts(source, plan_split(source, "app"))

    assert (counts.files, counts.records) == (1, 1)
    assert counts.substitutions == 2
