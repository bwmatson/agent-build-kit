"""`--scrub` changes moved text and named record fields, never identifiers or code."""

import pytest

from agent_build_kit.pipeline.unit_store import Description, UnitStore
from agent_build_kit.split import scrubbing
from agent_build_kit.split.copy import carry_out
from agent_build_kit.split.scrubbing import scrub_counts
from agent_build_kit.split.select import plan_split
from tests.factories import new_unit
from tests.split_sources import snapshot_tree, source_installation, write_change, write_units

TERM = "secret-term"
HISTORY = (
    {"state": "running", "at": "2026-01-01T10:00:00+00:00"},
    {"state": "failed", "at": "2026-01-01T11:00:00+00:00", "note": f"broke on {TERM}"},
)


class Scrub:
    """A stand-in for the term list and the text pass: one term, and what it saw."""

    def __init__(self) -> None:
        self.targets: list = []
        self.texts: list[str] = []

    def terms_for(self, installation, *, target=None):
        self.targets.append(target)
        return [TERM]

    def scrub_text(self, text, terms):
        self.texts.append(text)
        for term in terms:
            text = text.replace(term, "<redacted>")
        return text


@pytest.fixture
def scrub(monkeypatch):
    fake = Scrub()
    monkeypatch.setattr(scrubbing, "terms_for", fake.terms_for)
    monkeypatch.setattr(scrubbing, "scrub_text", fake.scrub_text)
    return fake


def installations(tmp_path):
    destination = source_installation(tmp_path / "destination")
    return source_installation(tmp_path / "source"), destination


def noisy_unit():
    return new_unit(
        "moves/1",
        state="failed",
        branch=f"spec/{TERM}/moves/1",
        run_log=f"{TERM}.log",
        trace=f"{TERM}-trace",
        feedback=f"fix {TERM}",
        guidance=f"mind {TERM}",
        predecessor_note=f"rebased over {TERM}",
        stack_refusal=f"{TERM} refused",
        description=Description(summary=f"about {TERM}", changes=(f"touches {TERM}",)),
        history=HISTORY,
    )


def test_a_moved_proposal_and_a_records_free_text_are_scrubbed(tmp_path, scrub):
    source, destination = installations(tmp_path)
    change = write_change(source, "moves", ["app"])
    (change / "proposal.md").write_text(f"# moves\n\nSee {TERM}.\n")
    write_units(source, noisy_unit())

    carry_out(source, destination, plan_split(source, "app"), scrub=True)

    assert (destination.changes_dir / "moves" / "proposal.md").read_text() == (
        "# moves\n\nSee <redacted>.\n"
    )
    record = UnitStore(destination.state_dir / "units.json").get("moves/1")
    assert record.feedback == "fix <redacted>"
    assert record.guidance == "mind <redacted>"
    assert record.predecessor_note == "rebased over <redacted>"
    assert record.stack_refusal == "<redacted> refused"
    assert record.description == Description(
        summary="about <redacted>", changes=("touches <redacted>",)
    )
    assert record.history[1]["note"] == "broke on <redacted>"


def test_identifiers_state_and_timestamps_are_never_scrubbed(tmp_path, scrub):
    source, destination = installations(tmp_path)
    write_change(source, "moves", ["app"])
    original = write_units(source, noisy_unit()).get("moves/1")

    carry_out(source, destination, plan_split(source, "app"), scrub=True)

    record = UnitStore(destination.state_dir / "units.json").get("moves/1")
    for field in ("id", "change", "repo", "branch", "run_log", "trace", "state", "history"):
        expected = getattr(original, field)
        actual = getattr(record, field)
        if field == "history":
            assert [(h["state"], h["at"]) for h in actual] == [
                (h["state"], h["at"]) for h in expected
            ]
        else:
            assert actual == expected


def test_a_file_under_a_code_repos_checkout_is_never_read_and_the_moved_repo_is_the_target(
    tmp_path, scrub
):
    source, destination = installations(tmp_path)
    write_change(source, "moves", ["app"])
    checkout = source.checkouts["app"]
    checkout.mkdir(parents=True)
    (checkout / "README.md").write_text(f"checkout-only-marker {TERM}\n")

    carry_out(source, destination, plan_split(source, "app"), scrub=True)

    assert (checkout / "README.md").read_text() == f"checkout-only-marker {TERM}\n"
    assert not [text for text in scrub.texts if "checkout-only-marker" in text]
    assert scrub.targets
    assert all(target == checkout for target in scrub.targets)


def test_without_the_flag_the_bytes_are_unchanged(tmp_path, scrub):
    source, destination = installations(tmp_path)
    change = write_change(source, "moves", ["app"])
    (change / "proposal.md").write_text(f"# moves\n\nSee {TERM}.\n")
    unit = write_units(source, noisy_unit()).get("moves/1")

    carry_out(source, destination, plan_split(source, "app"))

    assert (destination.changes_dir / "moves" / "proposal.md").read_bytes() == (
        change / "proposal.md"
    ).read_bytes()
    assert UnitStore(destination.state_dir / "units.json").get("moves/1") == unit
    assert scrub.texts == []


def test_the_plan_counts_files_records_and_substitutions_and_writes_nothing(tmp_path, scrub):
    source, destination = installations(tmp_path)
    change = write_change(source, "moves", ["app"])
    (change / "proposal.md").write_text(f"# moves\n\nSee {TERM}.\n")
    (change / "design.md").write_text(f"Design for {TERM}.\n")
    write_units(
        source,
        new_unit("moves/1", state="merged", feedback=f"fix {TERM}"),
        new_unit("moves/2", state="merged"),
    )
    before = (snapshot_tree(source.root), snapshot_tree(destination.root))

    counts = scrub_counts(source, plan_split(source, "app"))

    assert (counts.files, counts.records, counts.substitutions) == (2, 1, 3)
    assert (snapshot_tree(source.root), snapshot_tree(destination.root)) == before
