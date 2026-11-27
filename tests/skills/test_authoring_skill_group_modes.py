"""The authoring prompt of `abk init` keeps the exception that only a group that touches code writes
tests first (spec: group-build-modes)."""

from __future__ import annotations

from agent_build_kit.init import propose
from tests.prompt_text import flat


def test_the_authoring_prompt_keeps_the_exception() -> None:
    prompt = flat(propose.PROMPT)

    assert "Test tasks come before implementation tasks in every group." not in prompt
    assert "only a group that touches code" in prompt
