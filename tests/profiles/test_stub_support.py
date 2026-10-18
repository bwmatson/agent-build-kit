"""A profile declares whether it supports stubs, and a profile that says nothing does not
(spec: test-stubs)."""

from __future__ import annotations

from agent_build_kit import profiles
from agent_build_kit.profiles.base import supports_stubs


class Silent:
    """A profile object that declares nothing about stubs."""

    name = "silent"


class Declines:
    name = "declines"
    supports_stubs = False


class Declares:
    name = "declares"
    supports_stubs = True


def test_the_built_in_profiles_support_stubs() -> None:
    assert supports_stubs(profiles.get("python-uv"))
    assert supports_stubs(profiles.get("node-npm"))


def test_a_profile_that_declares_nothing_does_not_support_stubs() -> None:
    assert supports_stubs(Declares()) is True
    assert supports_stubs(Silent()) is False


def test_a_profile_that_says_false_does_not_support_stubs() -> None:
    assert supports_stubs(Declares()) is True
    assert supports_stubs(Declines()) is False
