"""Reviews made in the web UI reach a unit through the poller as comments (spec: pr-polling).

The review store is real and the host is a fake listing, so what is tested is what the poller
sees of a UI review and what the agent's replies do to it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline import pr_replies
from agent_build_kit.pipeline.pr_poller import Poller
from agent_build_kit.pipeline.pr_replies import MARKER
from agent_build_kit.pipeline.ui_review import with_ui_review, write_back_replies
from agent_build_kit.pipeline.unit_store import ReworkKind
from agent_build_kit.serve.review import THREAD_PREFIX, ReviewStore

UNIT = "feature/2"


class Rig:
    def __init__(self, tmp_path: Path, host: tuple[str, ...] = ("101",)) -> None:
        directory = tmp_path / "reviews"
        directory.mkdir()
        self.store = ReviewStore(directory)
        self.pull = PullRequest(
            number=4,
            head="spec/feature/2",
            base="main",
            state="open",
            conversation=host,
            comment_bodies=tuple(f"host {i}" for i in host),
        )
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.state = tmp_path / "poll.json"

    def list_prs(self) -> Any:
        return with_ui_review(lambda: [self.pull], review_of=lambda _: self.store.read(UNIT))

    def poller(self) -> Poller:
        return Poller(
            repo="app",
            state_path=self.state,
            list_prs=self.list_prs(),
            dispatch=lambda event, number, **kw: self.events.append((event, kw)),
        )

    def listed(self) -> PullRequest:
        return self.list_prs()()[0]

    def poll(self) -> list[tuple[str, dict[str, Any]]]:
        """What one poll dispatched, after a first poll that only records."""
        if not self.state.exists():
            self.poller().poll()
        self.events.clear()
        self.poller().poll()
        return list(self.events)

    def thread(self, body: str = "why this?") -> str:
        return self.store.add_thread(
            UNIT, path="a.py", side="new", line=3, start_line=None, commit="c" * 40, body=body
        ).id


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def kinds(events: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, Any]]:
    return [(event, kw.get("rework")) for event, kw in events]


def test_a_new_ui_comment_is_one_rework_as_a_new_comment(rig: Rig) -> None:
    rig.poll()
    rig.thread()

    events = rig.poll()

    assert kinds(events) == [("rework", ReworkKind.COMMENT)]
    assert events[0][1]["reason"] == "new comment"


def test_a_ui_reply_is_one_rework(rig: Rig) -> None:
    thread = rig.thread()
    rig.poll()
    rig.store.reply(UNIT, thread, "and this?")

    assert kinds(rig.poll()) == [("rework", ReworkKind.COMMENT)]


def test_request_changes_is_one_rework_as_changes_requested(rig: Rig) -> None:
    rig.poll()
    rig.store.decide(UNIT, round=1, decision="request_changes", summary="rework it")

    assert kinds(rig.poll()) == [("rework", ReworkKind.CHANGES_REQUESTED)]


def test_a_second_request_for_changes_in_a_later_round_is_a_rework_of_its_own(rig: Rig) -> None:
    rig.poll()
    rig.store.decide(UNIT, round=1, decision="request_changes", summary="rework it")
    assert kinds(rig.poll()) == [("rework", ReworkKind.CHANGES_REQUESTED)]
    assert rig.poll() == []

    rig.store.decide(UNIT, round=2, decision="request_changes", summary="still wrong")

    assert len(rig.poll()) == 1
    assert rig.poll() == []


def test_what_was_delivered_is_not_delivered_again(rig: Rig) -> None:
    thread = rig.thread()
    rig.store.reply(UNIT, thread, "and this?")
    rig.store.decide(UNIT, round=1, decision="request_changes", summary="")
    rig.poll()
    rig.thread("another")
    assert len(rig.poll()) == 1

    assert rig.poll() == []
    assert rig.poll() == []


def test_ui_comment_ids_cannot_collide_with_the_hosts(tmp_path: Path) -> None:
    rig = Rig(tmp_path, host=("101", "102", THREAD_PREFIX + "abc"))
    thread = rig.thread()
    rig.store.reply(UNIT, thread, "and this?")

    listed = rig.listed()

    added = [i for i in listed.conversation if i not in rig.pull.conversation]
    assert len(added) == 2
    assert all(i.startswith(THREAD_PREFIX) for i in added)
    assert listed.conversation[:3] == rig.pull.conversation
    assert len(set(listed.conversation)) == len(listed.conversation)
    assert "why this?" in listed.comment_bodies and "and this?" in listed.comment_bodies


def test_a_unit_with_no_ui_review_is_listed_as_the_host_has_it(rig: Rig) -> None:
    assert rig.listed() == rig.pull


def test_the_agents_reply_is_written_into_the_thread_it_answers(rig: Rig) -> None:
    thread = rig.thread()
    other = rig.thread("and here?")

    written = write_back_replies(
        rig.store, UNIT, [pr_replies.Reply(comment_id=thread, body="Renamed it")]
    )

    stored = {t.id: t for t in rig.store.read(UNIT).threads}
    assert len(written) == 1
    assert len(stored[thread].replies) == 1
    assert "Renamed it" in stored[thread].replies[0].body
    assert MARKER in stored[thread].replies[0].body
    assert stored[other].replies == ()


def test_a_reply_to_a_reply_lands_in_the_same_thread(rig: Rig) -> None:
    thread = rig.thread()
    rig.store.reply(UNIT, thread, "and this?")
    reply_id = next(i for i in rig.listed().conversation if i != thread and i.startswith("ui-"))

    write_back_replies(rig.store, UNIT, [pr_replies.Reply(comment_id=reply_id, body="Done")])

    replies = rig.store.read(UNIT).threads[0].replies
    assert len(replies) == 2 and "Done" in replies[1].body


def test_the_agents_replies_are_not_read_back_as_new_comments(rig: Rig) -> None:
    thread = rig.thread()
    rig.poll()
    written = write_back_replies(
        rig.store, UNIT, [pr_replies.Reply(comment_id=thread, body="Renamed it")]
    )

    assert rig.poll() == []
    assert not set(written) & set(rig.listed().conversation)
    assert "Renamed it" not in " ".join(rig.listed().comment_bodies)


def test_a_reviewers_reply_after_the_agents_is_a_new_comment(rig: Rig) -> None:
    thread = rig.thread()
    write_back_replies(rig.store, UNIT, [pr_replies.Reply(comment_id=thread, body="Renamed it")])
    rig.poll()
    rig.store.reply(UNIT, thread, "still wrong")

    assert kinds(rig.poll()) == [("rework", ReworkKind.COMMENT)]


def test_approve_records_the_approval_and_merges_nothing(rig: Rig) -> None:
    rig.poll()
    rig.store.decide(UNIT, round=1, decision="approve", summary="looks good")

    events = rig.poll()
    listed = rig.listed()

    assert events == []
    assert listed.review_decision == "approved"
    assert listed.state == "open"


def test_a_host_request_for_changes_is_not_hidden_by_a_ui_approval(rig: Rig) -> None:
    rig.store.decide(UNIT, round=1, decision="approve", summary="")
    rig.pull = rig.pull.model_copy(update={"review_decision": "changes_requested"})

    assert rig.listed().review_decision == "changes_requested"


def test_a_host_request_for_changes_after_a_ui_approval_is_one_rework(rig: Rig) -> None:
    rig.store.decide(UNIT, round=1, decision="approve", summary="")
    rig.poll()
    rig.pull = rig.pull.model_copy(update={"review_decision": "changes_requested"})

    assert kinds(rig.poll()) == [("rework", ReworkKind.CHANGES_REQUESTED)]
