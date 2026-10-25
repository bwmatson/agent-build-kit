"""The sandbox is on unless a workspace turns it off (spec: sandbox-default)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import load


def write(tmp_path: Path, body: str = "") -> Path:
    path = tmp_path / "abk.yaml"
    path.write_text("repos: {}\n" + body)
    return path


def test_the_sandbox_is_on_with_no_block_and_off_when_the_workspace_says_so(
    tmp_path: Path,
) -> None:
    assert load(write(tmp_path)).model_dump()["sandbox"] == {"enabled": True, "backend": "auto"}

    off = load(write(tmp_path, "sandbox:\n  enabled: false\n"))

    assert off.model_dump()["sandbox"] == {"enabled": False, "backend": "auto"}
