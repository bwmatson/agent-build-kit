"""The `new_session_id` fixture: an id made for the test, a new one on every call."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest

seen: set[str] = set()


@pytest.mark.parametrize("case", range(4))
def test_each_test_gets_an_id_no_other_test_in_the_process_had(
    case: int, new_session_id: Callable[[], str]
) -> None:
    session_id = new_session_id()

    assert str(uuid.UUID(session_id)) == session_id
    assert session_id not in seen
    seen.add(session_id)


def test_each_call_within_a_test_gives_another_id(new_session_id: Callable[[], str]) -> None:
    ids = {new_session_id() for _ in range(3)}

    assert len(ids) == 3
