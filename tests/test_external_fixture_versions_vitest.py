"""The Vitest recordings name the version they came from, and the guard fails when the
installed major is ahead of it (spec: node-npm-lint-and-test)."""

import pytest

from tests.test_external_fixture_versions import assert_vitest_recordings_current


def test_a_recording_made_with_an_older_major_than_the_installed_one_fails_the_guard() -> None:
    with pytest.raises(AssertionError) as raised:
        assert_vitest_recordings_current(99)

    message = str(raised.value)
    assert "vitest" in message
    assert "99" in message
    assert "3" in message
    assert "record_vitest.py" in message


def test_recordings_of_the_installed_major_pass_the_guard() -> None:
    assert_vitest_recordings_current(3)
