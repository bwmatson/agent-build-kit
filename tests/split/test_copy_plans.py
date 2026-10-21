"""A split writes a moved change's plan record, and the copied units read back."""

import argparse
import hashlib
import json

from agent_build_kit.cli import pipeline as pipeline_cli
from agent_build_kit.cli.pipeline import record_plans
from agent_build_kit.cli.report_cmd import cmd_report
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.work_graph import specification_text
from agent_build_kit.split import scrubbing
from agent_build_kit.split.copy import carry_out, outstanding
from agent_build_kit.split.select import plan_split
from tests.factories import new_unit
from tests.split_sources import source_installation, write_change, write_units


def installations(tmp_path):
    destination = source_installation(tmp_path / "destination")
    return source_installation(tmp_path / "source"), destination


def written_plans(destination):
    return json.loads((destination.state_dir / "planned.json").read_text())


def test_a_moved_changes_plan_record_is_written_with_a_hash_of_the_destination_text(tmp_path):
    source, destination = installations(tmp_path)
    write_change(source, "moves", ["app"])
    write_change(source, "stays", ["lib"])
    record_plans(
        source,
        {
            "moves": {"hash": "of-the-source-text", "attempts": 2, "ok": True},
            "stays": {"hash": "other", "attempts": 0, "ok": True},
        },
    )

    carry_out(source, destination, plan_split(source, "app"))

    text = (destination.changes_dir / "moves" / "tasks.md").read_text()
    digest = hashlib.sha256(specification_text(text).encode()).hexdigest()
    assert written_plans(destination) == {
        "moves": {"hash": digest, "sizing": "", "attempts": 0, "ok": True}
    }


def test_a_moved_record_keeps_the_sizing_it_was_made_under_and_a_rerun_has_nothing_to_write(
    tmp_path,
):
    source, destination = installations(tmp_path)
    write_change(source, "moves", ["app"])
    record_plans(
        source, {"moves": {"hash": "h", "sizing": "its-digest", "attempts": 0, "ok": True}}
    )
    plan = plan_split(source, "app")

    carry_out(source, destination, plan)

    assert written_plans(destination)["moves"]["sizing"] == "its-digest"
    assert not outstanding(source, destination, plan)


def test_a_scrubbed_change_keeps_a_matching_hash(tmp_path, monkeypatch):
    source, destination = installations(tmp_path)
    directory = write_change(source, "moves", ["app"])
    tasks = directory / "tasks.md"
    tasks.write_text(tasks.read_text() + "\nWorks on secret-term.\n")
    record_plans(source, {"moves": {"hash": "old", "attempts": 1, "ok": True}})
    monkeypatch.setattr(scrubbing, "terms_for", lambda *_, **__: ["secret-term"])
    monkeypatch.setattr(
        scrubbing, "scrub_text", lambda text, terms: text.replace("secret-term", "<redacted>")
    )

    carry_out(source, destination, plan_split(source, "app"), scrub=True)

    text = (destination.changes_dir / "moves" / "tasks.md").read_text()
    assert "secret-term" not in text
    digest = hashlib.sha256(specification_text(text).encode()).hexdigest()
    assert written_plans(destination)["moves"]["hash"] == digest


def test_a_change_with_no_source_record_gets_none(tmp_path):
    source, destination = installations(tmp_path)
    write_change(source, "moves", ["app"])
    write_change(source, "also", ["app"])
    record_plans(source, {"also": {"hash": "h", "attempts": 0, "ok": True}})

    carry_out(source, destination, plan_split(source, "app"))

    assert set(written_plans(destination)) == {"also"}


def test_status_and_report_print_for_a_copied_unit_whose_run_log_the_destination_lacks(
    tmp_path, monkeypatch, capsys
):
    source, destination = installations(tmp_path)
    write_change(source, "moves", ["app"])
    store = write_units(source, new_unit("moves/1", state="merged"))
    store.set_run_log("moves/1", "moves-1.log")
    store.set_trace("moves/1", "trace-ref")

    carry_out(source, destination, plan_split(source, "app"))

    copied = UnitStore(destination.state_dir / "units.json").get("moves/1")
    assert copied.run_log == "moves-1.log"
    monkeypatch.setattr(pipeline_cli, "current_usage", lambda: None)
    assert pipeline_cli.cmd_status(argparse.Namespace(), destination) == 0
    assert "units: 1 merged" in capsys.readouterr().out
    arguments = argparse.Namespace(
        by="unit",
        since=None,
        change=None,
        unit=None,
        include_estimates=False,
        waits=False,
        context=False,
        json=False,
    )
    assert cmd_report(arguments, destination) == 0
