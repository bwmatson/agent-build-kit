"""A test that scans the whole repository is an integration test, so the default unit run skips it.

Such a scan reads every test file; alone it takes seconds and under parallel load it is the test
that runs past its time limit (`test_live_modules_are_found` took 10 to 24 seconds, loaded).
Add a scan here when it is found; CI's `integration` check still runs it before a merge.
"""

from __future__ import annotations

import pytest

from tests.tracked_files import ROOT

WIDE_SCANS = [
    (
        "test_live_modules_are_found.py",
        "test_every_module_the_old_glob_and_text_match_found_is_still_found",
    ),
]


@pytest.mark.parametrize(("module", "name"), WIDE_SCANS)
def test_a_test_that_scans_the_whole_repository_is_an_integration_test(
    pytester: pytest.Pytester, module: str, name: str
) -> None:
    items, _ = pytester.inline_genitems(str(ROOT / "tests" / module))
    item = next(i for i in items if i.name == name)

    assert item.get_closest_marker("integration") is not None
