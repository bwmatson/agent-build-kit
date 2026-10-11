"""Replacing known secret values, and token-shaped strings, in text."""

from __future__ import annotations

from agent_build_kit.redaction import Redactor

KEY = "k3y-value-0001"
OTHER = "0th3r-value-02"


def test_an_exact_value_becomes_its_name_and_nothing_of_the_value_stays() -> None:
    out = Redactor({"API_KEY": KEY}).redact(f"failed with {KEY} at step 3")

    assert out == "failed with [redacted:API_KEY] at step 3"


def test_matching_is_case_sensitive() -> None:
    text = f"seen {KEY.upper()}"

    assert Redactor({"API_KEY": KEY}).redact(text) == text


def test_a_value_inside_a_url_or_after_bearer_keeps_the_rest_of_the_string() -> None:
    redactor = Redactor({"API_KEY": KEY})

    assert (
        redactor.redact(f"https://host.example/path?key={KEY}&x=1")
        == "https://host.example/path?key=[redacted:API_KEY]&x=1"
    )
    assert (
        redactor.redact(f"Authorization: Bearer {KEY}")
        == "Authorization: Bearer [redacted:API_KEY]"
    )


def test_two_secrets_in_one_string_one_of_them_twice_are_each_named() -> None:
    out = Redactor({"API_KEY": KEY, "OTHER": OTHER}).redact(f"{KEY} {OTHER} {KEY}")

    assert out == "[redacted:API_KEY] [redacted:OTHER] [redacted:API_KEY]"


def test_a_value_that_contains_another_is_replaced_whole() -> None:
    longer = KEY + "-and-more"

    out = Redactor({"SHORT": KEY, "LONG": longer}).redact(f"a {longer} b")

    assert out == "a [redacted:LONG] b"


def test_a_value_of_seven_characters_is_left_alone_and_one_of_eight_is_replaced() -> None:
    redactor = Redactor({"SEVEN": "abcdefg", "EIGHT": "abcdefgh"})

    assert redactor.redact("abcdefg") == "abcdefg"
    assert redactor.redact("abcdefgh") == "[redacted:EIGHT]"


def test_a_value_of_true_is_left_alone() -> None:
    assert Redactor({"FLAG": "true"}).redact("debug is true") == "debug is true"


def test_a_token_shape_the_set_does_not_hold_is_replaced() -> None:
    redactor = Redactor({})
    shapes = [
        "sk-" + "a1B2c3D4e5F6g7H8i9J0k1",
        "ghp_" + "A" * 36,
        "github_pat_" + "a1B2c3D4e5F6g7H8i9J0k1",
    ]

    for shape in shapes:
        assert redactor.redact(f"token {shape} end") == "token [redacted:token-shape] end"


def test_a_value_in_the_set_is_named_not_shaped() -> None:
    held = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1"

    assert Redactor({"GATEWAY": held}).redact(held) == "[redacted:GATEWAY]"


def test_a_plain_string_of_52_characters_is_untouched() -> None:
    plain = "a1b2c3d4e5" * 5 + "f6"
    assert len(plain) == 52

    assert Redactor({}).redact(f"pat {plain}") == f"pat {plain}"
