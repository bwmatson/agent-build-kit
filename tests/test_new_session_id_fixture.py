"""The `new_session_id` fixture: an id made for the test, a new one on every call."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest


@pytest.fixture
def first(new_session_id: Callable[[], str]) -> str:
    return new_session_id()


@pytest.fixture
def second(new_session_id: Callable[[], str]) -> str:
    return new_session_id()


def test_an_id_has_the_shape_of_a_session_id(first: str) -> None:
    assert str(uuid.UUID(first)) == first


def test_two_fixtures_backed_by_it_get_different_ids(first: str, second: str) -> None:
    assert first != second


def test_each_call_within_a_test_gives_another_id(new_session_id: Callable[[], str]) -> None:
    ids = {new_session_id() for _ in range(3)}

    assert len(ids) == 3
