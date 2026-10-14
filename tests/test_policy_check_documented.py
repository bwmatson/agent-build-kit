"""The documents and skills describe a policy check that reads the agent's configuration.

The check starts no agent, so no document may still describe a probe that prompts one,
a question about spending tokens, a live flag, a probe timeout or a kept answer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.runtimes.policy_check import LABEL

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
DOCS = [ROOT / "docs" / name for name in ("cli.md", "init.md", "agent-runtimes.md")]
SKILL_FILES = [SKILLS / name / "SKILL.md" for name in ("abk-pipeline", "abk-config")]

REMOVED = {
    "a probe that prompts the agent": re.compile(
        r"probe run|a probe costs|check that prompts the agent|whose check prompts", re.I
    ),
    "a token question for the check": re.compile(r"spends tokens|policy_check_prompts_agent", re.I),
    "--live": re.compile(r"--live\b"),
    "policy_probe_seconds": re.compile(r"policy_probe_seconds"),
    "a 15-minute cache": re.compile(r"15 minutes|policy-check\.json", re.I),
}


def squashed(path: Path) -> str:
    return " ".join(path.read_text().split())


@pytest.mark.parametrize("path", [*DOCS, *SKILL_FILES], ids=lambda p: f"{p.parent.name}/{p.name}")
def test_the_command_is_named(path: Path):
    assert "abk policy check" in squashed(path)


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_the_label_is_stated(path: Path):
    assert LABEL in squashed(path)


def test_no_document_describes_the_removed_probe():
    found = {
        name: [
            p.relative_to(ROOT).as_posix()
            for p in [*DOCS, *SKILL_FILES]
            if pattern.search(squashed(p))
        ]
        for name, pattern in REMOVED.items()
    }
    found = {name: paths for name, paths in found.items() if paths}
    assert not found, f"still described: {found}"
