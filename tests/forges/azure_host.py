"""Azure DevOps as the `az` CLI sees it: a stand-in answering at the wire.

What it receives is the argv the forge builds and the JSON body it writes to
`--in-file`; what it sends back is the raw document the real service sends,
from `azure_answers`. It does the two things the real service does that a
canned answer cannot: it honours `--status` and `--source-branch` on a pull
request listing, and it keeps every pull request status posted, each with an
id of its own, as the service does: superseding is the reader's to do.

A call it does not know fails the test rather than answering emptily: a forge
reaching for a resource nobody expected is the thing under test.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.forges import azure_answers


class AzureHost:
    def __init__(
        self,
        *pulls: dict,
        policies: dict[int, list[dict]] | None = None,
        refuse_pr_status: str = "",
    ) -> None:
        self.pulls = list(pulls)
        self.policies = policies or {}
        self.refuse_pr_status = refuse_pr_status
        self.calls: list[list[str]] = []
        self.commit_statuses: list[dict] = []
        # Per pull request, every status posted: the listing returns them all.
        self._pr_statuses: dict[int, list[dict]] = {}
        self.pr_status_posts: list[tuple[int, dict]] = []

    def __call__(self, args: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(args)
        if "pullRequestStatuses" in args:
            return self._pr_statuses_call(args)
        if "statuses" in args:
            self.commit_statuses.append({"commit": _route(args, "commitId"), **_body(args)})
            return _ok(args, {"id": 1})
        if "pullRequestThreads" in args:
            return _ok(args, azure_answers.threads())
        if "policy" in args and "pr" in args:
            return _ok(args, self.policies.get(int(_flag(args, "--id") or 0), []))
        if args[1:4] == ["repos", "pr", "list"]:
            return _ok(args, self._listing(args))
        raise AssertionError(f"the stand-in host was not expecting {' '.join(args)}")

    def asked(self, word: str) -> list[list[str]]:
        """Every call whose argv holds this word."""
        return [call for call in self.calls if word in call]

    def _listing(self, args: list[str]) -> list[dict]:
        status = _flag(args, "--status") or "active"
        branch = _flag(args, "--source-branch")
        return [
            pull
            for pull in self.pulls
            if (status == "all" or pull["status"] == status)
            and (not branch or pull["sourceRefName"].removeprefix("refs/heads/") == branch)
        ]

    def _pr_statuses_call(self, args: list[str]) -> subprocess.CompletedProcess:
        number = int(_route(args, "pullRequestId"))
        if "POST" not in args:
            return _ok(args, {"value": list(self._pr_statuses.get(number, []))})
        if self.refuse_pr_status:
            return subprocess.CompletedProcess(args, 1, "", self.refuse_pr_status)
        body = _body(args)
        stored = {**body, "id": len(self.pr_status_posts) + 1}
        self._pr_statuses.setdefault(number, []).append(stored)
        self.pr_status_posts.append((number, body))
        return _ok(args, stored)


def _ok(args: list[str], payload: object) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")


def _flag(args: list[str], name: str) -> str:
    return args[args.index(name) + 1] if name in args else ""


def _route(args: list[str], name: str) -> str:
    prefix = f"{name}="
    return next((item.removeprefix(prefix) for item in args if item.startswith(prefix)), "")


def _body(args: list[str]) -> dict:
    return json.loads(Path(_flag(args, "--in-file")).read_text())
