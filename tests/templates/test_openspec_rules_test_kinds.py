"""The rules text and the propose prompts name the three test kinds
(spec: integration-test-kind-is-a-label)"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import agent_build_kit.tracks
from agent_build_kit.init.propose import PROMPT
from agent_build_kit.init.scaffold import template
from tests.prompt_text import flat

PROPOSE_MD = Path(agent_build_kit.tracks.__file__).parent / "prompts" / "propose.md"

TEXTS = {
    "rules": lambda: template("openspec_rules.yaml"),
    "init propose prompt": lambda: PROMPT.replace("{rules}", ""),
    "track propose prompt": lambda: PROPOSE_MD.read_text(),
}

# each kind, with words its one-line meaning must carry
MEANINGS = {
    "unit-test": ("ordinary suite",),
    "integration-test": ("across modules", "no live stack"),
    "e2e-test": ("real local stack",),
}


def sentences(name: str) -> list[str]:
    return re.split(r"(?<=[.;:])\s+", flat(TEXTS[name]()))


@pytest.mark.parametrize("name", TEXTS)
@pytest.mark.parametrize("kind", MEANINGS)
def test_each_kind_is_named_with_what_it_covers(name: str, kind: str) -> None:
    carrying = [s for s in sentences(name) if f"`{kind}`" in s]

    assert any(all(word in s for word in MEANINGS[kind]) for s in carrying), carrying


@pytest.mark.parametrize("name", TEXTS)
def test_integration_test_is_said_not_to_be_the_marker_or_the_folder(name: str) -> None:
    carrying = [s for s in sentences(name) if "`integration-test`" in s]

    assert any(
        "not" in s and "`integration` marker" in s and "tests/integration/" in s for s in carrying
    ), carrying


@pytest.mark.parametrize("name", TEXTS)
def test_no_sentence_lists_only_two_kinds(name: str) -> None:
    two = [s for s in sentences(name) if "unit-test or e2e-test" in s or "unit-test, e2e-test" in s]

    assert two == []


@pytest.mark.parametrize("name", TEXTS)
def test_acceptance_is_said_to_be_e2e_test_only(name: str) -> None:
    carrying = [s for s in sentences(name) if "[acceptance]" in s]

    assert any("e2e-test" in s and "only" in s for s in carrying), carrying
