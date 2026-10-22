"""Support for the tests of the allowlisting proxy: a local upstream and a raw client."""

from __future__ import annotations

import http.server
import socket
from collections.abc import Iterator
from contextlib import contextmanager

from tests.http_thread import serving

UPSTREAM_BODY = "upstream-ok"


class _Upstream(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = UPSTREAM_BODY.encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class _KeepAliveUpstream(_Upstream):
    """An HTTP/1.1 server that keeps the connection open for the next request unless the
    request asked for it to close, as a real server does."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        body = UPSTREAM_BODY.encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def upstream(*, keep_alive: bool = False) -> Iterator[int]:
    """A local HTTP server answering every GET with `UPSTREAM_BODY`; yields its port. With
    `keep_alive` it speaks HTTP/1.1 and answers further requests on the same connection."""
    handler = _KeepAliveUpstream if keep_alive else _Upstream
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    with serving(server):
        yield server.server_address[1]


def _read_all(client: socket.socket) -> bytes:
    chunks: list[bytes] = []
    while chunk := client.recv(4096):
        chunks.append(chunk)
    return b"".join(chunks)


def plain_get(proxy_port: int, url: str) -> tuple[int, str]:
    """A plain-HTTP request through the proxy as a client sends it: the absolute URL as the
    target. Returns the status code and the rest of the response."""
    host = url.split("//", 1)[1].split("/", 1)[0]
    request = f"GET {url} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n"
    with socket.create_connection(("127.0.0.1", proxy_port), timeout=10) as client:
        client.sendall(request.encode())
        return split_response(_read_all(client))


def send_raw(proxy_port: int, request: str) -> tuple[int, str]:
    """`request` written to the proxy in one `sendall`; returns the status code and the rest of
    what the proxy sends before it closes the connection."""
    with socket.create_connection(("127.0.0.1", proxy_port), timeout=10) as client:
        client.sendall(request.encode())
        return split_response(_read_all(client))


def connect(proxy_port: int, target: str, *, then: str = "") -> tuple[int, str]:
    """A `CONNECT target` through the proxy; after a 200, sends `then` down the tunnel. Returns
    the status code of the proxy's answer and everything after its headers."""
    with socket.create_connection(("127.0.0.1", proxy_port), timeout=10) as client:
        client.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = client.recv(4096)
            if not chunk:
                break
            head += chunk
        status, _, rest = head.partition(b"\r\n\r\n")
        code = int(status.split()[1])
        body = rest
        if code == 200 and then:
            client.sendall(then.encode())
            body += _read_all(client)
        elif code != 200:
            body += _read_all(client)
        return code, body.decode(errors="replace")


def split_response(raw: bytes) -> tuple[int, str]:
    head, _, body = raw.partition(b"\r\n\r\n")
    return int(head.split()[1]), body.decode(errors="replace")
