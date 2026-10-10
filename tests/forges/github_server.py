"""A fake GitHub host a process can reach over HTTP, for tests that run `abk` as
a subprocess and point `ABK_GITHUB_API_URL` at it.

It answers the REST and GraphQL routes the forge calls from the recorded answers
in `github_answers.py` through the route table in `github_routes.py`, keeps its state
in memory, and lets the test change that state the way a reviewer would on the host.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Any

import httpx

from tests.forges.github_host import GitHubHost, refusal
from tests.forges.github_routes import GitHubState
from tests.forges.mock_host import recorded


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
        self.state = GitHubState(first_number=first_number)
        self._host = GitHubHost(state=self.state)
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
            self.state.new_comment(self.state.made[number], body)

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
            pull = self.state.made[number]
            review = self.state.new_review(pull, state, body)
            if inline is None:
                return None
            path, line, text = inline
            return self.state.new_inline(pull, review, path=path, line=line, body=text)["id"]

    def review_comments(self, number: int) -> list[dict[str, Any]]:
        """Every inline comment on the pull request, replies included, as the
        pulls API lists them."""
        with self._lock:
            return [dict(c) for c in self.state.made[number].inline]

    def merge(self, number: int) -> None:
        with self._lock:
            self.state.made[number].merged = True

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
            return list(self.state.statuses)

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
            missed = len(self._host.unrouted)
            reply = self._host.handle_request(request)
            if len(self._host.unrouted) > missed:
                self._unrouted.append(key)
                return refusal(404, f"No route for {key[0]} {key[1]}")
            return reply
