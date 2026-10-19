"""A unit that carries groups of another change builds its own change's groups first and then the
carried ones, one pair each, each pair naming its own change (spec: per-group-commits)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.units import Member
from tests.graph.branch_fakes import TRAILER, built, messages, subjects
from tests.graph.test_per_group_build import group_named

CARRIED = Member(change="sample-change", groups=(7, 8))


def test_own_groups_are_built_first_then_the_carried_ones_each_in_its_own_change(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(
        tmp_path,
        groups={
            "add-marker": {1: ("Own one", "Done when own one."), 2: ("Own two", "")},
            "sample-change": {
                7: ("Carried seven", "Done when carried seven."),
                8: ("Carried eight", ""),
            },
        },
        carries=(CARRIED,),
    )

    assert outcome.status == "open"
    assert subjects(repo) == [
        "test: Own one",
        "feat: Own one",
        "test: Own two",
        "feat: Own two",
        "test: Carried seven",
        "feat: Carried seven",
        "test: Carried eight",
        "feat: Carried eight",
    ]
    prompts = recorder.prompts[:8]
    assert [group_named(prompt) for prompt in prompts] == list("11227788")
    own, carried = prompts[:4], prompts[4:]
    assert all("openspec/changes/add-marker" in prompt for prompt in own)
    assert not any("sample-change" in prompt for prompt in own)
    assert all("openspec/changes/sample-change" in prompt for prompt in carried)
    assert not any("openspec/changes/add-marker" in prompt for prompt in carried)
    carried_commit = messages(repo)[4]
    assert "Done when carried seven." in carried_commit, "the goal is read from its own change"
    assert carried_commit.splitlines()[-1] == TRAILER
