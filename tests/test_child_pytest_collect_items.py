"""`collect_items` collects repository modules in-process and fails with the collection's report."""

from __future__ import annotations

import pytest

from tests.child_pytest import collect_items
from tests.time_limit import LOADED_TEST_TIME_LIMIT, limit_for


def test_a_test_whose_module_takes_collect_items_gets_the_loaded_limit(
    request: pytest.FixtureRequest,
) -> None:
    assert callable(collect_items)
    assert limit_for(request.node) == LOADED_TEST_TIME_LIMIT


def test_a_module_that_fails_to_import_fails_the_test_with_the_collection_report(
    pytester: pytest.Pytester,
) -> None:
    pytester.copy_example("collect_items")

    with pytest.raises(pytest.fail.Exception) as raised:
        collect_items(pytester, pytester.path / "broken.py")

    assert "no_such_module_xyz" in str(raised.value)
    assert "broken.py" in str(raised.value)


def test_a_clean_module_returns_its_items(pytester: pytest.Pytester) -> None:
    pytester.copy_example("collect_items")

    items = collect_items(pytester, pytester.path / "clean.py")

    assert [i.name for i in items] == ["test_a", "test_b"]
