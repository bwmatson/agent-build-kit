"""A test that scans the whole repository is an integration test, so the default unit run skips it.

Such a scan reads every test file; alone it takes seconds and under parallel load it is the test
that runs past its time limit. CI's `integration` check still runs it before a merge.

A scan is found by its syntax (`tests/wide_scans.py`, its cases are the specification table in
`tests/test_wide_scans.py`) and fails the check below unless the baseline names it; the baseline
may only shrink.
"""

from __future__ import annotations

import pytest

from tests.time_limit import LOADED_TEST_TIME_LIMIT
from tests.tracked_files import test_trees
from tests.wide_scans import check_tests, load_baseline


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
@pytest.mark.integration
def test_no_test_of_the_repository_scans_it_without_the_integration_selector() -> None:
    modules = [path for tree in test_trees() for path in tree.rglob("test_*.py")]

    assert len(modules) > 0
    assert check_tests(baseline=load_baseline()) == []
