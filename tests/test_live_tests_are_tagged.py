"""A drift test fails an untagged live test that drives an agent, and an ACP scenario with no
Claude variant and no reason."""

from __future__ import annotations

import warnings

import pytest

from tests.live_tag_drift import (
    EVERY_LIVE_MODULE_TIME_LIMIT,
    INTEGRATION,
    agent_start_notes,
    drift,
    drifted,
    find_live_modules,
)
from tests.runtime_tag_collection import ROOT, collect
from tests.runtime_tags import runtime_tags

INIT_CONVENTIONS = INTEGRATION / "test_init_conventions_workspace.py"

# The fixture modules below are collected the way the project collects its own.
SCRATCH_IMPORT = "from tests.runtime_scratch import runtime_scratch\n"
AGENT_HOME_IMPORT = "from tests.agent_home import agent_home\n"
SCRATCH_MODULE_IMPORT = "from tests import runtime_scratch\n"
HOME_MODULE_IMPORT = "from tests import agent_home\n"
HEADER = "import pytest\n\npytestmark = pytest.mark.local_stack\n"
BUILDS_ONE_TAGGED = (
    f"{HEADER}{SCRATCH_IMPORT}\n\n@pytest.mark.runtime_claude_code\n"
    "def test_builds_a_unit():\n    pass\n"
)


# An import of a helper and the statement of a test that starts an agent through it (a test
# starts an agent by calling or reading it, not by the module importing it).
STARTS = [
    (SCRATCH_IMPORT, 'runtime_scratch("acp", None, None)'),
    (AGENT_HOME_IMPORT, "agent_home(None)"),
    ("import os\n", 'os.environ.get("ABK_ACCEPTANCE_ACP_COMMAND")'),
    (SCRATCH_MODULE_IMPORT, 'runtime_scratch.runtime_scratch("acp", None, None)'),
    (HOME_MODULE_IMPORT, "agent_home.agent_home(None)"),
]


@pytest.mark.parametrize(
    ("use", "call"), STARTS, ids=["scratch", "home", "command", "scratch-module", "home-module"]
)
def test_an_untagged_test_that_starts_an_agent_is_named(
    pytester: pytest.Pytester, use: str, call: str
) -> None:
    found = drifted(
        pytester,
        test_untagged=f"{HEADER}{use}\n\ndef test_builds_a_unit():\n    {call}\n",
    )

    assert len(found) == 1
    assert "test_builds_a_unit" in found[0]


def test_a_test_that_carries_one_tag_is_not_named(pytester: pytest.Pytester) -> None:
    assert drifted(pytester, test_tagged=BUILDS_ONE_TAGGED) == []


def test_a_test_that_starts_no_agent_passes_untagged(pytester: pytest.Pytester) -> None:
    assert drifted(pytester, test_plain=f"{HEADER}\n\ndef test_inits():\n    pass\n") == []


def test_the_init_conventions_module_which_starts_no_agent_passes_untagged(
    pytester: pytest.Pytester,
) -> None:
    items, _ = pytester.inline_genitems(str(INIT_CONVENTIONS))

    assert items
    assert drift(items) == []
    assert INIT_CONVENTIONS in find_live_modules(ROOT / "tests")


@pytest.mark.time_limit(EVERY_LIVE_MODULE_TIME_LIMIT)
def test_every_test_of_the_kits_live_modules_that_starts_an_agent_has_exactly_one_tag(
    pytester: pytest.Pytester,
) -> None:
    modules = find_live_modules(ROOT / "tests")
    assert modules
    items, _ = pytester.inline_genitems(*(str(m) for m in modules))

    assert items
    assert drift(items) == []
    for note in agent_start_notes(items):
        warnings.warn(note, stacklevel=1)


ACP_MODULE = """
import pytest

pytestmark = pytest.mark.local_stack
{import_}

@pytest.mark.runtime_acp
def test_lists_the_session():
    pass

{table}
"""
# One function parametrised per runtime, as the kit's live modules write a scenario with both.
BOTH_RUNTIMES = """
import pytest

from tests.runtime_scratch import RUNTIME_PARAMS

pytestmark = pytest.mark.local_stack


@pytest.mark.parametrize("runtime", RUNTIME_PARAMS)
def test_lists_the_session(runtime):
    pass
"""


def acp_module(table: str = "") -> str:
    return ACP_MODULE.format(import_=SCRATCH_IMPORT, table=table)


def test_an_acp_scenario_with_no_claude_sibling_and_no_reason_is_named(
    pytester: pytest.Pytester,
) -> None:
    found = drifted(pytester, test_acp_only=acp_module())

    assert len(found) == 1
    assert "test_lists_the_session" in found[0]


def test_an_acp_scenario_with_a_claude_sibling_passes(pytester: pytest.Pytester) -> None:
    pytester.syspathinsert(ROOT)
    pytester.makepyfile(test_both=BOTH_RUNTIMES)
    items, _ = pytester.inline_genitems()

    assert sorted(runtime_tags(item) for item in items) == [
        ["runtime_acp"],
        ["runtime_claude_code"],
    ]
    assert drift(items) == []


def test_an_entry_with_an_empty_reason_is_named(pytester: pytest.Pytester) -> None:
    found = drifted(
        pytester, test_empty=acp_module(table='ACP_ONLY_REASONS = {"test_lists_the_session": ""}')
    )

    assert len(found) == 1
    assert "test_lists_the_session" in found[0]


def test_an_acp_only_scenario_with_a_stated_reason_passes(pytester: pytest.Pytester) -> None:
    table = 'ACP_ONLY_REASONS = {"test_lists_the_session": "only the protocol lists sessions"}'

    assert drifted(pytester, test_reasoned=acp_module(table=table)) == []


def test_a_claude_test_with_no_acp_sibling_is_not_named(pytester: pytest.Pytester) -> None:
    assert drifted(pytester, test_claude_only=BUILDS_ONE_TAGGED) == []


def test_a_parametrised_claude_test_with_no_acp_sibling_is_not_named(
    pytester: pytest.Pytester,
) -> None:
    claude_only = BOTH_RUNTIMES.replace("RUNTIME_PARAMS", "CLAUDE_CODE_PARAMS")

    assert drifted(pytester, test_claude_param=claude_only) == []


TWO_TAGS = f"""{HEADER}{SCRATCH_IMPORT}

@pytest.mark.runtime_acp
@pytest.mark.runtime_claude_code
def test_needs_both():
    pass
"""


def test_a_scenario_of_one_test_with_two_tags_is_refused_by_the_collection_and_the_pair_is_named(
    pytester: pytest.Pytester,
) -> None:
    pytester.syspathinsert(ROOT)
    refused = collect(pytester, test_two=TWO_TAGS)
    found = drifted(pytester, test_two=TWO_TAGS)

    assert refused.ret != 0
    assert "test_needs_both" in refused.stdout.str() + refused.stderr.str()
    assert len(found) == 1
    assert "test_needs_both" in found[0]
    assert "runtime_acp" in found[0]
    assert "runtime_claude_code" in found[0]
