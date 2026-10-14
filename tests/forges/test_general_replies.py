"""A reply to a general note goes in the note's thread where the host has threads, and quotes
the note where it does not."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.forges import ReviewNote
from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.pipeline.pr_replies import build_post_replies
from tests.forges.stand_in import StandInForge, lookup

NOTE = ReviewNote(
    id="660.1",
    body="Please make one_pass the default, and say in the readme why the old default was kept",
)
ANSWER = json.dumps({"replies": [{"comment_id": "660.1", "body": "Done."}], "summary": ""})


class Threaded(StandInForge):
    general_threads = True


def post(tmp_path: Path, forge: StandInForge) -> None:
    build_post_replies(root=tmp_path, for_repo=lookup(forge), log=lambda line: None)(
        repo="platform", pr=17, answer_text=ANSWER, sha="0123456789abcdef"
    )


def test_a_reply_to_a_general_note_is_added_to_its_thread_where_the_host_has_threads(
    tmp_path: Path,
) -> None:
    assert AzureDevOpsForge.general_threads is True, "Azure DevOps has a thread per comment"
    assert GitHubForge.general_threads is False
    forge = Threaded(notes=[NOTE])

    post(tmp_path, forge)

    assert [note for note, _ in forge.replies] == ["660.1"]
    assert forge.comments == []


def test_a_reply_to_a_general_note_quotes_it_where_the_host_has_no_threads(
    tmp_path: Path,
) -> None:
    forge = StandInForge(notes=[NOTE])

    post(tmp_path, forge)

    assert forge.replies == []
    [comment] = forge.comments
    assert comment.startswith(f"Re: {NOTE.body[:60]}")
    assert "Done." in comment
