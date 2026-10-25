"""No module reads a single unit ceiling: the planner's prompt states each review tier's ceiling
where it limits a unit, and the setting that was the one ceiling is read nowhere (spec:
review-always-on)."""

from __future__ import annotations

from pathlib import Path

import agent_build_kit
from tests.tier_ceiling_support import configure
from tests.tier_prompt_support import prompt_for

SETTING = "max_unit_lines"
# The load error that refuses the setting, and the migration that moves its value.
MAY_NAME_IT = {"config.py", "config_migrate.py"}


def test_only_the_load_error_and_the_migration_name_the_setting() -> None:
    root = Path(agent_build_kit.__file__).parent
    readers = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if SETTING in path.read_text() and path.name not in MAY_NAME_IT
    )

    assert readers == []


def test_the_rule_against_combining_groups_over_the_ceiling_names_every_tiers_ceiling() -> None:
    configure(enabled=True)

    prompt = prompt_for([])

    start = prompt.index("Never combine groups into a unit estimated over")
    rule = prompt[start : prompt.index("\n- ", start)]
    for tier, ceiling in (("auto", "5000"), ("light", "2000"), ("full", "750")):
        assert tier in rule and ceiling in rule
