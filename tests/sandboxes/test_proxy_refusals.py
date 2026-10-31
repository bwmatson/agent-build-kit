"""The allowlisting proxy reports each host it refuses, so a step's refused request is visible
(spec: claude-steps-can-renew-their-login).

The proxy used to answer 403 and say nothing else. A refusal of the `claude` process's own
traffic never reaches a tool's output, so the renewal of an expired login was refused unseen."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_build_kit.sandboxes import Coverage, SandboxPolicy
from agent_build_kit.sandboxes import confinement as confinement_module
from agent_build_kit.sandboxes.proxy import Proxy
from tests.sandboxes.proxy_support import connect, plain_get, upstream


def test_a_refused_plain_request_reports_its_host_and_port() -> None:
    refused: list[tuple[str, int]] = []

    with Proxy(["pypi.org"], on_refused=lambda host, port: refused.append((host, port))) as proxy:
        code, _ = plain_get(proxy.port, "http://example.com/")

    assert code == 403
    assert refused == [("example.com", 80)]


def test_a_refused_connect_reports_its_host_and_port() -> None:
    refused: list[tuple[str, int]] = []

    with Proxy(["pypi.org"], on_refused=lambda host, port: refused.append((host, port))) as proxy:
        code, _ = connect(proxy.port, "platform.claude.com:443")

    assert code == 403
    assert refused == [("platform.claude.com", 443)]


def test_an_allowed_host_reports_nothing() -> None:
    refused: list[tuple[str, int]] = []

    with (
        upstream() as port,
        Proxy(["127.0.0.1"], on_refused=lambda host, port: refused.append((host, port))) as proxy,
    ):
        code, _ = plain_get(proxy.port, f"http://127.0.0.1:{port}/")

    assert code == 200
    assert refused == []


def test_a_callback_that_fails_does_not_stop_the_refusal() -> None:
    def broken(host: str, port: int) -> None:
        raise RuntimeError("the log is gone")

    with Proxy(["pypi.org"], on_refused=broken) as proxy:
        code, body = plain_get(proxy.port, "http://example.com/")

    assert code == 403
    assert "example.com" in body


def test_a_proxy_with_no_callback_still_refuses() -> None:
    with Proxy(["pypi.org"]) as proxy:
        code, body = plain_get(proxy.port, "http://example.com/")

    assert code == 403
    assert "example.com" in body


def test_confinement_gives_the_proxy_the_refusal_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    class FakeProxy:
        port = 1

        def __init__(self, hosts, on_refused=None) -> None:
            seen["hosts"] = tuple(hosts)
            seen["on_refused"] = on_refused

        def __enter__(self) -> FakeProxy:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    found = SimpleNamespace(ok=True, coverage=Coverage.PROCESS, cause="", fix="")
    monkeypatch.setattr(confinement_module, "Proxy", FakeProxy)
    monkeypatch.setattr(
        confinement_module.sandboxes, "probe", lambda name: (SimpleNamespace(name="fake"), found)
    )
    policy = SandboxPolicy(write=(), read=(), hosts=("api.anthropic.com",), required=Coverage.NONE)
    callback = lambda host, port: None  # noqa: E731

    with confinement_module.confinement(policy, on_refused=callback):
        pass

    assert seen == {"hosts": ("api.anthropic.com",), "on_refused": callback}
