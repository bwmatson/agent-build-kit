"""A fake GitHub host a process can reach over HTTP, for tests that run `abk` as
a subprocess and point `ABK_GITHUB_API_URL` at it.

It answers the REST and GraphQL routes the forge calls from the recorded answers
in `github_answers.py` and `github_host.py`, keeps its state in memory, and lets
the test change that state the way a reviewer would on the host.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Any

import httpx

from tests.forges import github_answers
from tests.forges.github_host import GitHubHost, answer, refusal
from tests.forges.mock_host import recorded

_PULLS = re.compile(r"/repos/(?P<owner>[^/]+)/[^/]+/pulls")
_PULL_LISTS = re.compile(r"/repos/[^/]+/[^/]+/pulls/(?P<n>\d+)/(?P<what>reviews|comments)")
_MERGED_AT = "2026-10-01T12:00:00Z"
_DECIDING = ("APPROVED", "CHANGES_REQUESTED")


class _Pull:
    """What the forge and the test have done to one pull request."""

    def __init__(self, number: int, head: str, base: str, title: str, body: str) -> None:
        self.number = number
        self.head = head
        self.base = base
        self.title = title
        self.body = body
        self.merged = False
        self.comments: list[tuple[str, str]] = []
        self.reviews: list[tuple[str, str, str]] = []

    def decision(self) -> str | None:
        decided = [state for _, state, _ in self.reviews if state in _DECIDING]
        return decided[-1] if decided else None


class FakeGitHub:
    # What the server requires in `Authorization`; the test makes the stand-in
    # `gh auth token` print the same.
    token: str
    # `http://127.0.0.1:<port>`, once started.
    url: str

    def __init__(self, token: str = "fake-github-token", *, first_number: int = 1) -> None:
        self.token = token
        self.url = ""
        self._next = first_number
        self._ids = 0
        self._host = GitHubHost()
        self._pulls: dict[int, _Pull] = {}
        self._requests: list[tuple[str, str]] = []
        self._unrouted: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> FakeGitHub:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                pass

            def handle_any(self) -> None:
                length = int(self.headers.get("content-length") or 0)
                content = self.rfile.read(length) if length else b""
                headers = {k: v for k, v in self.headers.items() if k.lower() != "host"}
                request = httpx.Request(
                    self.command, f"{fake.url}{self.path}", headers=headers, content=content
                )
                reply = fake.respond(request)
                self.send_response(reply.status_code)
                for name, value in reply.headers.items():
                    if name.lower() not in ("content-length", "transfer-encoding"):
                        self.send_header(name, value)
                self.send_header("content-length", str(len(reply.content)))
                self.end_headers()
                self.wfile.write(reply.content)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = handle_any  # noqa: N815

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join()

    def add_comment(self, number: int, body: str) -> None:
        """A conversation comment on the pull request, as a person leaves one."""
        with self._lock:
            self._ids += 1
            self._pulls[number].comments.append((f"IC_kwDOAAAAAc{self._ids:08d}", body))

    def add_review(self, number: int, state: str, body: str) -> None:
        """A submitted review (`APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`)."""
        with self._lock:
            self._ids += 1
            self._pulls[number].reviews.append((f"PRR_kwDOAAAAAc{self._ids:08d}", state, body))

    def merge(self, number: int) -> None:
        with self._lock:
            self._pulls[number].merged = True

    def requests(self, method: str | None = None, path: str | None = None) -> list[tuple[str, str]]:
        """Every `(method, path)` that reached the server carrying the token."""
        with self._lock:
            return [
                r
                for r in self._requests
                if (method is None or r[0] == method) and (path is None or r[1] == path)
            ]

    def unrouted(self) -> list[tuple[str, str]]:
        """Every `(method, path)` the server had no route for."""
        with self._lock:
            return list(self._unrouted)

    # --- answering ------------------------------------------------------------------

    def respond(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") not in (
            f"Bearer {self.token}",
            f"token {self.token}",
        ):
            return recorded("bad_credentials_401")
        key = (request.method, request.url.path)
        with self._lock:
            self._requests.append(key)
            reply = self._rest(request)
            if reply is not None:
                return reply
            self._sync()
            missed = len(self._host.unrouted)
            reply = self._host.handle_request(request)
            if len(self._host.unrouted) > missed:
                self._unrouted.append(key)
                return refusal(404, f"No route for {key[0]} {key[1]}")
            return reply

    def _sync(self) -> None:
        """Write what the test has done into the nodes the host answers from."""
        for number, pull in self._pulls.items():
            node = self._host.pull(number)
            fresh = github_answers.pull(
                number,
                head=pull.head,
                base=pull.base,
                state="MERGED" if pull.merged else "OPEN",
                draft=node["isDraft"],
                merged_at=_MERGED_AT if pull.merged else None,
                review_decision=pull.decision(),
                labels=tuple(self._host.pr_labels.get(number, ())),
                comments=tuple(pull.comments),
                reviews=tuple(pull.reviews),
            )
            fresh["title"] = pull.title
            node.update(fresh)

    def _document(self, pull: _Pull) -> dict[str, Any]:
        node = self._host.pull(pull.number)
        return {
            "number": pull.number,
            "node_id": node["id"],
            "state": "closed" if pull.merged else "open",
            "draft": node["isDraft"],
            "title": pull.title,
            "body": pull.body,
            "merged": pull.merged,
            "head": {"ref": pull.head, "label": f"{github_answers.OWNER}:{pull.head}"},
            "base": {"ref": pull.base},
            "html_url": node["url"],
        }

    def _rest(self, request: httpx.Request) -> httpx.Response | None:
        path = request.url.path
        found = _PULLS.fullmatch(path)
        if found and request.method == "POST":
            return self._create(found["owner"], json.loads(request.content or b"{}"))
        if found and request.method == "GET":
            wanted = request.url.params.get("head", "").split(":", 1)[-1]
            return answer(
                [self._document(p) for p in self._pulls.values() if not wanted or p.head == wanted]
            )
        listed = _PULL_LISTS.fullmatch(path)
        if listed and request.method == "GET":
            pull = self._pulls.get(int(listed["n"]))
            if pull is None:
                return refusal(404, "Not Found")
            if listed["what"] == "comments":
                return answer([])
            return answer(
                [
                    {"id": 1000 + i, "node_id": node, "body": body, "state": state}
                    for i, (node, state, body) in enumerate(pull.reviews)
                ]
            )
        return None

    def _create(self, owner: str, body: dict[str, Any]) -> httpx.Response:
        head = str(body.get("head", ""))
        if any(p.head == head and not p.merged for p in self._pulls.values()):
            problem = {
                "resource": "PullRequest",
                "code": "custom",
                "message": f"A pull request already exists for {owner}:{head}.",
            }
            return refusal(422, "Validation Failed", [problem])
        number = self._next
        self._next += 1
        base = str(body.get("base", "main"))
        pull = _Pull(number, head, base, str(body.get("title", "")), str(body.get("body", "")))
        self._pulls[number] = pull
        self._host.pulls.append(github_answers.pull(number, head=head, base=base))
        self._sync()
        return answer(self._document(pull), 201)
