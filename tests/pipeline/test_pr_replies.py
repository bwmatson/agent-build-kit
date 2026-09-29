"""Answering a reviewer in the threads they opened, after the push."""

import json
from collections.abc import Collection
from pathlib import Path

from agent_build_kit.forges import RepoId
from agent_build_kit.pipeline.pr_replies import MARKER, build_post_replies, own_posts, parse_answer

ANSWER = json.dumps(
    {
        "replies": [
            {"comment_id": 11, "body": "Now a frozen BaseModel."},
            {"comment_id": 12, "body": "No reason — moved to the top."},
        ],
        "summary": "Also dropped the /mcp key, per the spec change.",
    }
)


class FakeForge:
    """A host that records what it was asked to post and hands back ids.

    Two ids per reply, as GitHub's forge really returns: the reply itself and
    the bodyless review it creates. What the wire calls look like is the
    forge's own test; this one is about which thread each reply lands in and
    what gets recorded.
    """

    def __init__(self, *, failing: Collection[str] = ()) -> None:
        self.replies: list[tuple[str, str]] = []
        self.comments: list[str] = []
        self.failing = failing

    def post_reply(self, repo: RepoId, pr: int, *, note_id: str, body: str) -> list[str]:
        if note_id in self.failing:
            raise RuntimeError("404 Not Found")
        self.replies.append((note_id, body))
        return [f"PRRC_{note_id}", f"PRR_9{note_id}"]

    def post_comment(self, repo: RepoId, pr: int, *, body: str) -> list[str]:
        self.comments.append(body)
        return ["IC_summary"]


def lookup(forge: FakeForge):
    def for_repo(repo: str) -> tuple[FakeForge, RepoId]:
        return forge, RepoId(forge="github", account="example", name="platform")

    return for_repo


def post(tmp_path: Path, forge: FakeForge, text: str = ANSWER) -> list[str]:
    lines: list[str] = []
    build_post_replies(root=tmp_path, for_repo=lookup(forge), log=lines.append)(
        repo="platform", pr=17, answer_text=text, sha="0123456789abcdef"
    )
    return lines


def test_each_reply_goes_in_its_own_comment_s_thread(tmp_path: Path) -> None:
    forge = FakeForge()
    post(tmp_path, forge)

    assert [note for note, _ in forge.replies] == ["11", "12"]
    assert len(forge.comments) == 1, "the summary is one comment on the PR itself"


def test_a_reply_names_the_commit_it_describes_and_is_marked(tmp_path: Path) -> None:
    """The commit, so the reviewer can see the change; the marker, so the
    next rework does not read the pipeline's words as the reviewer's."""
    forge = FakeForge()
    post(tmp_path, forge)

    _, body = forge.replies[0]
    assert "012345678" in body
    assert MARKER in body


def test_everything_posted_is_recorded_for_the_poller(tmp_path: Path) -> None:
    """A reply creates a review of its own, with no body to mark — so its id
    is what the poller has to be told to skip."""
    post(tmp_path, FakeForge())

    assert own_posts(tmp_path, "example/platform", 17) == {
        "PRRC_11",
        "PRR_911",
        "PRRC_12",
        "PRR_912",
        "IC_summary",
    }


def test_one_bad_comment_id_does_not_cost_the_other_replies(tmp_path: Path) -> None:
    lines = post(tmp_path, FakeForge(failing={"11"}))

    assert "PRRC_12" in own_posts(tmp_path, "example/platform", 17)
    assert any("comment 11 not posted" in line for line in lines)


def test_a_rework_that_did_not_answer_in_json_posts_nothing(tmp_path: Path) -> None:
    forge = FakeForge()
    lines = post(tmp_path, forge, text="Done. Everything is fixed.")

    assert forge.replies == [] and forge.comments == []
    assert "no replies posted" in lines[0]


def test_the_answer_is_the_last_json_in_the_message() -> None:
    """An agent may quote JSON while it works; the answer comes last."""
    text = 'I saw {"approved": false} earlier.\n\n' + ANSWER

    answer = parse_answer(text)

    assert answer is not None
    assert [r.comment_id for r in answer.replies] == ["11", "12"]
