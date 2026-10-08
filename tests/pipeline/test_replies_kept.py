"""An owed reply stays owed until it is posted or found already posted."""

import json
from pathlib import Path

from agent_build_kit.forges import RepoId
from agent_build_kit.pipeline.pr_replies import (
    MARKER,
    build_post_replies,
    own_posts,
    parse_answer,
)
from tests.forges.stand_in import StandInForge, lookup

ANSWER = json.dumps(
    {
        "replies": [
            {"comment_id": 11, "body": "Now a frozen BaseModel."},
            {"comment_id": 12, "body": "No reason — moved to the top."},
        ],
        "summary": "Also dropped the /mcp key.",
    }
)
SLUG = "example/app"


class Refusing(StandInForge):
    """A host that answers a post the way the retry layer does once it has given up on
    one: no ids, and nothing stored."""

    def post_reply(self, repo: RepoId, pr: int, *, note_id: str, body: str) -> list[str]:
        return []

    def post_comment(self, repo: RepoId, pr: int, *, body: str) -> list[str]:
        return []


class Landed(StandInForge):
    """A host that already holds the reply to note 11, whose answer the pipeline lost."""

    def __init__(self) -> None:
        super().__init__()
        self.asked: list[tuple[str, str, str | None]] = []

    def comment_exists(
        self, repo: RepoId, pr: int, marker: str, body: str, *, reply_to: str | None = None
    ) -> str | None:
        self.asked.append((marker, body, reply_to))
        return "reply-11-earlier" if reply_to == "11" else None


def post(tmp_path: Path, forge: StandInForge, text: str = ANSWER) -> str:
    return build_post_replies(root=tmp_path, for_repo=lookup(forge), log=lambda line: None)(
        repo="platform", pr=17, answer_text=text, sha="0123456789abcdef"
    )


def owed(left: str) -> list[str]:
    answer = parse_answer(left) if left else None
    return [r.comment_id for r in answer.replies] if answer else []


def test_a_host_that_refuses_everything_leaves_every_reply_and_the_summary_owed(
    tmp_path: Path,
) -> None:
    left = post(tmp_path, Refusing())

    answer = parse_answer(left)
    assert answer is not None
    assert [r.comment_id for r in answer.replies] == ["11", "12"]
    assert answer.summary == "Also dropped the /mcp key."
    assert own_posts(tmp_path, SLUG, 17) == set()


def test_a_reply_the_host_raised_on_stays_owed_and_the_posted_one_leaves(tmp_path: Path) -> None:
    left = post(tmp_path, StandInForge(failing_replies={"11"}))

    assert owed(left) == ["11"]
    answer = parse_answer(left)
    assert answer is not None and answer.summary == "", "the summary went out"


def test_the_next_pass_posts_what_is_left_once(tmp_path: Path) -> None:
    refusing = StandInForge(failing_replies={"11"})
    left = post(tmp_path, refusing)

    working = StandInForge()
    assert post(tmp_path, working, text=left) == ""

    assert [note for note, _ in working.replies] == ["11"]
    assert [note for note, _ in refusing.replies] == ["12"]
    assert working.comments == [], "the summary was not posted a second time"
    assert {"reply-11", "reply-12"} <= own_posts(tmp_path, SLUG, 17)


def test_a_reply_the_host_already_holds_is_posted_no_more_and_recorded_as_ours(
    tmp_path: Path,
) -> None:
    host = Landed()

    left = post(tmp_path, host)

    assert [note for note, _ in host.replies] == ["12"], "11 is not posted again"
    assert left == ""
    assert "reply-11-earlier" in own_posts(tmp_path, SLUG, 17)
    marker, body, reply_to = host.asked[0]
    assert (marker, reply_to) == (MARKER, "11")
    assert "Now a frozen BaseModel." in body
