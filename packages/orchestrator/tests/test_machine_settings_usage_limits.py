"""`machine_settings` classifies `usage_limits` as it did `limits`: a default a team may commit."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.machine_settings import machine_settings


def test_usage_limits_under_a_runtime_is_listed_as_a_default(tmp_path: Path) -> None:
    document = {"runtimes": {"r": {"usage_limits": {"session": {"usage_pause_pct": 70}}}}}

    found = machine_settings(document, tmp_path / "plan")

    assert [(s.path, s.kind) for s in found] == [(("runtimes", "r", "usage_limits"), "default")]
