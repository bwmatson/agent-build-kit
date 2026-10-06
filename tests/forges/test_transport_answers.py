"""Answers that are not the expected one are errors, not empty results."""

from __future__ import annotations

import httpx
import pytest

from agent_build_kit.forges.transport import (
    AuthError,
    Credentials,
    HostError,
    NotFound,
    Transport,
    TransportError,
)
from tests.forges.mock_host import MockHost, recorded, sign_in_page

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
    host = MockHost(recorded("repo_404"))

    with pytest.raises(NotFound) as caught:
        transport(host).request("GET", "/repos/example/app")

    assert caught.value.account == "example"
    assert "example" in str(caught.value)
    assert len(host.requests) == 1


@pytest.mark.parametrize("answer", ["bad_credentials_401", "bad_credentials_403"])
def test_a_refusal_is_an_authentication_error(answer: str) -> None:
    host = MockHost(recorded(answer))

    with pytest.raises(AuthError):
        transport(host).request("GET", "/repos/example/app")


ENV_CREDENTIALS = Credentials(scheme="Bearer", token="tok-env", source="GH_TOKEN", owner="example")


def env_transport(host: MockHost) -> Transport:
    return Transport(
        "https://api.example.test",
        ENV_CREDENTIALS,
        transport=host,
        retries=0,
        sleep=lambda _: None,
    )


def test_a_not_found_names_the_credential_source_as_well_as_the_owner() -> None:
    host = MockHost(recorded("repo_404"))

    with pytest.raises(NotFound) as caught:
        env_transport(host).request("GET", "/repos/other/app")

    assert "GH_TOKEN" in str(caught.value)
    assert "example" in str(caught.value)
    assert caught.value.source == "GH_TOKEN"
    assert caught.value.account == "example"


@pytest.mark.parametrize("answer", ["bad_credentials_401", "bad_credentials_403"])
def test_a_refusal_names_the_credential_source_as_well_as_the_owner(answer: str) -> None:
    host = MockHost(recorded(answer))

    with pytest.raises(AuthError) as caught:
        env_transport(host).request("GET", "/repos/other/app")

    assert "GH_TOKEN" in str(caught.value)
    assert "example" in str(caught.value)


def test_a_truncated_json_body_is_a_transport_error() -> None:
    host = MockHost(
        httpx.Response(200, content='{"trunc', headers={"content-type": "application/json"})
    )

    with pytest.raises(TransportError) as caught:
        transport(host).request("GET", "/user")

    assert isinstance(caught.value, HostError)
    assert '{"trunc' in str(caught.value)
