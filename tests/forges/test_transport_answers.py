"""Answers that are not the expected one are errors, not empty results."""

from __future__ import annotations

import pytest

from agent_build_kit.forges.transport import AuthError, Credentials, NotFound, Transport
from tests.forges.mock_host import MockHost, failure, sign_in_page

CREDENTIALS = Credentials(scheme="Bearer", token="tok-example", source="setting", owner="example")


def transport(host: MockHost) -> Transport:
    return Transport(
        "https://api.example.test",
        CREDENTIALS,
        transport=host,
        timeout=7.0,
        retries=1,
        sleep=lambda _: None,
    )


def test_a_sign_in_page_with_a_200_is_an_authentication_error() -> None:
    host = MockHost(sign_in_page())

    with pytest.raises(AuthError) as caught:
        transport(host).request("GET", "/repos/example/app")

    assert "<!DOCTYPE html>" in str(caught.value)
    assert len(host.requests) == 1


def test_a_not_found_names_the_account_used() -> None:
    host = MockHost(failure(404, "Not Found"))

    with pytest.raises(NotFound) as caught:
        transport(host).request("GET", "/repos/example/app")

    assert caught.value.account == "example"
    assert "example" in str(caught.value)
    assert len(host.requests) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_a_refusal_is_an_authentication_error(status: int) -> None:
    host = MockHost(failure(status, "Bad credentials"))

    with pytest.raises(AuthError):
        transport(host).request("GET", "/repos/example/app")
