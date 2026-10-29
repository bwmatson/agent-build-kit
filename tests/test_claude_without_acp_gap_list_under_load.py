"""The gap-list test gives the same result however loaded the host is.

The test collects every live module of the kit in-process, which under parallel load takes
longer than the default per-test time limit, so the limit interrupts it at random. It is judged
here on the limit it runs under, not on how long a host took to collect.
"""

from __future__ import annotations

import pytest

from tests.runtime_tag_collection import ROOT
from tests.time_limit import DEFAULT_TEST_TIME_LIMIT, limit_for

MODULE = ROOT / "tests" / "test_claude_without_acp_gap_list.py"
KITS_LIST = "test_the_kits_current_list_matches_the_documents_without_a_warning"
HEADROOM = 4  # a loaded host collects the live modules several times slower than an idle one


def test_the_test_that_collects_every_live_module_has_a_limit_beyond_a_loaded_collection(
    pytester: pytest.Pytester,
) -> None:
    items, _ = pytester.inline_genitems(str(MODULE))
    item = next(i for i in items if i.name == KITS_LIST)

    assert limit_for(item) >= DEFAULT_TEST_TIME_LIMIT * HEADROOM
