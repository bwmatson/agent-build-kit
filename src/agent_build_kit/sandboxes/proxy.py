"""The allowlisting proxy: the one way a confined process reaches the network."""

from __future__ import annotations

import select
import socket
import socketserver
import threading
from collections.abc import Callable, Sequence
from types import TracebackType
from urllib.parse import urlsplit

LOCALHOST = "127.0.0.1"
_TIMEOUT = 30
_CHUNK = 65536


def host_allowed(host: str, patterns: Sequence[str]) -> bool:
    """Whether `host` matches a pattern exactly or, for `*.suffix`, is a subdomain of it."""
    name = host.lower().rstrip(".")
    for pattern in patterns:
        pattern = pattern.lower()
        if pattern.startswith("*."):
            if name.endswith(pattern[1:]):
                return True
        elif name == pattern:
            return True
    return False


def _split_target(target: str, default_port: int) -> tuple[str, int]:
    host, sep, port = target.rpartition(":")
    if not sep or not port.isdigit():
        return target.strip("[]"), default_port
    return host.strip("[]"), int(port)


def _is_connection_header(header: str) -> bool:
    name = header.lower()
    return name.startswith("proxy-") or name.startswith("connection:")


class _Handler(socketserver.StreamRequestHandler):
    # Unbuffered, so nothing past the headers is pulled out of the socket before the relay.
    rbufsize = 0

    def _hosts(self) -> tuple[str, ...]:
        server = self.server
        assert isinstance(server, _Server)
        return server.hosts

    def handle(self) -> None:
        try:
            self._serve()
        except OSError:
            pass  # the client went away, or the upstream did: nothing to answer

    def _serve(self) -> None:
        self.request.settimeout(_TIMEOUT)
        line = self.rfile.readline(65537).decode("latin-1").strip()
        parts = line.split()
        if len(parts) != 3:
            return
        method, target, version = parts
        headers: list[str] = []
        while (header := self.rfile.readline(65537).decode("latin-1")) not in ("\r\n", "\n", ""):
            headers.append(header)
        if method.upper() == "CONNECT":
            host, port = _split_target(target, 443)
        else:
            url = urlsplit(target)
            host, port = url.hostname or "", url.port or 80
        if not host_allowed(host, self._hosts()):
            self._report_refused(host or target, port)
            self._answer(403, f"sandbox: the host {host or target} is not on the allowed list\n")
            return
        try:
            upstream = socket.create_connection((host, port), timeout=_TIMEOUT)
        except OSError as failure:
            self._answer(502, f"sandbox: could not reach {host}: {failure}\n")
            return
        with upstream:
            if method.upper() == "CONNECT":
                self.wfile.write(f"{version} 200 Connection established\r\n\r\n".encode())
                self.wfile.flush()
            else:
                url = urlsplit(target)
                path = (url.path or "/") + (f"?{url.query}" if url.query else "")
                # One request per connection: a later one on it could name another host.
                kept = [h for h in headers if not _is_connection_header(h)]
                head = (
                    f"{method} {path} {version}\r\n" + "".join(kept) + "Connection: close\r\n\r\n"
                )
                upstream.sendall(head.encode("latin-1"))
            self._relay(upstream)

    def _report_refused(self, host: str, port: int) -> None:
        """Tell the run's callback which host was refused; a callback that fails does not change
        the answer."""
        server = self.server
        assert isinstance(server, _Server)
        if server.on_refused is None:
            return
        try:
            server.on_refused(host, port)
        except Exception:  # noqa: BLE001, S110
            pass

    def _answer(self, code: int, text: str) -> None:
        body = text.encode()
        reason = {403: "Forbidden", 502: "Bad Gateway"}[code]
        self.wfile.write(
            f"HTTP/1.1 {code} {reason}\r\nContent-Type: text/plain\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )

    def _relay(self, upstream: socket.socket) -> None:
        sockets = [self.request, upstream]
        while True:
            ready, _, _ = select.select(sockets, [], [], _TIMEOUT)
            if not ready:
                return
            for source in ready:
                data = source.recv(_CHUNK)
                if not data:
                    return
                (upstream if source is self.request else self.request).sendall(data)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = False  # closing the server joins its handlers, so none outlives `Proxy`

    def __init__(
        self, hosts: Sequence[str], on_refused: Callable[[str, int], None] | None = None
    ) -> None:
        super().__init__((LOCALHOST, 0), _Handler)
        self.hosts = tuple(hosts)
        self.on_refused = on_refused


class Proxy:
    """Listens on a free local port; passes a request to an allowed host (exact or `*.suffix`)
    and answers 403 naming the host for any other, first telling `on_refused` the host and port.
    A context manager: leaving stops and joins it."""

    def __init__(
        self, hosts: Sequence[str], on_refused: Callable[[str, int], None] | None = None
    ) -> None:
        self._server = _Server(hosts, on_refused)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def __enter__(self) -> Proxy:
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
        self._thread.join(timeout=10)
