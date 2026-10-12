"""What a forge writes to a code host holds the replacement for a known secret value
(titles, bodies, comments, statuses), and a redaction that fails withholds the text.

Each forge is checked at its own boundary: the request the host receives, or for the
local forge what it keeps.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.local import LocalForge
from agent_build_kit.pipeline.pr_body import build_pr_body
from agent_build_kit.pipeline.tier2 import Tier2Result, build_snapshot
from tests.factories import stored_unit
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost
from tests.forges.github_host import GitHubHost, answer
from tests.redaction_fakes import FAILURE_MESSAGE, NAME, NOTICE, SECRET, known

REPLACED = f"[redacted:{NAME}]"
GITHUB = RepoId(forge="github", account="example", name="app")
AZURE = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
LOCAL = RepoId(forge="local", account="local", name="app")
BASE = "/repos/example/app"
HEAD = "spec/add-marker/1"
SAID = f"the run printed {SECRET} in its output"
SAID_REPLACED = f"the run printed {REPLACED} in its output"


def _failing_tier_two_body() -> str:
    snapshot = build_snapshot(
        Tier2Result(
            sha="abcdef1234567",
            passed=0,
            failed=1,
            skipped=0,
            duration_seconds=1.5,
            command="uv run pytest -m local_stack",
            output=f"FAILED tests/live/test_it.py - Scratch(env={SECRET})",
        )
    )
    return build_pr_body(
        stored_unit(tier="tier2"), graph=[stored_unit()], base="main", tier2_snapshot=snapshot
    )


def _one_failure_line(caplog: pytest.LogCaptureFixture) -> None:
    lines = [
        r
        for r in caplog.records
        if r.name == "agent_build_kit.redaction" and r.levelno >= logging.WARNING
    ]
    assert len(lines) == 1, [r.getMessage() for r in caplog.records]
    shown = lines[0].getMessage()
    assert "RuntimeError" in shown
    assert SECRET not in shown
    assert FAILURE_MESSAGE not in shown


@pytest.mark.usefixtures("github_env")
class TestGitHub:
    def test_a_pull_request_description_from_a_failing_tier_two_holds_the_replacement(
        self,
    ) -> None:
        created = answer(
            {"number": 7, "node_id": "PR_7", "state": "open", "head": {"ref": HEAD}}, 201
        )
        host = GitHubHost(routes={("POST", f"{BASE}/pulls"): created})
        body = _failing_tier_two_body()
        assert SECRET in body

        with known():
            GitHubForge(http=host).create_pr(
                GITHUB, head=HEAD, base="main", title=f"Fix {SECRET}", body=body
            )

        [call] = host.calls("POST", f"{BASE}/pulls")
        assert SECRET not in str(call.body)
        assert call.body["title"] == f"Fix {REPLACED}"
        assert f"Scratch(env={REPLACED})" in call.body["body"]

    def test_an_updated_description_holds_the_replacement(self) -> None:
        host = GitHubHost(routes={("PATCH", f"{BASE}/pulls/7"): answer({"number": 7})})

        with known():
            GitHubForge(http=host).update_pr(GITHUB, 7, body=SAID)

        [call] = host.calls("PATCH", f"{BASE}/pulls/7")
        assert call.body == {"body": SAID_REPLACED}

    def test_a_posted_comment_holds_the_replacement(self) -> None:
        route = ("POST", f"{BASE}/issues/17/comments")
        host = GitHubHost(routes={route: answer({"id": 5, "node_id": "IC_5", "body": ""}, 201)})

        with known():
            GitHubForge(http=host).post_comment(GITHUB, 17, body=SAID)

        [call] = host.calls(*route)
        assert call.body == {"body": SAID_REPLACED}

    def test_a_posted_status_holds_the_replacement_and_is_still_the_counts(self) -> None:
        route = ("POST", f"{BASE}/statuses/abc1234def")
        host = GitHubHost(routes={route: answer({"id": 1, "state": "failure"}, 201)})
        counts = "0 passed, 1 failed in 1.5s"

        with known():
            forge = GitHubForge(http=host)
            forge.post_status(
                GITHUB, sha="abc1234def", ok=False, context="local/tier2", description=counts
            )
            forge.post_status(
                GITHUB, sha="abc1234def", ok=False, context="local/tier2", description=SAID
            )

        counted, said = host.calls(*route)
        assert counted.body["description"] == counts
        assert said.body["description"] == SAID_REPLACED

    def test_a_failed_redaction_withholds_the_posted_body(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        route = ("POST", f"{BASE}/issues/17/comments")
        host = GitHubHost(routes={route: answer({"id": 5, "node_id": "IC_5", "body": ""}, 201)})

        with known(broken=True):
            GitHubForge(http=host).post_comment(GITHUB, 17, body=SAID)

        [call] = host.calls(*route)
        assert call.body == {"body": NOTICE}
        _one_failure_line(caplog)


@pytest.mark.usefixtures("rest_env")
class TestAzureDevOps:
    def test_a_created_pull_request_holds_the_replacement(self) -> None:
        host = RestHost()

        with known():
            AzureDevOpsForge(http=host).create_pr(
                AZURE, head=HEAD, base="main", title=f"Fix {SECRET}", body=_failing_tier_two_body()
            )

        [call] = host.writes()
        assert SECRET not in str(call.body)
        assert call.body["title"] == f"Fix {REPLACED}"
        assert f"Scratch(env={REPLACED})" in call.body["description"]

    def test_a_comment_and_a_reply_hold_the_replacement(self) -> None:
        host = RestHost(azure_answers.OPEN)

        with known():
            forge = AzureDevOpsForge(http=host)
            forge.post_comment(AZURE, 162, body=SAID)
            forge.post_reply(AZURE, 162, note_id="478.1", body=SAID)

        written = "\n".join(str(call.body) for call in host.writes())
        assert SECRET not in written
        assert written.count(SAID_REPLACED) == 2

    def test_a_status_description_holds_the_replacement(self) -> None:
        host = RestHost(azure_answers.OPEN)

        with known():
            AzureDevOpsForge(http=host).post_status(
                AZURE, sha="abc123", ok=False, context="local/tier2", description=SAID, head=HEAD
            )

        written = "\n".join(str(call.body) for call in host.writes())
        assert SAID_REPLACED in written
        assert SECRET not in written

    def test_a_failed_redaction_withholds_the_posted_body(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        host = RestHost(azure_answers.OPEN)

        with known(broken=True):
            AzureDevOpsForge(http=host).post_comment(AZURE, 162, body=SAID)

        [call] = host.writes()
        assert call.body["comments"][0]["content"] == NOTICE
        _one_failure_line(caplog)


class TestLocal:
    def test_what_the_forge_keeps_holds_the_replacement(self, tmp_path: Path) -> None:
        forge = LocalForge(tmp_path)

        with known():
            number = forge.create_pr(
                LOCAL, head=HEAD, base="main", title=f"Fix {SECRET}", body=_failing_tier_two_body()
            )
            forge.post_comment(LOCAL, number, body=SAID)
            forge.update_pr(LOCAL, number, body=SAID)

        kept = forge.record(LOCAL, number)
        assert kept is not None
        assert SECRET not in str(kept)
        assert kept["title"] == f"Fix {REPLACED}"
        assert kept["body"] == SAID_REPLACED

    def test_a_failed_redaction_withholds_the_kept_comment(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        forge = LocalForge(tmp_path)
        number = forge.create_pr(LOCAL, head=HEAD, base="main", title="Fix", body="Body")

        with known(broken=True):
            forge.post_comment(LOCAL, number, body=SAID)

        kept = forge.record(LOCAL, number)
        assert kept is not None
        assert [c["body"] for c in cast(list[dict[str, Any]], kept["comments"])] == [NOTICE]
        _one_failure_line(caplog)
