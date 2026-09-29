"""The runtime registry: which agent executes the workspace's steps.

The same shape as `forges/` and `profiles/`: filled in-process, no plugin
discovery, and an unknown name says which names it knows. Group 1 ships no
built-in adapter, so these tests register a plain-class double into an empty
registry of their own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.config import ModelsConfig
from agent_build_kit.runtimes import (
    AgentRequest,
    AgentResult,
    AgentRuntime,
    PolicyReport,
    UsageStatus,
)
from agent_build_kit.runtimes.base import PolicyCoverage


class _Double:
    """A runtime as a test supplies one: a plain class, no base to inherit."""

    implemented = True
    policy_coverage: PolicyCoverage = "none"
    supports_usage_tracking = False
    supports_streaming = False
    requires: tuple[str, ...] = ()
    agent_command: tuple[str, ...] = ()
    default_models = ModelsConfig()

    def __init__(self, name: str) -> None:
        self.name = name

    def run(self, request: AgentRequest) -> AgentResult:
        return AgentResult(ok=True, text=request.prompt)

    def get_usage_status(self) -> UsageStatus | None:
        return None

    def check_policy(self, cwd: Path) -> PolicyReport:
        return PolicyReport(ok=False, unenforced=("merging a pull request",))


# The static half of the conformance check: a double that drifts from the
# Protocol fails the type checker here, as an adapter does at its own module end.
_: AgentRuntime = _Double("double")


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtimes, "_REGISTRY", {})


@pytest.mark.usefixtures("registry")
def test_a_runtime_comes_back_by_name() -> None:
    double = _Double("double")
    runtimes.register(double)

    assert runtimes.get("double") is double


@pytest.mark.usefixtures("registry")
def test_an_unknown_runtime_names_the_ones_it_knows() -> None:
    """The error a typo in abk.yaml's `runtime:` produces, so it reads as a
    typo rather than as a missing feature."""
    runtimes.register(_Double("double"))
    runtimes.register(_Double("other"))

    with pytest.raises(KeyError) as caught:
        runtimes.get("nonesuch")

    assert "nonesuch" in str(caught.value)
    assert runtimes.names() == ["double", "other"]
    for known in runtimes.names():
        assert known in str(caught.value)


@pytest.mark.usefixtures("registry")
def test_every_registered_runtime_is_keyed_by_its_own_name() -> None:
    """Structural typing is checked statically, so this asserts the parts a
    static check cannot: that the registry is not empty and each entry is
    registered under the name it reports."""
    runtimes.register(_Double("double"))

    assert runtimes.names()
    for name in runtimes.names():
        assert runtimes.get(name).name == name


def test_the_built_in_registry_keys_each_runtime_by_its_own_name() -> None:
    """Whatever `_load_builtin` registers, the key abk.yaml names is the name
    the adapter reports."""
    for name in runtimes.names():
        assert runtimes.get(name).name == name
