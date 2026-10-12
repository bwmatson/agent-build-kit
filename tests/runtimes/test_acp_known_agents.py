"""The table of known protocol agents: data, each entry complete, and named nowhere else."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit.runtimes import acp

SRC = Path(acp.__file__).resolve().parents[1]


def test_every_entry_says_how_it_starts_and_how_far_it_is_verified() -> None:
    assert acp.KNOWN_AGENTS
    for agent in acp.KNOWN_AGENTS:
        assert agent.program, agent.name
        assert agent.variants, agent.name
        assert all(variant.argv for variant in agent.variants), agent.name
        assert agent.verified.strip(), agent.name
        assert agent.source.strip(), agent.name


def test_no_framework_file_outside_the_table_names_a_product_from_it() -> None:
    programs = "|".join(re.escape(agent.program) for agent in acp.KNOWN_AGENTS)
    assert programs
    named = re.compile(r"(?<![\w-])(?:" + programs + r")(?![\w-])", re.IGNORECASE)
    table_module = Path(acp.__file__).resolve()

    offenders = [
        f"{path.relative_to(SRC)}: {found.group()}"
        for path in sorted(SRC.rglob("*.py"))
        if path != table_module
        for found in named.finditer(path.read_text())
    ]

    assert offenders == []
