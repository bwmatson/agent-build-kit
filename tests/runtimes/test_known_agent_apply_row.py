"""The known-agent table's apply descriptors: every one complete, and the first agent's
row carrying one that merges into a fixture configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_build_kit.runtimes.known_agents import KNOWN_AGENTS, ApplyPolicy, KnownAgent
from agent_build_kit.runtimes.policy_apply import WRITERS, Status, apply
from agent_build_kit.runtimes.recommended_policy import patterns


def _with_applier() -> list[KnownAgent]:
    return [agent for agent in KNOWN_AGENTS if agent.apply is not None]


def _problems(agent: KnownAgent) -> list[str]:
    descriptor = agent.apply
    assert descriptor is not None
    found = []
    for field in ("home_env", "home_default", "file", "verified"):
        if not getattr(descriptor, field).strip():
            found.append(f"{agent.name}: {field} is empty")
    if not descriptor.deny_path or not all(descriptor.deny_path):
        found.append(f"{agent.name}: deny_path is empty")
    if descriptor.format not in WRITERS:
        found.append(f"{agent.name}: format {descriptor.format} has no writer")
    return found


def _first() -> ApplyPolicy:
    rows = _with_applier()
    assert rows, "no known agent carries an apply descriptor"
    descriptor = rows[0].apply
    assert descriptor is not None
    return descriptor


def test_every_descriptor_is_complete() -> None:
    rows = _with_applier()
    assert rows, "no known agent carries an apply descriptor"
    assert [problem for agent in rows for problem in _problems(agent)] == []


def test_only_the_verified_first_agent_carries_one() -> None:
    assert [agent.name for agent in _with_applier()] == [KNOWN_AGENTS[0].name]


def test_the_default_home_is_a_directory_name_not_a_home_path() -> None:
    home = _first().home_default
    assert home
    assert not home.startswith(("~", "/"))
    assert "/" not in home.strip("/")


def test_the_first_agents_round_trip_adds_the_patterns_and_keeps_off_quoted(
    tmp_path: Path,
) -> None:
    descriptor = _first()
    assert descriptor.deny_path == ("approvals", "deny")
    home = tmp_path / "home"
    home.mkdir()
    config = home / descriptor.file
    before = '# mine\napprovals:\n  mode: "off"   # quoted\n  deny:\nmodel: fast\n'
    config.write_bytes(before.encode())

    result = apply(descriptor, home)

    after = config.read_bytes().decode()
    assert result.status == Status.WRITTEN
    assert yaml.safe_load(after)["approvals"]["deny"] == patterns()
    kept = iter(after.splitlines())
    assert all(line in kept for line in before.splitlines())
