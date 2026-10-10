from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.replay.fake_upstream import FakeUpstream


@pytest.fixture
def upstream() -> Iterator[FakeUpstream]:
    with FakeUpstream() as fake:
        yield fake
