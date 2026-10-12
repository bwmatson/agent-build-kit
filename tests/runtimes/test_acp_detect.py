"""What the protocol runtime's probe reports for a known agent, without a model call."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from agent_build_kit.runtimes import acp
from tests.runtimes.acp_agent import use_agent
from tests.runtimes.probe_fakes import (
    HELP_TIMEOUT,
    OTHER,
    PLAIN,
    VARYING,
    Host,
    table,
    without_library,
)


def test_a_program_on_the_path_is_a_usable_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    table(monkeypatch, PLAIN)
    host = Host((PLAIN.program,))

    [candidate] = acp.RUNTIME.detect(host.which, host.run)

    assert candidate.runtime == "acp"
    assert candidate.usable is True
    assert candidate.label == PLAIN.name
    assert candidate.command == ("svc-a", "acp")
    assert PLAIN.needs in candidate.note
    assert candidate.verified == PLAIN.verified
    assert candidate.reasons == ()


def test_a_missing_program_is_unusable_and_the_reason_names_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table(monkeypatch, PLAIN)
    host = Host()

    [candidate] = acp.RUNTIME.detect(host.which, host.run)

    assert candidate.usable is False
    assert any("svc-a" in reason and "path" in reason for reason in candidate.reasons)


def test_a_program_without_the_library_is_unusable_and_the_reason_names_the_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table(monkeypatch, PLAIN)
    without_library(monkeypatch)
    host = Host((PLAIN.program,))

    [candidate] = acp.RUNTIME.detect(host.which, host.run)

    assert candidate.usable is False
    assert any("acp" in reason for reason in candidate.reasons)
    assert not any("path" in reason for reason in candidate.reasons)


def test_the_variant_the_help_shows_is_the_command(monkeypatch: pytest.MonkeyPatch) -> None:
    table(monkeypatch, VARYING)
    older = Host((VARYING.program,), helps={"svc-b": "usage: svc-b [--experimental-serve]"})
    newer = Host((VARYING.program,), helps={"svc-b": "usage: svc-b serve"})

    [from_older] = acp.RUNTIME.detect(older.which, older.run)
    [from_newer] = acp.RUNTIME.detect(newer.which, newer.run)

    assert (from_older.usable, from_older.command) == (True, ("svc-b", "--experimental-serve"))
    assert (from_newer.usable, from_newer.command) == (True, ("svc-b", "serve"))


def test_help_showing_neither_variant_makes_it_unusable(monkeypatch: pytest.MonkeyPatch) -> None:
    table(monkeypatch, VARYING)
    host = Host((VARYING.program,), helps={"svc-b": "usage: svc-b [options]"})

    [candidate] = acp.RUNTIME.detect(host.which, host.run)

    assert candidate.usable is False
    assert candidate.reasons


def test_a_help_that_times_out_is_unusable_and_the_others_are_still_probed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    table(monkeypatch, VARYING, PLAIN, OTHER)
    host = Host(
        (VARYING.program, PLAIN.program, OTHER.program),
        helps={"svc-c": "run"},
        hangs=(VARYING.program,),
    )

    found = {c.label: c for c in acp.RUNTIME.detect(host.which, host.run)}

    assert set(found) == {"svc-a", "svc-b", "svc-c"}
    assert found["svc-b"].usable is False
    assert any("time" in reason for reason in found["svc-b"].reasons)
    assert found["svc-a"].usable is True
    assert found["svc-c"].usable is True


def test_the_probe_starts_no_session_and_sends_no_prompt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record)
    table(monkeypatch, PLAIN, VARYING)

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the probe reached the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    host = Host((PLAIN.program, VARYING.program), helps={"svc-b": "serve"})

    acp.RUNTIME.detect(host.which, host.run)

    assert not record.exists() or record.read_text() == ""


def test_the_help_run_carries_a_five_second_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    table(monkeypatch, VARYING, PLAIN)
    host = Host((VARYING.program, PLAIN.program), helps={"svc-b": "serve"})

    acp.RUNTIME.detect(host.which, host.run)

    assert [argv[0] for argv, _ in host.runs] == ["svc-b"]
    assert all(kwargs.get("timeout") == HELP_TIMEOUT for _, kwargs in host.runs)
