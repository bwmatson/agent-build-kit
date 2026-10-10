"""A local upstream the proxy tests put the proxy in front of: it keeps what it was
asked and answers from a function the test gives it, over real HTTP."""

from __future__ import annotations

import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType

from agent_build_kit.model import Frozen


class Seen(Frozen):
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


class Answer(Frozen):
    status: int = 200
    headers: dict[str, str] = {}
    # More than one chunk is sent with chunked transfer encoding, each flushed alone.
    chunks: list[bytes] = [b"ok"]


def _echo(seen: Seen) -> Answer:
    return Answer(chunks=[b"echo:" + seen.body])


class FakeUpstream:
    url: str

    def __init__(self, answer: Callable[[Seen], Answer] = _echo) -> None:
        self.seen: list[Seen] = []
        self.url = ""
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _serve(self) -> None:
                size = int(self.headers.get("Content-Length") or 0)
                request = Seen(
                    method=self.command,
                    path=self.path,
                    headers={k.lower(): v for k, v in self.headers.items()},
                    body=self.rfile.read(size),
                )
                outer.seen.append(request)
                reply = answer(request)
                self.send_response(reply.status)
                for name, value in reply.headers.items():
                    self.send_header(name, value)
                if len(reply.chunks) > 1:
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    for chunk in reply.chunks:
                        self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                        self.wfile.flush()
                    self.wfile.write(b"0\r\n\r\n")
                else:
                    body = reply.chunks[0] if reply.chunks else b""
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            do_GET = do_POST = _serve

            def log_message(self, format: str, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> FakeUpstream:
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread.start()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()
