"""The architecture guide and the `abk-pipeline` skill say that a merge is recorded only when it is
on the default branch, and what `landed_off_default` and `base_not_moved` mean
(spec: merge-must-land-on-the-default-branch)."""

from __future__ import annotations

import pytest

from tests.doc_text import ROOT
from tests.prompt_text import flat

ARCHITECTURE = flat((ROOT / "docs" / "architecture.md").read_text())
SKILL = flat(
    (ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md").read_text()
)


def test_the_architecture_says_a_merge_is_recorded_only_when_on_the_default_branch() -> None:
    assert "recorded only when" in ARCHITECTURE
    assert "default branch" in ARCHITECTURE


@pytest.mark.parametrize("cause", ["landed_off_default", "base_not_moved"])
def test_the_architecture_explains_the_cause_beyond_the_list_of_causes(cause: str) -> None:
    assert ARCHITECTURE.count(f"`{cause}`") >= 2


@pytest.mark.parametrize("cause", ["landed_off_default", "base_not_moved"])
def test_the_skill_mentions_the_cause(cause: str) -> None:
    assert f"`{cause}`" in SKILL
