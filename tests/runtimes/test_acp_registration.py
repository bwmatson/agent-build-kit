"""The `acp` runtime is selectable when its extra is installed, and its absence
leaves an installation importing cleanly with `claude_code` alone."""

from __future__ import annotations

import sys

import pytest

from agent_build_kit import runtimes


@pytest.fixture(autouse=True)
def empty_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtimes, "_REGISTRY", {})


def test_acp_is_registered_when_its_extra_is_installed() -> None:
    from agent_build_kit.runtimes import acp

    assert runtimes.get("acp") is acp.RUNTIME
    assert "acp" in runtimes.names()


def test_acp_is_an_implemented_runtime() -> None:
    from agent_build_kit.runtimes import acp

    assert acp.RUNTIME.implemented is True


def test_without_the_extra_only_claude_code_is_known(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "acp", None)
    monkeypatch.delitem(sys.modules, "agent_build_kit.runtimes.acp", raising=False)
    monkeypatch.delattr(runtimes, "acp", raising=False)

    assert runtimes.get("claude_code").name == "claude_code"
    assert runtimes.names() == ["claude_code"]
    with pytest.raises(KeyError, match="unknown agent runtime 'acp'"):
        runtimes.get("acp")


def test_a_failing_import_inside_the_adapter_is_not_mistaken_for_a_missing_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "agent_build_kit.pipeline.command_policy", None)
    monkeypatch.delitem(sys.modules, "agent_build_kit.runtimes.acp", raising=False)
    monkeypatch.delattr(runtimes, "acp", raising=False)

    with pytest.raises(ModuleNotFoundError, match="command_policy"):
        runtimes.get("claude_code")
