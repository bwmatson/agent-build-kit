"""The three kinds of test are stated once: the marker descriptions in `pyproject.toml` and the
taxonomy in `AGENTS.md` carry the same rule for each kind (spec: test-markers)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The rule each kind is stated by, in the words both texts share.
RULES = {
    "unit-test": "needs nothing running",
    "integration-test": "needs no live stack and no configuration of its own",
    "e2e-test": "needs the real local stack and is never run in CI",
}


def squashed(text: str) -> str:
    return " ".join(text.split())


def marker_description(name: str) -> str:
    options = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]
    (found,) = (m for m in options["markers"] if m.startswith(f"{name}:"))
    return squashed(found)


@pytest.mark.parametrize("kind", RULES)
def test_agents_md_states_the_rule_of_each_kind(kind: str) -> None:
    text = squashed((ROOT / "AGENTS.md").read_text())

    assert f"`{kind}`" in text
    assert RULES[kind] in text


def test_the_integration_marker_states_its_rule() -> None:
    assert RULES["integration-test"] in marker_description("integration")


def test_the_e2e_marker_states_its_rule() -> None:
    assert RULES["e2e-test"] in marker_description("e2e")
