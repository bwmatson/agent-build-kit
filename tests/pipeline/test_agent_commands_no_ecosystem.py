"""The module that composes and renders the agent commands names no toolchain (spec:
toolchain-profiles)."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.config import RepoConfig
from agent_build_kit.pipeline import agent_commands

TOOL_WORDS = ["pytest", "vitest", "uv", "npx", "npm", "pre-commit"]


def test_the_source_holds_no_profile_name_and_no_tool_word(tmp_path: Path) -> None:
    repo = RepoConfig(path=tmp_path, slug="example/app")
    assert agent_commands.commands_note(repo), "the module does the work being scanned"
    source = Path(agent_commands.__file__).read_text()

    names = profiles.names()
    found = [
        word
        for word in [*names, *TOOL_WORDS]
        if re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", source)
    ]

    assert found == []
