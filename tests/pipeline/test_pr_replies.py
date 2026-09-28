"""Answering a reviewer in the threads they opened, after the push."""

import json
from collections.abc import Collection
from pathlib import Path

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


class FakeGitHub:
    def __init__(self, *, failing: Collection[int] = ()) -> None:
        self.calls: list[list[str]] = []
        self.failing = failing

    def __call__(self, args: list[str], *, slug: str) -> dict:
        self.calls.append(args)
        path = args[4] if args[2:4] == ["-X", "POST"] else args[2]
        if "/replies" in path:
            comment = int(path.split("/comments/")[1].split("/")[0])
            if comment in self.failing:
                raise RuntimeError("404 Not Found")
            return {"node_id": f"PRRC_{comment}", "pull_request_review_id": 900 + comment}
        if "/reviews/" in path:
            return {"node_id": f"PRR_{path.rsplit('/', 1)[1]}"}
        return {"node_id": "IC_summary"}


def post(tmp_path: Path, github: FakeGitHub, text: str = ANSWER) -> list[str]:
    lines: list[str] = []
    build_post_replies(root=tmp_path, post=github, log=lines.append)(
        repo="platform", pr=17, answer_text=text, sha="0123456789abcdef"
    )
    return lines


def test_each_reply_goes_in_its_own_comment_s_thread(tmp_path: Path) -> None:
    github = FakeGitHub()
    post(tmp_path, github)

    targets = [c[4] for c in github.calls if c[2:4] == ["-X", "POST"]]
    assert targets == [
        "repos/example/platform/pulls/17/comments/11/replies",
        "repos/example/platform/pulls/17/comments/12/replies",
        "repos/example/platform/issues/17/comments",
    ]


def test_a_reply_names_the_commit_it_describes_and_is_marked(tmp_path: Path) -> None:
    """The commit, so the reviewer can see the change; the marker, so the
    next rework does not read the pipeline's words as the reviewer's."""
    github = FakeGitHub()
    post(tmp_path, github)

    body = github.calls[0][-1]
    assert "012345678" in body
    assert MARKER in body


def test_everything_posted_is_recorded_for_the_poller(tmp_path: Path) -> None:
    """A reply creates a review of its own, with no body to mark — so its id
    is what the poller has to be told to skip."""
    post(tmp_path, FakeGitHub())

    assert own_posts(tmp_path, "example/platform", 17) == {
        "PRRC_11",
        "PRR_911",
        "PRRC_12",
        "PRR_912",
        "IC_summary",
    }


def test_one_bad_comment_id_does_not_cost_the_other_replies(tmp_path: Path) -> None:
    lines = post(tmp_path, FakeGitHub(failing={11}))

    assert "PRRC_12" in own_posts(tmp_path, "example/platform", 17)
    assert any("comment 11 not posted" in line for line in lines)


def test_a_rework_that_did_not_answer_in_json_posts_nothing(tmp_path: Path) -> None:
    github = FakeGitHub()
    lines = post(tmp_path, github, text="Done. Everything is fixed.")

    assert github.calls == []
    assert "no replies posted" in lines[0]


def test_the_answer_is_the_last_json_in_the_message() -> None:
    """An agent may quote JSON while it works; the answer comes last."""
    text = 'I saw {"approved": false} earlier.\n\n' + ANSWER

    answer = parse_answer(text)

    assert answer is not None
    assert [r.comment_id for r in answer.replies] == [11, 12]
