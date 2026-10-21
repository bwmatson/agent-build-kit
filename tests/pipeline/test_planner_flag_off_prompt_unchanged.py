"""With per-tier sizing off, the planner's instructions are byte for byte the text they were
before the tier ceilings existed, whatever ceilings and overrides are set
(spec: review-tier-ceilings).

The expected texts in `golden/` were produced by the planner before this change, for the
instructions without a calibrated kind and with one (twenty units of `app` that landed at 1.5
times their estimate).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.compat_names import old_spelling
from agent_build_kit.model import TestTier
from tests.calibration_support import limits
from tests.tier_ceiling_support import configure
from tests.tier_prompt_support import landed_at_one_and_a_half, prompt_for

GOLDEN = Path(__file__).parent / "golden"
OVERRIDES = {"auto": 3000, "light": 1500}


def golden(name: str) -> str:
    """The recorded text, with the old tag spellings its prompt still names put back (the
    files carry placeholders, so the repository holds no old spelling)."""
    return (
        (GOLDEN / name)
        .read_text()
        .replace("@OLD_UNIT_TEST@", old_spelling(TestTier.UNIT_TEST))
        .replace("@OLD_E2E@", old_spelling(TestTier.E2E_TEST))
    )


@pytest.mark.parametrize("overrides", [None, OVERRIDES], ids=["no override", "override"])
def test_the_prompt_without_a_calibrated_kind_is_the_text_it_was(
    overrides: dict[str, int] | None,
) -> None:
    limits()
    configure(enabled=False, repo_ceilings=overrides)

    assert prompt_for([]) == golden("planner_prompt_flag_off.txt")


@pytest.mark.parametrize("overrides", [None, OVERRIDES], ids=["no override", "override"])
def test_the_prompt_with_a_calibrated_kind_is_the_text_it_was(
    overrides: dict[str, int] | None,
) -> None:
    limits()
    configure(enabled=False, repo_ceilings=overrides)

    expected = golden("planner_prompt_flag_off_calibrated.txt")
    assert prompt_for(landed_at_one_and_a_half()) == expected
