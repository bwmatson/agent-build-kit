"""Answering a reviewer in the threads they opened, after the push."""

import json
from pathlib import Path

from agent_build_kit.pipeline.pr_replies import MARKER, build_post_replies, own_posts, parse_answer
from tests.forges.stand_in import StandInForge, lookup

ANSWER = json.dumps(
    {
        "replies": [
            {"comment_id": 11, "body": "Now a frozen BaseModel."},
            {"comment_id": 12, "body": "No reason — moved to the top."},
        ],
        "summary": "Also dropped the /mcp key, per the spec change.",
    }
)


def post(tmp_path: Path, forge: StandInForge, text: str = ANSWER) -> list[str]:
    lines: list[str] = []
    build_post_replies(root=tmp_path, for_repo=lookup(forge), log=lines.append)(
        repo="platform", pr=17, answer_text=text, sha="0123456789abcdef"
    )
    return lines


def test_each_reply_goes_in_its_own_comment_s_thread(tmp_path: Path) -> None:
    forge = StandInForge()
    post(tmp_path, forge)

    assert [note for note, _ in forge.replies] == ["11", "12"]
    assert len(forge.comments) == 1, "the summary is one comment on the PR itself"


def test_a_reply_names_the_commit_it_describes_and_is_marked(tmp_path: Path) -> None:
    """The commit, so the reviewer can see the change; the marker, so the
    next rework does not read the pipeline's words as the reviewer's."""
    forge = StandInForge()
    post(tmp_path, forge)

    _, body = forge.replies[0]
    assert "012345678" in body
    assert MARKER in body


def test_everything_posted_is_recorded_for_the_poller(tmp_path: Path) -> None:
    """A reply creates a review of its own, with no body to mark — so its id
    is what the poller has to be told to skip."""
    post(tmp_path, StandInForge())

    assert own_posts(tmp_path, "example/app", 17) == {
        "reply-11",
        "review-11",
        "reply-12",
        "review-12",
        "comment-1",
    }


def test_one_bad_comment_id_does_not_cost_the_other_replies(tmp_path: Path) -> None:
    lines = post(tmp_path, StandInForge(failing_replies={"11"}))

    assert "reply-12" in own_posts(tmp_path, "example/app", 17)
    assert any("comment 11 not posted" in line for line in lines)


def test_a_rework_that_did_not_answer_in_json_posts_nothing(tmp_path: Path) -> None:
    forge = StandInForge()
    lines = post(tmp_path, forge, text="Done. Everything is fixed.")

    assert forge.replies == [] and forge.comments == []
    assert "no replies posted" in lines[0]


def test_the_answer_is_the_last_json_in_the_message() -> None:
    """An agent may quote JSON while it works; the answer comes last."""
    text = 'I saw {"approved": false} earlier.\n\n' + ANSWER

    answer = parse_answer(text)

    assert answer is not None
    assert [r.comment_id for r in answer.replies] == ["11", "12"]
