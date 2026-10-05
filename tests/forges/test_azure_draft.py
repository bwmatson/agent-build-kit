"""The Azure DevOps forge's draft toggle, as the `az` argv it sends.

Mirrors `test_github_draft.py`. The runner is a stand-in at the process
boundary: it answers a pull request document with the `isDraft` it holds, and
changes it when `az repos pr update --draft` arrives.
"""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy

import pytest

from agent_build_kit import forges
from agent_build_kit.forges.azure_devops import FORGE
from agent_build_kit.forges.base import RepoId
from agent_build_kit.pipeline.az import AzError
from tests.forges import azure_answers

REPO = RepoId(forge="azure_devops", account="example", project="Proj", name="app")
ORG = "https://dev.azure.com/example"


class Host:
    def __init__(self, *, draft: bool, refusal: str = "") -> None:
        self.draft = draft
        self.refusal = refusal
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **_) -> subprocess.CompletedProcess:
        self.calls.append(args)
        if args[:4] == ["az", "repos", "pr", "update"]:
            if self.refusal:
                return subprocess.CompletedProcess(args, 1, "", self.refusal)
            self.draft = args[args.index("--draft") + 1] == "true"
        document = {**deepcopy(azure_answers.OPEN), "pullRequestId": 7, "isDraft": self.draft}
        answer = [document] if args[:4] == ["az", "repos", "pr", "list"] else document
        return subprocess.CompletedProcess(args, 0, json.dumps(answer), "")

    def writes(self) -> list[list[str]]:
        return [c for c in self.calls if c[:4] == ["az", "repos", "pr", "update"]]


def test_a_ready_pull_request_is_made_a_draft() -> None:
    host = Host(draft=False)

    FORGE.set_draft(REPO, 7, True, run=host)

    [write] = host.writes()
    assert write[write.index("--id") + 1] == "7"
    assert write[write.index("--draft") + 1] == "true"
    assert write[write.index("--org") + 1] == ORG


def test_a_draft_is_published() -> None:
    host = Host(draft=True)

    FORGE.set_draft(REPO, 7, False, run=host)

    [write] = host.writes()
    assert write[write.index("--draft") + 1] == "false"
    assert write[write.index("--org") + 1] == ORG


def test_made_a_draft_and_then_published_sends_both_in_order() -> None:
    host = Host(draft=False)

    FORGE.set_draft(REPO, 7, True, run=host)
    FORGE.set_draft(REPO, 7, False, run=host)

    assert [w[w.index("--draft") + 1] for w in host.writes()] == ["true", "false"]


@pytest.mark.parametrize("draft", [True, False])
def test_a_pull_request_already_in_the_asked_for_state_is_not_written_to(draft: bool) -> None:
    host = Host(draft=draft)

    FORGE.set_draft(REPO, 7, draft, run=host)

    assert host.writes() == []
    assert host.calls, "the current state is read before deciding"


def test_a_refusal_raises_with_the_hosts_message() -> None:
    host = Host(draft=False, refusal="TF401027: you need the pull request contribute permission")

    with pytest.raises(AzError, match="TF401027"):
        FORGE.set_draft(REPO, 7, True, run=host)


@pytest.mark.parametrize("draft", [True, False])
def test_the_argv_is_one_the_deny_list_accepts(draft: bool) -> None:
    """The pipeline's own argv and the exception list cannot drift apart: the
    command `set_draft` runs is one `forges.denies` lets through."""
    host = Host(draft=not draft)

    FORGE.set_draft(REPO, 7, draft, run=host)

    [argv] = host.writes()
    assert forges.denies(argv) == ""
