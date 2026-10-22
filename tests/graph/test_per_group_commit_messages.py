"""Each commit of a per-group build says why: a fixed sentence for what it holds, then the group's
"Done when" sentence when it has one, and the unit trailer stays (spec: per-group-commits). The
branch is real, so the messages are read back from git."""

from __future__ import annotations

from pathlib import Path

from tests.graph.branch_fakes import TRAILER, Groups, built, messages

GOALS: Groups = {
    1: ("Parse the key", "Done when the key parses."),
    2: ("Use the key", ""),
    3: ("Drop the key", "Done when the key is gone."),
}


def proposal(tmp_path: Path) -> None:
    """The change's proposal, whose Why every body opens with."""
    directory = tmp_path / "meta" / "openspec" / "changes" / "add-marker"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "proposal.md").write_text("## Why\n\nThe key is unread. More.\n\n## What\n\nx\n")


def body_of(message: str) -> str:
    """What is between the subject and the trailer."""
    _, _, rest = message.partition("\n")
    return rest.removesuffix(TRAILER).strip()


def test_each_body_has_the_fixed_sentence_and_the_groups_goal_when_it_has_one(
    tmp_path: Path,
) -> None:
    proposal(tmp_path)
    _, outcome, repo = built(tmp_path, groups={"add-marker": GOALS})

    assert outcome.status == "open"
    made = messages(repo)
    assert len(made) == 6
    fixed: dict[str, set[str]] = {"test": set(), "feat": set()}
    for index, message in enumerate(made):
        goal = GOALS[index // 2 + 1][1]
        body = body_of(message)
        sentence = body.replace(goal, "").strip() if goal else body
        assert sentence, f"{message!r} says nothing of what it holds"
        if goal:
            assert goal in body
            assert body.index(sentence) < body.index(goal), "the fixed sentence comes first"
        else:
            assert "Done when" not in body, "a group without a goal has the fixed sentence alone"
        fixed[message.split(":", 1)[0]].add(sentence)
    assert all(len(sentences) == 1 for sentences in fixed.values()), "the sentence is fixed"
    assert fixed["test"] != fixed["feat"], "the two kinds of commit say what they hold apart"


def test_every_commit_keeps_the_unit_trailer(tmp_path: Path) -> None:
    proposal(tmp_path)
    _, _, repo = built(tmp_path, groups={"add-marker": GOALS})

    made = messages(repo)
    assert len(made) == 6
    assert all(message.splitlines()[-1] == TRAILER for message in made)
    assert all(body_of(message) for message in made), "a body comes before the trailer"
