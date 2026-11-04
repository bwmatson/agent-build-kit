"""A test that takes only the tick pass's builder, and runs no pass, keeps the default limit."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.tick_pass import Builder, install_builder
from tests.time_limit import DEFAULT_TEST_TIME_LIMIT, limit_for


def test_a_test_that_only_installs_the_builder_keeps_the_default_limit(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert isinstance(install_builder(tmp_path, monkeypatch), Builder)
    assert limit_for(request.node) == DEFAULT_TEST_TIME_LIMIT
