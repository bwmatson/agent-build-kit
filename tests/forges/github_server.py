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
from tests.forges.github_routes import GitHubState
from tests.forges.mock_host import recorded

_PULLS = re.compile(r"/repos/(?P<owner>[^/]+)/[^/]+/pulls")
_PULL_LISTS = re.compile(r"/repos/[^/]+/[^/]+/pulls/(?P<n>\d+)/(?P<what>reviews|comments|files)")
_REPLY = re.compile(r"/repos/[^/]+/[^/]+/pulls/(?P<n>\d+)/comments/(?P<note>\d+)/replies")
_REVIEW = re.compile(r"/repos/[^/]+/[^/]+/pulls/(?P<n>\d+)/reviews/(?P<review>\d+)")
_PULL_ONE = re.compile(r"/repos/[^/]+/[^/]+/pulls/(?P<n>\d+)")
_ISSUE_COMMENTS = re.compile(r"/repos/[^/]+/[^/]+/issues/(?P<n>\d+)/comments")
_STATUSES = re.compile(r"/repos/[^/]+/[^/]+/statuses/(?P<sha>[^/]+)")
_MERGED_AT = "2026-10-01T12:00:00Z"
_DECIDING = ("APPROVED", "CHANGES_REQUESTED")
_REVIEWER = {"login": "reviewer", "id": 4242, "type": "User", "site_admin": False}
_COMMIT = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
_WEB = "https://github.com/example/app/pull"


class _Pull:
    """What the forge and the test have done to one pull request."""

    def __init__(
        self, number: int, owner: str, head: str, base: str, title: str, body: str
    ) -> None:
        self.number = number
        self.owner = owner
        self.head = head
        self.base = base
        self.title = title
        self.body = body
        self.merged = False
        self.closed = False
        self.comments: list[tuple[str, str]] = []
        # As the REST API lists them: a review has its own numeric id, an inline
        # comment another, and a reply is an inline comment naming its parent.
        self.reviews: list[dict[str, Any]] = []
        self.inline: list[dict[str, Any]] = []

    def decision(self) -> str | None:
        decided = [r["state"] for r in self.reviews if r["state"] in _DECIDING]
        return decided[-1] if decided else None


