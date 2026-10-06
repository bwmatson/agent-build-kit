"""The GitHub forge's draft toggle, as the `gh` argv it sends.

The fake sits at the process boundary, so whichever shell helper the forge
reads and writes through is exercised. It answers a pull request's draft state
the way `gh pr view --json isDraft` and `gh pr list` print it, and keeps every
call.
"""

import json
import subprocess

import pytest

from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import FORGE

REPO = RepoId(forge="github", account="example", name="app")

PULL = {
    "number": 7,
    "headRefName": "spec/feature/1",
    "baseRefName": "main",
    "state": "OPEN",
    "mergedAt": None,
    "labels": [],
    "comments": [],
    "statusCheckRollup": [],
    "reviewDecision": "",
    "mergeable": "MERGEABLE",
}


class Host:
    """A repo whose pull request 7 is a draft or is not."""

    def __init__(self, *, draft: bool, refusal: str = "") -> None:
        self.draft = draft
        self.refusal = refusal
        self.commands: list[list[str]] = []

    def __call__(self, args: list[str], **_) -> subprocess.CompletedProcess:
        if args[:3] == ["gh", "auth", "token"]:
            return subprocess.CompletedProcess(args, 1, "", "")
        self.commands.append(args)
        if args[:3] == ["gh", "pr", "ready"]:
            if self.refusal:
                return subprocess.CompletedProcess(args, 1, "", self.refusal)
            self.draft = "--undo" in args
            return subprocess.CompletedProcess(args, 0, "", "")
        pull = {**PULL, "isDraft": self.draft}
        answer = [pull] if args[:3] == ["gh", "pr", "list"] else pull
        return subprocess.CompletedProcess(args, 0, json.dumps(answer), "")

    def writes(self) -> list[list[str]]:
        return [c for c in self.commands if c[:3] == ["gh", "pr", "ready"]]


def host(monkeypatch: pytest.MonkeyPatch, **kwargs) -> Host:
    fake = Host(**kwargs)
    monkeypatch.setattr("agent_build_kit.pipeline.shell.subprocess.run", fake)
    return fake


def test_a_ready_pull_request_is_made_a_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = host(monkeypatch, draft=False)

    FORGE.set_draft(REPO, 7, True)

    assert fake.writes() == [["gh", "pr", "ready", "7", "--repo", "example/app", "--undo"]]


def test_a_draft_is_published(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = host(monkeypatch, draft=True)

    FORGE.set_draft(REPO, 7, False)

    assert fake.writes() == [["gh", "pr", "ready", "7", "--repo", "example/app"]]


def test_made_a_draft_and_then_published_sends_both_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = host(monkeypatch, draft=False)

    FORGE.set_draft(REPO, 7, True)
    FORGE.set_draft(REPO, 7, False)

    assert fake.writes() == [
        ["gh", "pr", "ready", "7", "--repo", "example/app", "--undo"],
        ["gh", "pr", "ready", "7", "--repo", "example/app"],
    ]


@pytest.mark.parametrize("draft", [True, False])
def test_a_pull_request_already_in_the_asked_for_state_is_not_written_to(
    monkeypatch: pytest.MonkeyPatch, draft: bool
) -> None:
    fake = host(monkeypatch, draft=draft)

    FORGE.set_draft(REPO, 7, draft)

    assert fake.writes() == []
    assert fake.commands, "the current state is read before deciding"


def test_a_refusal_raises_with_the_hosts_message(monkeypatch: pytest.MonkeyPatch) -> None:
    host(
        monkeypatch, draft=False, refusal="Draft pull requests are not supported in this repository"
    )

    with pytest.raises(RuntimeError, match="Draft pull requests are not supported"):
        FORGE.set_draft(REPO, 7, True)
