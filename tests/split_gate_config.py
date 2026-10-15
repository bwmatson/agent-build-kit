"""Building a workspace whose `acp` split carries a gate (spec: split-gate-usage)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit.config import WorkspaceConfig

PROVIDER = {"name": "modal", "budget_usd": 200}


def with_gate(gate: Any, *, split: str = "acp") -> WorkspaceConfig:
    """A workspace with one split, `split`, whose entry carries `gate`."""
    entry: dict[str, Any] = {"gate": gate}
    if split != "rest":
        entry["marker"] = f"runtime_{split}"
    return WorkspaceConfig.model_validate(
        {
            "tests": {"tier2_splits": {split: entry}},
            "repos": {"app": {"path": "/work/app", "slug": "example/app"}},
        }
    )


def gate_of(loaded: WorkspaceConfig, split: str = "acp") -> Any:
    return loaded.tests.tier2_splits[split].gate  # type: ignore[attr-defined]


def refusal(gate: Any) -> str:
    """What loading refuses about `gate`: each error's setting path and message, never the
    input it echoes, so a name only counts when the refusal itself says it."""
    with pytest.raises(ValidationError) as refused:
        with_gate(gate)
    return "\n".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in refused.value.errors()
    )
