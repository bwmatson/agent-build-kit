"""What the build path hands the description, and what it records for it.

The open-pull-request step gives the builder the planning repo's changes
directory, which is what makes the Why and the goal appear in a real pull
request; an approving review records one entry for a point given both as an
optional finding and as a follow-up.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.graph.test_build_path import build, fresh
from tests.graph.test_remaining_paths import capturing

REASON = "Reviewers cannot tell from the pull request why the work exists."
GOAL = "Done when a loopback server answers the read endpoints."
FOLLOW_UPS = Path("openspec") / "changes" / "add-marker" / "follow-ups.md"


def write_change(planning: Path) -> None:
    change = planning / "openspec" / "changes" / "add-marker"
    change.mkdir(parents=True)
    (change / "proposal.md").write_text(
        f"# Proposal\n\n## Why\n\n{REASON}\n\n## What Changes\n\n- x\n"
    )
    (change / "tasks.md").write_text(
        f"# Tasks\n\nAcceptance: none — a fixture\n\n## 1. [app] [tier1] Serve\n\n{GOAL}\n\n"
        "- [ ] 1.1 Test: it answers.\n- [ ] 1.2 Do it.\n"
    )


def test_the_pull_request_opened_for_a_unit_opens_with_its_why_and_goal(tmp_path: Path) -> None:
    write_change(tmp_path / "meta")
    recorder = fresh(tmp_path)
    bodies: list[dict[str, str]] = []

    build(tmp_path, recorder, open_pr=capturing(recorder, bodies))

    assert bodies
    for opened in (bodies[0]["body"], bodies[0]["stacked_body"]):
        assert opened.startswith("## Why")
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

    recorded = (tmp_path / "meta" / FOLLOW_UPS).read_text()
    for point in (located, bare, other):
        assert f"- {point}" in recorded, "the file keeps every point"
    body = bodies[0]["body"]
    assert f"- {located}" in body
    assert bare not in body
    assert f"- {other}" in body
