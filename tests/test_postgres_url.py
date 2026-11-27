"""The test-store URL helper never reaches the real store's database."""

from __future__ import annotations

import pytest

from tests.support.postgres_url import (
    TestStoreIsTheRealStore,
    TestStoreNotConfigured,
    postgres_url,
)

TEST = {
    "ABK_TEST_STORE_HOST": "db.example",
    "ABK_TEST_STORE_USER": "tester",
    "ABK_TEST_STORE_DATABASE": "abk_test",
}


@pytest.mark.parametrize(
    ("environ", "error"),
    [
        pytest.param(
            {k: v for k, v in TEST.items() if k != "ABK_TEST_STORE_DATABASE"}
            | {"ABK_STORE_DATABASE": "abk"},
            TestStoreNotConfigured,
            id="the-database-never-falls-back",
        ),
        pytest.param(
            TEST | {"ABK_STORE_URL": "postgresql://u:p@db.example:5432/abk_test"},
            TestStoreIsTheRealStore,
            id="the-same-server-port-and-database-as-the-store-url",
        ),
        pytest.param(
            TEST | {"ABK_STORE_HOST": "db.example", "ABK_STORE_DATABASE": "abk_test"},
            TestStoreIsTheRealStore,
            id="the-same-server-port-and-database-as-the-store-parts",
        ),
    ],
)
def test_an_unsafe_test_store_is_refused(environ: dict[str, str], error: type[Exception]) -> None:
    with pytest.raises(error):
        postgres_url(environ)


def test_the_host_falls_back_to_the_stores_own() -> None:
    environ = {k: v for k, v in TEST.items() if k != "ABK_TEST_STORE_HOST"} | {
        "ABK_STORE_HOST": "fallback.example"
    }

    assert "fallback.example" in postgres_url(environ)
