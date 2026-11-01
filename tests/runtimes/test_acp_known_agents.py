"""The table of known protocol agents: data, each entry complete, and named nowhere else."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.runtimes import known_agents
from agent_build_kit.runtimes.base import DOCUMENTED_ONLY, Candidate
from tests.time_limit import LOADED_TEST_TIME_LIMIT

PACKAGE = Path(known_agents.__file__).resolve().parents[1]
# Not source: caches, and the web UI's build output (git-ignored).
SKIPPED = ("__pycache__", "serve/static")


def test_every_entry_says_how_it_starts_and_how_far_it_is_verified() -> None:
    assert known_agents.KNOWN_AGENTS
    for agent in known_agents.KNOWN_AGENTS:
        assert agent.program, agent.name
        assert agent.variants, agent.name
        assert all(variant.argv for variant in agent.variants), agent.name
        assert agent.verified.strip(), agent.name
        assert agent.source.strip(), agent.name


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
def test_no_framework_file_outside_the_table_names_a_product_from_it() -> None:
    programs = "|".join(re.escape(agent.program) for agent in known_agents.KNOWN_AGENTS)
    assert programs
    named = re.compile(r"(?<![\w-])(?:" + programs + r")(?![\w-])", re.IGNORECASE)
    table_module = Path(known_agents.__file__).resolve()

    offenders = []
    for path in sorted(PACKAGE.rglob("*")):
        relative = path.relative_to(PACKAGE).as_posix()
        if not path.is_file() or path == table_module or any(s in relative for s in SKIPPED):
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue  # not a text file
        offenders += [f"{relative}: {found.group()}" for found in named.finditer(text)]

    assert offenders == []


def test_a_candidate_is_documented_only_by_the_shared_prefix_and_not_by_wording_elsewhere() -> None:
    documented = [a for a in known_agents.KNOWN_AGENTS if a.verified.startswith(DOCUMENTED_ONLY)]
    assert documented
    for agent in known_agents.KNOWN_AGENTS:
        candidate = Candidate(
            runtime="acp", command=("x",), label=agent.name, usable=True, verified=agent.verified
        )
        assert candidate.documented_only == (agent in documented), agent.name
    assert not Candidate(
        runtime="acp", command=("x",), label="x", usable=True, verified="run: not documented only"
    ).documented_only
