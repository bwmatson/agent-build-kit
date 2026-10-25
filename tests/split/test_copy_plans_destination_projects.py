"""A moved change's plan record is hashed under the destination's projects, not the active
workspace's, so the destination's own tick finds the plan current (spec: project-resolution)."""

import json

from agent_build_kit.cli.pipeline import plan_digest, record_plans
from agent_build_kit.split.copy import carry_out
from agent_build_kit.split.select import plan_split
from tests.split_sources import source_installation, write_change


def test_a_moved_plan_is_hashed_under_the_projects_the_destination_declares(tmp_path):
    destination = source_installation(tmp_path / "destination", app=("web",))
    source = source_installation(tmp_path / "source")
    directory = write_change(source, "moves", ["app"])
    (directory / "tasks.md").write_text(
        "# Tasks\n\nAcceptance: none — a fixture about plans\n\n"
        "## 1. [app] [unit-test] Group 1\n\n- [ ] 1.1 Test: it\n- [ ] 1.2 Edit `web/src/app.ts`.\n"
    )
    record_plans(source, {"moves": {"hash": "h", "attempts": 0, "ok": True}})

    carry_out(source, destination, plan_split(source, "app"))

    moved = destination.changes_dir / "moves" / "tasks.md"
    written = json.loads((destination.state_dir / "planned.json").read_text())["moves"]["hash"]
    assert written == plan_digest(moved, inst=destination)
    assert written != plan_digest(moved, inst=source)
