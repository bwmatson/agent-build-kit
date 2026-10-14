"""The policy check reads the agent's configuration and never runs the agent: the live probe, its
tracking, its prompt, its settings, its flag and its token question are gone from the product."""

from __future__ import annotations

import inspect

import pytest

from agent_build_kit import config
from agent_build_kit.cli import build_parser
from agent_build_kit.pipeline.vocabulary import OverheadNode
from agent_build_kit.runtimes import acp
from agent_build_kit.runtimes.known_agents import KnownAgent
from tests.ecosystem_names import SOURCE_ROOT

# The list of commands is the one thing of the probe that stays.
KEPT = {"PROBE_CLASSES", "probe_branch", "probe_rows"}
SETTINGS = ("policy_probe_seconds", "policy_oracle_seconds")
TOKEN_QUESTION = "spends tokens"
TEXT_SUFFIXES = {".py", ".md", ".txt", ".yaml", ".yml"}


def probe_names(owner: object) -> list[str]:
    return [
        name
        for name in dir(owner)
        if ("probe" in name.lower() or "oracle" in name.lower()) and name not in KEPT
    ]


def config_classes() -> list[type]:
    return [
        member
        for _name, member in inspect.getmembers(config, inspect.isclass)
        if hasattr(member, "model_fields")
    ]


def test_the_live_probe_and_its_remains_are_gone() -> None:
    left = [f"acp.{name}" for name in probe_names(acp)]
    left += [f"AcpRuntime.{name}" for name in probe_names(acp.AcpRuntime)]
    left += [
        f"{cls.__name__}.{field}"
        for cls in config_classes()
        for field in cls.model_fields
        if field in SETTINGS
    ]
    left += [f"OverheadNode.{node.name}" for node in OverheadNode if "probe" in node.name.lower()]
    left += [f"KnownAgent.{field}" for field in KnownAgent.model_fields if field == "oracle"]
    left += [
        str(path.relative_to(SOURCE_ROOT))
        for path in sorted(SOURCE_ROOT.rglob("*"))
        if path.is_file()
        and path.suffix in TEXT_SUFFIXES
        and TOKEN_QUESTION in path.read_text(errors="ignore")
    ]
    with pytest.raises(SystemExit):
        build_parser().parse_args(["policy", "check", "--live"])
    assert left == [], "the live policy probe is gone from the product"