class FakeGitHub:
    """The host standing in for one repository, such as `example/app`: pull
    requests are kept by number alone, whatever repository the path names."""

    # What the server requires in `Authorization`; the test makes the stand-in
    # `gh auth token` print the same.
    token: str
    # `http://127.0.0.1:<port>`, once started.
    url: str
    # The state the routes answer from; a host built over it answers the same.
    state: GitHubState

    def __init__(self, token: str = "fake-github-token", *, first_number: int = 1) -> None:
        self.token = token
        self.url = ""
        self._next = first_number
        self._ids = 0
        self._host = GitHubHost()
        self._pulls: dict[int, _Pull] = {}
        self._statuses: list[tuple[str, str, str]] = []
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

    def add_review(
        self,
        number: int,
        state: str,
        body: str,
        *,
        inline: tuple[str, int, str] | None = None,
    ) -> int | None:
        """A submitted review (`APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`),
        carrying an inline comment `(path, line, body)` when given. Returns the
        inline comment's id, which is what a reply must name."""
        with self._lock:
            pull = self._pulls[number]
            review = self._new_review(pull, state, body)
            if inline is None:
                return None
            path, line, text = inline
            return self._new_inline(pull, review, path=path, line=line, body=text)["id"]

    def review_comments(self, number: int) -> list[dict[str, Any]]:
        """Every inline comment on the pull request, replies included, as the
        pulls API lists them."""
        with self._lock:
            return [dict(c) for c in self._pulls[number].inline]

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

    def statuses(self) -> list[tuple[str, str, str]]:
        """Every commit status posted, as `(sha, context, state)`."""
        with self._lock:
            return list(self._statuses)

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
                state="MERGED" if pull.merged else "CLOSED" if pull.closed else "OPEN",
                draft=node["isDraft"],
                merged_at=_MERGED_AT if pull.merged else None,
                review_decision=pull.decision(),
                labels=tuple(self._host.pr_labels.get(number, ())),
                comments=tuple(pull.comments),
                reviews=tuple((r["node_id"], r["state"], r["body"]) for r in pull.reviews),
            )
            fresh["title"] = pull.title
            node.update(fresh)

    def _document(self, pull: _Pull) -> dict[str, Any]:
        node = self._host.pull(pull.number)
        return {
            "number": pull.number,
            "node_id": node["id"],
            "state": "closed" if pull.merged or pull.closed else "open",
            "draft": node["isDraft"],
            "title": pull.title,
            "body": pull.body,
            "merged": pull.merged,
            "head": {"ref": pull.head, "label": f"{pull.owner}:{pull.head}"},
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
            if listed["what"] == "files":
                return answer([])
            return answer(list(pull.reviews if listed["what"] == "reviews" else pull.inline))
        fetched = _REVIEW.fullmatch(path)
        if fetched and request.method == "GET":
            pull = self._pulls.get(int(fetched["n"]))
            found = [r for r in pull.reviews if r["id"] == int(fetched["review"])] if pull else []
            return answer(found[0]) if found else refusal(404, f"Not Found: {path}")
        reply = _REPLY.fullmatch(path)
        if reply and request.method == "POST":
            pull = self._pulls.get(int(reply["n"]))
            parent = [c for c in pull.inline if c["id"] == int(reply["note"])] if pull else []
            if pull is None or not parent:
                return refusal(404, f"Not Found: {path} names no inline comment")
            text = str(json.loads(request.content or b"{}").get("body", ""))
            review = self._new_review(pull, "COMMENTED", "")
            made = self._new_inline(
                pull,
                review,
                path=parent[0]["path"],
                line=parent[0]["line"],
                body=text,
                reply_to=parent[0]["id"],
            )
            return answer(made, 201)
        one = _PULL_ONE.fullmatch(path)
        if one and request.method == "PATCH":
            pull = self._pulls.get(int(one["n"]))
            if pull is None:
                return refusal(404, "Not Found")
            changes = json.loads(request.content or b"{}")
            pull.base = str(changes.get("base", pull.base))
            pull.body = str(changes.get("body", pull.body))
            if "state" in changes:
                pull.closed = changes["state"] == "closed"
            self._sync()
            return answer(self._document(pull))
        posted = _ISSUE_COMMENTS.fullmatch(path)
        if posted and request.method == "POST":
            pull = self._pulls.get(int(posted["n"]))
            if pull is None:
                return refusal(404, "Not Found")
            body = str(json.loads(request.content or b"{}").get("body", ""))
            self._ids += 1
            node = f"IC_kwDOAAAAAc{self._ids:08d}"
            pull.comments.append((node, body))
            return answer({"id": 2000 + self._ids, "node_id": node, "body": body}, 201)
        status = _STATUSES.fullmatch(path)
        if status and request.method == "POST":
            made = json.loads(request.content or b"{}")
            context, state = str(made.get("context", "")), str(made.get("state", ""))
            self._statuses.append((status["sha"], context, state))
            return answer(
                {"id": 3000 + len(self._statuses), "context": context, "state": state}, 201
            )
        return None

    def _new_review(self, pull: _Pull, state: str, body: str) -> dict[str, Any]:
        self._ids += 1
        review_id = 1000 + self._ids
        review = {
            "id": review_id,
            "node_id": f"PRR_kwDOAAAAAc{self._ids:08d}",
            "user": _REVIEWER,
            "body": body,
            "state": state,
            "html_url": f"{_WEB}/{pull.number}#pullrequestreview-{review_id}",
            "submitted_at": "2026-09-28T10:00:00Z",
            "commit_id": _COMMIT,
            "author_association": "CONTRIBUTOR",
        }
        pull.reviews.append(review)
        return review

    def _new_inline(
        self,
        pull: _Pull,
        review: dict[str, Any],
        *,
        path: str,
        line: int | None,
        body: str,
        reply_to: int | None = None,
    ) -> dict[str, Any]:
        self._ids += 1
        comment_id = 5000 + self._ids
        comment: dict[str, Any] = {
            "id": comment_id,
            "node_id": f"PRRC_kwDOAAAAAc{self._ids:08d}",
            "pull_request_review_id": review["id"],
            "diff_hunk": "@@ -0,0 +1,3 @@",
            "path": path,
            "commit_id": _COMMIT,
            "user": _REVIEWER,
            "body": body,
            "created_at": "2026-09-28T10:00:00Z",
            "updated_at": "2026-09-28T10:00:00Z",
            "html_url": f"{_WEB}/{pull.number}#discussion_r{comment_id}",
            "line": line,
            "side": "RIGHT",
        }
        if reply_to is not None:
            comment["in_reply_to_id"] = reply_to
        pull.inline.append(comment)
        return comment

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
        pull = _Pull(
            number, owner, head, base, str(body.get("title", "")), str(body.get("body", ""))
        )
        self._pulls[number] = pull
        self._host.pulls.append(github_answers.pull(number, head=head, base=base))
        self._sync()
        return answer(self._document(pull), 201)
