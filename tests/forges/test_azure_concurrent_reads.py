"""A poll reads each open PR's conversation and checks on a bounded pool."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from copy import deepcopy

import pytest

from agent_build_kit.config import AzureDevOpsConfig, RepoConfig
from agent_build_kit.forges.azure_devops import FORGE, READ_POOL
from agent_build_kit.pipeline.az import AzError
from tests.forges import azure_answers

REPO = FORGE.identity(
    RepoConfig(
        path=".",
        forge="azure_devops",
        azure_devops=AzureDevOpsConfig(org="acme", project="Proj", repo="app"),
    )
)


def open_prs(count: int) -> list[dict]:
    return [
        {
            **deepcopy(azure_answers.OPEN),
            "pullRequestId": 100 + n,
            "sourceRefName": f"refs/heads/spec/add-marker/{n}",
        }
        for n in range(count)
    ]


def _thread_of(pr: int) -> dict:
    """A conversation only this PR has: its number is in the thread and the note."""
    note = {**azure_answers.REVIEW_THREAD["comments"][0], "content": f"note on {pr}"}
    return azure_answers.thread(id=pr, comments=[note])


def _failed_status_of(pr: int) -> dict:
    """A failing check named after this PR."""
    return {**azure_answers.FAILED_STATUS, "context": {"genre": "ci", "name": f"build-{pr}"}}


class Az:
    """An `az` double: a listing, then a thread and a status read per open PR.

    Records how many reads were in flight together, and can make one fail.
    """

    def __init__(self, listing: list[dict], *, fail_on: int | None = None, pause: float = 0.0):
        self.listing = listing
        self.fail_on = fail_on
        self.pause = pause
        self.lock = threading.Lock()
        self.in_flight = 0
        self.peak = 0

    def __call__(self, args, **kwargs):
        if "list" in args:
            return subprocess.CompletedProcess(args, 0, json.dumps(self.listing), "")
        pr = next(int(a.split("=")[1]) for a in args if a.startswith("pullRequestId="))
        with self.lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
        try:
            time.sleep(self.pause)
            if pr == self.fail_on:
                return subprocess.CompletedProcess(args, 1, "", "TF400898: boom")
            if "pullRequestThreads" in args:
                body = azure_answers.threads(_thread_of(pr))
            else:
                body = {"value": [_failed_status_of(pr)]}
            return subprocess.CompletedProcess(args, 0, json.dumps(body), "")
        finally:
            with self.lock:
                self.in_flight -= 1


def test_five_open_prs_list_as_they_would_one_at_a_time() -> None:
    listing = open_prs(5)

    found = FORGE.list_prs(REPO, run=Az(listing, pause=0.01))

    # Each PR read on its own is the serial result: one call chain, one thread.
    serial = [FORGE.list_prs(REPO, run=Az([pull]))[0] for pull in listing]
    assert [p.number for p in found] == [100, 101, 102, 103, 104], "in listing order"
    assert found == serial
    for pull in found:
        assert pull.comment_bodies == (f"note on {pull.number}",), "another PR's conversation"
        assert [str(pull.number) in note for note in pull.conversation] == [True]
        assert all(str(pull.number) in check for check in pull.failing_checks)
        assert len(pull.failing_checks) == 1, "another PR's checks"


def test_the_per_pr_reads_overlap() -> None:
    az = Az(open_prs(5), pause=0.05)

    FORGE.list_prs(REPO, run=az)

    assert az.peak > 1, "the reads ran one after another"


def test_twenty_open_prs_never_exceed_the_pool() -> None:
    az = Az(open_prs(20), pause=0.02)

    found = FORGE.list_prs(REPO, run=az)

    assert len(found) == 20
    assert 1 < az.peak <= READ_POOL


def test_one_failed_read_fails_the_poll_with_no_partial_list() -> None:
    az = Az(open_prs(6), fail_on=103, pause=0.01)

    with pytest.raises(AzError):
        FORGE.list_prs(REPO, run=az)
