"""A model gateway on a local port, speaking HTTP and JSON as one does: a master
key mints keys (`POST /key/generate`), every request made with a key is logged
against it (`GET /spend/logs?api_key=`) and a key is revoked with
`POST /key/delete`.

A test plays the model traffic with `spend`. The rows carry what a gateway logs
beyond the figures a client reads (request id, model, times, metadata), and the
minted key's reply carries its own extras, so a client that insists on only the
fields it needs is not what is being tested.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

MASTER = "sk-master-fixture"


class FakeGateway:
    def __init__(self) -> None:
        self.minted: list[dict[str, Any]] = []  # {"key", "alias", "auth", "body"}
        self.revoked: list[str] = []
        self.calls: list[tuple[str, str]] = []  # (method, path) of every request
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.refuse_mint = False
        self.fail_reads = False
        self._lock = threading.Lock()
        self.url = ""

    @property
    def aliases(self) -> list[str]:
        return [m["alias"] for m in self.minted]

    def spend(self, key: str, *, prompt: int, completion: int, cost: float) -> None:
        """One request the model served for `key`."""
        with self._lock:
            logged = self.rows.setdefault(key, [])
            logged.append(
                {
                    "request_id": f"chatcmpl-{len(logged)}",
                    "call_type": "acompletion",
                    "api_key": key,
                    "spend": cost,
                    "total_tokens": prompt + completion,
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "startTime": "2026-10-05T10:00:00.000000+00:00",
                    "endTime": "2026-10-05T10:00:03.000000+00:00",
                    "model": "served-model",
                    "user": "",
                    "metadata": {"status": "success"},
                }
            )

    def handler(self) -> type[BaseHTTPRequestHandler]:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def _reply(self, status: int, body: Any) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length) or b"{}")

            def do_POST(self) -> None:
                path = urlparse(self.path).path
                body = self._body()
                with gateway._lock:
                    gateway.calls.append(("POST", path))
                if self.headers.get("Authorization") != f"Bearer {MASTER}":
                    return self._reply(401, {"error": {"message": "invalid master key"}})
                if path == "/key/generate":
                    if gateway.refuse_mint:
                        return self._reply(500, {"error": {"message": "cannot mint"}})
                    with gateway._lock:
                        key = f"sk-run-{len(gateway.minted) + 1}"
                        gateway.minted.append(
                            {
                                "key": key,
                                "alias": body.get("key_alias"),
                                "auth": self.headers.get("Authorization"),
                                "body": body,
                            }
                        )
                    return self._reply(
                        200,
                        {
                            "key": key,
                            "key_alias": body.get("key_alias"),
                            "expires": "2026-10-05T14:00:00Z",
                            "models": [],
                            "spend": 0.0,
                            "max_budget": None,
                            "metadata": body.get("metadata") or {},
                        },
                    )
                if path == "/key/delete":
                    with gateway._lock:
                        gateway.revoked += body.get("keys", [])
                    return self._reply(200, {"deleted_keys": body.get("keys", [])})
                self._reply(404, {"error": "no such route"})

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                with gateway._lock:
                    gateway.calls.append(("GET", parsed.path))
                if self.headers.get("Authorization") != f"Bearer {MASTER}":
                    return self._reply(401, {"error": {"message": "invalid master key"}})
                if parsed.path == "/spend/logs" and not gateway.fail_reads:
                    key = parse_qs(parsed.query).get("api_key", [""])[0]
                    return self._reply(200, gateway.rows.get(key, []))
                self._reply(500 if gateway.fail_reads else 404, {"error": "unavailable"})

        return Handler


@contextmanager
def serving() -> Iterator[FakeGateway]:
    gateway = FakeGateway()
    server = ThreadingHTTPServer(("127.0.0.1", 0), gateway.handler())
    gateway.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield gateway
    finally:
        server.shutdown()
        server.server_close()


def unreachable_url() -> str:
    """The address of a port nothing listens on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"
