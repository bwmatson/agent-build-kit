"""The reverse proxy that records and replays the calls of tier-2 tests.

One listener on loopback per configured upstream; the code under test is given the
listener's address through the environment variables the upstream names.
"""

from __future__ import annotations

import gzip
import shutil
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from urllib.parse import unquote, urlsplit

import httpx

from agent_build_kit.config import ReplayConfig, ReplayUpstream
from agent_build_kit.model import Frozen
from agent_build_kit.replay.hosts import InStackHosts
from agent_build_kit.replay.models import (
    STORED_HEADERS,
    Cassette,
    ReplayMode,
    Request,
    Rule,
    StoredResponse,
    UpstreamKind,
    applied_rules,
    request_key,
    summarise,
)
from agent_build_kit.replay.store import (
    find_cassette,
    load_cassette,
    test_directory,
    write_cassette,
)

# Per connection, not part of an answer: the proxy sets its own framing.
_HOP_BY_HOP = frozenset({"transfer-encoding", "connection", "content-length", "keep-alive"})
_NOT_FORWARDED = _HOP_BY_HOP | {"host"}


class InStackUpstream(Exception):
    """A configured upstream whose host is part of the stack."""


class SecretInRecording(Exception):
    """A response body held a configured secret; the test's calls were not stored."""


class _Answer(Frozen):
    status: int
    headers: dict[str, str]
    # In the order received; one chunk when the answer was not streamed.
    chunks: list[bytes]


