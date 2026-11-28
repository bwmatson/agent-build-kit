"""What the build path hands the description, and what it records for it.

The open-pull-request step gives the builder the planning repo's changes
directory, which is what makes the Why and the goal appear in a real pull
request; an approving review records one entry for a point given both as an
optional finding and as a follow-up.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.verdict_record import VERDICTS
from packages.worker.tests.graph.test_build_path import build, fresh
from packages.worker.tests.graph.test_remaining_paths import capturing
from tests.factories import activate_with
from tests.progress_support import copy_file, meta_planning

REASON = "Reviewers cannot tell from the pull request why the work exists."
GOAL = "Done when a loopback server answers the read endpoints."


@pytest.fixture(autouse=True)
def tracking_copy(tmp_path: Path) -> None:
    """The planning repo at `<tmp>/meta` with its state directory at `<tmp>/state`."""
    meta_planning(tmp_path)


def write_change(planning: Path) -> None:
    change = planning / "openspec" / "changes" / "add-marker"
    change.mkdir(parents=True)
    (change / "proposal.md").write_text(
        f"# Proposal\n\n## Why\n\n{REASON}\n\n## What Changes\n\n- x\n"
    )
    (change / "tasks.md").write_text(
        f"# Tasks\n\nAcceptance: none — a fixture\n\n## 1. [app] [unit-test] Serve\n\n{GOAL}\n\n"
        "- [ ] 1.1 Test: it answers.\n- [ ] 1.2 Do it.\n"
    )


def test_the_pull_request_opened_for_a_unit_opens_with_its_why_and_goal(tmp_path: Path) -> None:
    write_change(tmp_path / "meta")
    recorder = fresh(tmp_path)
    bodies: list[dict[str, str]] = []

    build(tmp_path, recorder, open_pr=capturing(recorder, bodies))

    assert bodies
    for opened in (bodies[0]["body"], bodies[0]["stacked_body"]):
        assert opened.startswith("## Start here")
        assert opened.index("## Why") < opened.index("## What this pull request does")
        assert REASON in opened
        assert GOAL in opened[opened.index("## What this pull request does") :]


def test_a_point_given_twice_is_recorded_whole_and_listed_once_in_the_description(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    bodies: list[dict[str, str]] = []
    located = "docs/architecture.md:815 — The flake paragraph does not mention the restack path."
    bare = (
        "docs/architecture.md: mention that a merge-time restack meeting a flake parks the child."
    )
    other = "Skip the flake rerun when the command hit its time limit."
    recorder.verdicts = [
        json.dumps(
            {
                "approved": True,
                "feedback": "",
                "findings": [
                    {
                        "file": "docs/architecture.md",
                        "line": 815,
                        "summary": "The flake paragraph does not mention the restack path.",
                        "consequence": "",
                        "done": "",
                        "required": False,
                    }
                ],
                "follow_ups": [
                    {"kind": "optional", "point": bare},
                    {"kind": "optional", "point": other},
                ],
            }
        )
    ]

    build(tmp_path, recorder, open_pr=capturing(recorder, bodies))

    recorded = copy_file(meta_planning(tmp_path), "add-marker", "follow-ups.md").read_text()
    for point in (located, bare, other):
        assert f"- {point}" in recorded, "the file keeps every point"
    body = bodies[0]["body"]
    assert f"- {located}" in body
    assert bare not in body
    assert f"- {other}" in body


def start_section(body: str) -> str:
    return body[body.index("## Start here") :].split("\n## ")[0]


def test_the_start_here_section_lists_the_recorded_results_and_the_verdict_tier(
    tmp_path: Path,
) -> None:
    activate_with(review={"enabled": True})
    recorder = fresh(tmp_path)
    bodies: list[dict[str, str]] = []

    build(tmp_path, recorder, open_pr=capturing(recorder, bodies))

    start = start_section(bodies[0]["body"])
    assert "seen to fail first" not in start, "this build ran no red check"
    assert "unit-test result: passed" in start
    assert "Review took 1 review round" in start
    reason = json.loads((tmp_path / VERDICTS).read_text())["add-marker/1"]["reason"]
    assert f"— {reason}" in start, "the tier line carries the recorded verdict's reason"


def test_a_build_that_changed_a_protected_setting_records_full_and_names_it_in_start_here(
    tmp_path: Path,
) -> None:
    activate_with(review={"enabled": True})
    named = "pyproject.toml: tool.ruff"
    plain, changed = fresh(tmp_path / "plain"), fresh(tmp_path / "changed")
    plain_bodies: list[dict[str, str]] = []
    changed_bodies: list[dict[str, str]] = []

    build(tmp_path / "plain", plain, open_pr=capturing(plain, plain_bodies))
    build(
        tmp_path / "changed",
        changed,
        open_pr=capturing(changed, changed_bodies),
        protected_settings=lambda tree, base, paths: (named,),
    )

    recorded = json.loads((tmp_path / "changed" / VERDICTS).read_text())["add-marker/1"]
    assert recorded["tier"] == "full"
    assert named in recorded["reason"]
    assert f"— {recorded['reason']}" in start_section(changed_bodies[0]["body"])
    default = json.loads((tmp_path / "plain" / VERDICTS).read_text())["add-marker/1"]
    assert "protected setting" not in default["reason"]
    assert "protected setting" not in start_section(plain_bodies[0]["body"])


def test_with_review_on_and_no_readable_verdict_the_pull_request_opens_without_a_tier_line(
    tmp_path: Path,
) -> None:
    activate_with(review={"enabled": True})
    (tmp_path / VERDICTS).mkdir()  # a directory where the file goes: nothing can be recorded
    recorder = fresh(tmp_path)
    bodies: list[dict[str, str]] = []

    build(tmp_path, recorder, open_pr=capturing(recorder, bodies))

    assert bodies, "the pull request was still opened"
    start = start_section(bodies[0]["body"])
    assert "Review tier" not in start
    assert "seen to fail first" not in start, "this build ran no red check"
