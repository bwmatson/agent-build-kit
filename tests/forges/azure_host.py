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
        if args[1:4] == ["pipelines", "runs", "show"]:
            # The build behind a policy evaluation; these tests' builds failed.
            return _ok(args, {"id": int(_flag(args, "--id") or 0), "result": "failed"})
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


class AzureLabelsHost:
    """The pull request labels resource, answering `az devops invoke` at the wire.

    It is the runner: it receives the argv the forge builds and the body file
    it writes, and answers with the raw JSON the service sends. What it keeps of
    the real service: a label is `{id, name, active}`, unique case-insensitively
    (adding `In-Review` to a pull request carrying `in-review` answers with the
    one it has), and removed by name; removing one the pull request does not
    carry exits non-zero with "could not be found". The single pull request
    document does not carry labels, as the host's does not.
    """

    def __init__(self, labels: dict[int, list[str]] | None = None, *, refuse: str = "") -> None:
        self.refuse = refuse
        self._labels: dict[int, list[dict]] = {}
        self._next = 0
        for number, names in (labels or {}).items():
            self._labels[number] = [self._made(name) for name in names]
        self.calls: list[list[str]] = []

    def names(self, number: int) -> list[str]:
        return [label["name"] for label in self._labels.get(number, [])]

    def writes(self) -> list[list[str]]:
        """Every call that changed something."""
        return [call for call in self.calls if _flag(call, "--http-method") != "get"]

    def __call__(self, args: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(args)
        if args[1:3] != ["devops", "invoke"] or "pullRequestLabels" not in args:
            raise AssertionError(f"the stand-in host was not expecting {' '.join(args)}")
        method = _flag(args, "--http-method")
        labels = self._labels.setdefault(int(_route(args, "pullRequestId")), [])
        if method == "get":
            return _ok(args, {"count": len(labels), "value": list(labels)})
        if self.refuse:
            return subprocess.CompletedProcess(args, 1, "", self.refuse)
        if method == "post":
            name = _body(args)["name"]
            held = _find(labels, name)
            if held is None:
                held = self._made(name)
                labels.append(held)
            return _ok(args, held)
        if method == "delete":
            gone = _find(labels, _route(args, "labelIdOrName"))
            if gone is None:
                return subprocess.CompletedProcess(
                    args, 1, "", "TF401088: The label could not be found."
                )
            labels.remove(gone)
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(f"the stand-in host was not expecting {' '.join(args)}")

    def _made(self, name: str) -> dict:
        self._next += 1
        return {"id": f"00000000-0000-0000-0000-{self._next:012d}", "name": name, "active": True}


def _find(labels: list[dict], name: str) -> dict | None:
    return next((x for x in labels if x["name"].casefold() == name.casefold()), None)


def _ok(args: list[str], payload: object) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")


def _flag(args: list[str], name: str) -> str:
    return args[args.index(name) + 1] if name in args else ""


def _route(args: list[str], name: str) -> str:
    prefix = f"{name}="
    return next((item.removeprefix(prefix) for item in args if item.startswith(prefix)), "")


def _body(args: list[str]) -> dict:
    return json.loads(Path(_flag(args, "--in-file")).read_text())
