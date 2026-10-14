"""The node-npm profile recognises test files by naming (spec: node-npm-lint-and-test)."""

from __future__ import annotations

import pytest

from agent_build_kit import profiles

EXTENSIONS = ("ts", "tsx", "js", "jsx", "mts")


@pytest.fixture
def profile():
    return profiles.get("node-npm")


def classified(profile, template: str) -> dict[str, bool]:
    paths = [template.format(ext=ext) for ext in EXTENSIONS]
    return {path: profile.is_test_path(path) for path in paths}


def test_a_dot_test_file_is_a_test_path_in_every_source_extension(profile) -> None:
    assert all(classified(profile, "src/a.test.{ext}").values()), classified(
        profile, "src/a.test.{ext}"
    )


def test_a_dot_spec_file_is_a_test_path_in_every_source_extension(profile) -> None:
    assert all(classified(profile, "src/a.spec.{ext}").values()), classified(
        profile, "src/a.spec.{ext}"
    )


def test_a_file_under_a_tests_directory_is_a_test_path_and_a_plain_source_file_is_not(
    profile,
) -> None:
    in_tests = classified(profile, "src/__tests__/a.{ext}")
    plain = classified(profile, "src/a.{ext}")

    assert all(in_tests.values()), in_tests
    assert not any(plain.values()), plain
    # Together with the naming rules above: the three shapes the spec names.
    assert profile.is_test_path("src/a.test.ts")
    assert profile.is_test_path("src/a.spec.tsx")
    assert profile.is_test_path("src/__tests__/a.ts")
    assert not profile.is_test_path("src/a.ts")
