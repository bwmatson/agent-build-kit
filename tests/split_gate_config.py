"""Building a workspace whose `acp` split carries a gate (spec: split-gate-usage)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit.config import GateConfig, GateProviderConfig, WorkspaceConfig

PROVIDER = {"name": "modal", "budget_usd": 200}


def with_gate(gate: Any, *, split: str = "acp") -> WorkspaceConfig:
    """A workspace with one split, `split`, whose entry carries `gate`."""
    entry: dict[str, Any] = {"gate": gate}
    if split != "rest":
        entry["marker"] = f"runtime_{split}"
    return WorkspaceConfig.model_validate(
        {
            "tests": {"e2e_splits": {split: entry}},
            "repos": {"app": {"path": "/work/app", "slug": "example/app"}},
        }
    )


def gate_of(loaded: WorkspaceConfig, split: str = "acp") -> GateConfig:
    gate = loaded.tests.e2e_splits[split].gate
    assert gate is not None
    return gate


def provider_of(loaded: WorkspaceConfig, split: str = "acp") -> GateProviderConfig:
    provider = gate_of(loaded, split).provider
    assert provider is not None
    return provider


def refusal(gate: Any) -> str:
    """What loading refuses about `gate`: each error's setting path and message, never the
    input it echoes, so a name only counts when the refusal itself says it."""
    with pytest.raises(ValidationError) as refused:
        with_gate(gate)
    return "\n".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in refused.value.errors()
    )