class ReplayProxy:
    def __init__(
        self,
        config: ReplayConfig,
        mode: ReplayMode,
        *,
        staging: Path,
        in_stack: InStackHosts | None = None,
        secrets: Sequence[str] = (),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        settle_seconds: float = 30,
    ) -> None:
        self.config = config
        self.mode = mode
        # The calls so far that were not recorded because their body was too large.
        self.too_large: list[str] = []
        # The tests whose calls were not promoted: the directory would pass `max_directory_mb`,
        # or a call was still in flight at the end of the test.
        self.over_size: list[str] = []
        self.incomplete: list[str] = []
        # The declared rules that applied to a call, in the tests run so far.
        self.rules_used: list[Rule] = []
        self._staging = staging
        self._settle = settle_seconds
        self._in_stack = in_stack
        self._secrets = [secret.encode() for secret in secrets]
        self._clock = clock
        self._lock = threading.Condition()
        self._active = 0
        self._test_id = ""
        self._rules: Sequence[Rule] = ()
        self._calls = 0
        self._servers: dict[str, ThreadingHTTPServer] = {}
        self._client = httpx.Client(timeout=600)

    def __enter__(self) -> ReplayProxy:
        if self.mode is ReplayMode.off:
            return self
        for upstream in self.config.upstreams:
            host = urlsplit(upstream.url).hostname or ""
            if self._in_stack and (key := self._in_stack.why(host)):
                raise InStackUpstream(
                    f"upstream {upstream.name!r}: host {host} is in the stack ({key})"
                )
        for upstream in self.config.upstreams:
            server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler(upstream))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self._servers[upstream.name] = server
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        for server in self._servers.values():
            server.shutdown()
            server.server_close()
        self._servers = {}
        self._client.close()

    @property
    def addresses(self) -> dict[str, str]:
        """Each upstream's name to its listener's base URL; empty when the mode is `off`."""
        return {
            name: f"http://127.0.0.1:{server.server_address[1]}"
            for name, server in self._servers.items()
        }

    def environment(self) -> dict[str, str]:
        """The environment variables, each set to its upstream's listener; empty when `off`."""
        addresses = self.addresses
        return {
            variable: addresses[upstream.name]
            for upstream in self.config.upstreams
            if upstream.name in addresses
            for variable in upstream.env
        }

    def begin(self, test_id: str, rules: Sequence[Rule] = ()) -> None:
        """Calls from here on belong to `test_id`, and `rules` are declared for them."""
        with self._lock:
            self._test_id = test_id
            self._rules = rules
            self._calls = 0
        shutil.rmtree(test_directory(self._staging, test_id), ignore_errors=True)

    def finish(self, *, passed: bool) -> None:
        """Promote the staged calls of the test to the cassette directory, or discard them."""
        with self._lock:
            # A client has its answer before the proxy has staged the call.
            settled = self._lock.wait_for(lambda: self._active == 0, timeout=self._settle)
        staged = test_directory(self._staging, self._test_id)
        try:
            if not passed:
                return
            if not settled:
                self.incomplete.append(self._test_id)
                return
            if not staged.exists():
                return
            files = sorted(staged.glob("*.json.gz"))
            if any(self._leaks(load_cassette(path)) for path in files):
                raise SecretInRecording(f"{self._test_id}: a call holds a configured secret")
            held = sum(path.stat().st_size for path in self.config.directory.rglob("*.json.gz"))
            if held + sum(path.stat().st_size for path in files) > (
                self.config.max_directory_mb * 1024 * 1024
            ):
                self.over_size.append(self._test_id)
                return
            target = test_directory(self.config.directory, self._test_id)
            target.mkdir(parents=True, exist_ok=True)
            for path in files:
                shutil.move(path, target / path.name)
        finally:
            shutil.rmtree(staged, ignore_errors=True)

    def _leaks(self, cassette: Cassette) -> bool:
        """Whether a configured secret is in the response body or in the request's address."""
        body = b"".join(cassette.response.chunks)
        try:
            found = [body, gzip.decompress(body)]
        except (OSError, EOFError):
            found = [body]
        address = f"{cassette.request.path}?{cassette.request.query}"
        found += [address.encode(), unquote(address).encode()]
        return any(secret in held for secret in self._secrets for held in found)

    def _handler(self, upstream: ReplayUpstream) -> type[BaseHTTPRequestHandler]:
        answer = self._answer

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _serve(self) -> None:
                parts = urlsplit(self.path)
                request = Request(
                    method=self.command,
                    path=parts.path,
                    query=parts.query,
                    headers={name.lower(): value for name, value in self.headers.items()},
                    body=self._body(),
                )
                answer(upstream, request, self)

            def _body(self) -> bytes:
                if "chunked" not in self.headers.get("Transfer-Encoding", "").lower():
                    return self.rfile.read(int(self.headers.get("Content-Length") or 0))
                body = b""
                while size := int(self.rfile.readline().split(b";")[0].strip() or b"0", 16):
                    body += self.rfile.read(size)
                    self.rfile.readline()
                while self.rfile.readline().strip():
                    pass  # trailers
                return body

            do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _serve

            def log_message(self, format: str, *args: object) -> None:
                pass

        return Handler

    def _answer(
        self, upstream: ReplayUpstream, request: Request, out: BaseHTTPRequestHandler
    ) -> None:
        with self._lock:
            self._active += 1
        try:
            self._answer_call(upstream, request, out)
        finally:
            with self._lock:
                self._active -= 1
                self._lock.notify_all()

    def _answer_call(
        self, upstream: ReplayUpstream, request: Request, out: BaseHTTPRequestHandler
    ) -> None:
        with self._lock:
            test_id, rules, index = self._test_id, self._rules, self._calls
            self._calls += 1
        applied = applied_rules(request, rules)
        key = request_key(
            request, rules, upstream=upstream.name, keyed_headers=upstream.keyed_headers
        )
        with self._lock:
            self.rules_used.extend(rule for rule in applied if rule not in self.rules_used)
        if self.mode is ReplayMode.replay:
            held = find_cassette(self.config.directory, test_id, key)
            if held is not None and not self._aged(upstream, held):
                _send(
                    out,
                    request.method,
                    held.response.status,
                    held.response.headers,
                    held.response.chunks,
                )
                return
        received = self._forward(upstream, request, out)
        if sum(len(chunk) for chunk in received.chunks) > self.config.max_body_bytes:
            self.too_large.append(key)
            return
        keep = STORED_HEADERS | ({"content-length"} if request.method == "HEAD" else set())
        stored = {n: v for n, v in received.headers.items() if n in keep}
        cassette = Cassette(
            key=key,
            upstream=upstream.name,
            kind=upstream.kind,
            recorded_at=self._clock(),
            test_id=test_id,
            call_index=index,
            rules=applied,
            request=summarise(request),
            response=StoredResponse(status=received.status, headers=stored, chunks=received.chunks),
        )
        with self._lock:
            write_cassette(self._staging, cassette)

    def _aged(self, upstream: ReplayUpstream, held: Cassette) -> bool:
        days = (
            self.config.llm_max_age_days
            if upstream.kind is UpstreamKind.llm
            else self.config.max_age_days
        )
        return self._clock() - held.recorded_at > timedelta(days=days)

    def _forward(
        self, upstream: ReplayUpstream, request: Request, out: BaseHTTPRequestHandler
    ) -> _Answer:
        """Ask the upstream, answering `out` as the answer arrives."""
        url = upstream.url.rstrip("/") + request.path
        headers = {n: v for n, v in request.headers.items() if n not in _NOT_FORWARDED}
        # The client's own, so the answer is what it asked for; the HTTP library would add its own.
        headers.setdefault("accept-encoding", "identity")
        with self._client.stream(
            request.method,
            url,
            params=request.query or None,
            headers=headers,
            content=request.body,
        ) as response:
            head = request.method == "HEAD"
            sent = {
                n.lower(): v
                for n, v in response.headers.items()
                if n.lower() not in _HOP_BY_HOP or (head and n.lower() == "content-length")
            }
            chunks: list[bytes] = []
            if "chunked" in response.headers.get("transfer-encoding", "").lower():
                _start(out, response.status_code, sent, None)
                for chunk in response.iter_raw():
                    chunks.append(chunk)
                    _write_chunk(out, chunk)
                out.wfile.write(b"0\r\n\r\n")
            else:
                chunks = list(response.iter_raw())
                _send(out, request.method, response.status_code, sent, chunks)
            return _Answer(status=response.status_code, headers=sent, chunks=chunks)


def _start(
    out: BaseHTTPRequestHandler, status: int, headers: dict[str, str], length: int | None
) -> None:
    out.send_response(status)
    for name, value in headers.items():
        out.send_header(name, value)
    if length is None:
        out.send_header("Transfer-Encoding", "chunked")
    else:
        out.send_header("Content-Length", str(length))
    out.end_headers()


def _write_chunk(out: BaseHTTPRequestHandler, chunk: bytes) -> None:
    out.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
    out.wfile.flush()


def _send(
    out: BaseHTTPRequestHandler,
    method: str,
    status: int,
    headers: dict[str, str],
    chunks: list[bytes],
) -> None:
    """Answer from chunks held: streamed when there was more than one, else in one piece.
    An answer to HEAD is its headers alone, with the length the upstream gave."""
    if method == "HEAD":
        out.send_response(status)
        for name, value in headers.items():
            out.send_header(name, value)
        out.end_headers()
        return
    if len(chunks) > 1:
        _start(out, status, headers, None)
        for chunk in chunks:
            _write_chunk(out, chunk)
        out.wfile.write(b"0\r\n\r\n")
        return
    body = b"".join(chunks)
    _start(out, status, headers, len(body))
    out.wfile.write(body)
