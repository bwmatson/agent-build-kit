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

import io
import json
import subprocess
import urllib.error
import urllib.parse
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


class AzureLabelsHost:
    """The pull request labels endpoints, answering at the wire.

    `open_url` stands in for `urlopen`: it receives the request `az.rest`
    builds and answers with the raw JSON the service sends. What it keeps of
    the real service: a label is `{id, name, active}`, unique case-insensitively
    (adding `In-Review` to a pull request carrying `in-review` answers with the
    one it has), and removed by id; a name containing `:` in the path is
    refused by the host's path check. The single pull request document does not
    carry labels, as the host's does not.
    """

    def __init__(self, labels: dict[int, list[str]] | None = None, *, refuse: str = "") -> None:
        self.refuse = refuse
        self._labels: dict[int, list[dict]] = {}
        self._next = 0
        for number, names in (labels or {}).items():
            self._labels[number] = [self._made(name) for name in names]
        self.requests: list[tuple[str, str]] = []

    def names(self, number: int) -> list[str]:
        return [label["name"] for label in self._labels.get(number, [])]

    def writes(self) -> list[tuple[str, str]]:
        """Every request that changed something."""
        return [(method, path) for method, path in self.requests if method != "GET"]

    def open_url(self, request, timeout=None) -> _Response:
        method = request.get_method()
        path = urllib.parse.unquote(urllib.parse.urlsplit(request.full_url).path)
        self.requests.append((method, path))
        _, _, tail = path.partition("/pullRequests/")
        number, _, rest = tail.partition("/")
        pull = int(number)
        labels = self._labels.setdefault(pull, [])
        if rest == "":
            return _Response({"pullRequestId": pull, "status": "active"})
        if method == "GET" and rest == "labels":
            return _Response({"count": len(labels), "value": list(labels)})
        if method != "GET" and self.refuse:
            raise _refused(request, 403, "Forbidden", self.refuse)
        if method == "POST" and rest == "labels":
            name = json.loads(request.data.decode())["name"]
            held = next((x for x in labels if x["name"].casefold() == name.casefold()), None)
            if held is None:
                held = self._made(name)
                labels.append(held)
            return _Response(held)
        if method == "DELETE" and rest.startswith("labels/"):
            key = rest.removeprefix("labels/")
            by_id = next((x for x in labels if x["id"] == key), None)
            by_name = next((x for x in labels if x["name"].casefold() == key.casefold()), None)
            if by_id is None and by_name is not None and ":" in key:
                raise _refused(request, 400, "Bad Request", "The label name is not valid")
            gone = by_id or by_name
            if gone is None:
                raise _refused(request, 404, "Not Found", "The label does not exist")
            labels.remove(gone)
            return _Response(None)
        raise AssertionError(f"the stand-in host was not expecting {method} {path}")

    def _made(self, name: str) -> dict:
        self._next += 1
        return {"id": f"00000000-0000-0000-0000-{self._next:012d}", "name": name, "active": True}


class _Response:
    def __init__(self, body: object) -> None:
        self.text = "" if body is None else json.dumps(body)

    def read(self) -> bytes:
        return self.text.encode()

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc) -> None:
        return None


def _refused(request, code: int, reason: str, message: str) -> urllib.error.HTTPError:
    body = io.BytesIO(json.dumps({"message": message}).encode())
    return urllib.error.HTTPError(request.full_url, code, reason, {}, body)  # type: ignore[arg-type]


def _ok(args: list[str], payload: object) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")


def _flag(args: list[str], name: str) -> str:
    return args[args.index(name) + 1] if name in args else ""


def _route(args: list[str], name: str) -> str:
    prefix = f"{name}="
    return next((item.removeprefix(prefix) for item in args if item.startswith(prefix)), "")


def _body(args: list[str]) -> dict:
    return json.loads(Path(_flag(args, "--in-file")).read_text())
