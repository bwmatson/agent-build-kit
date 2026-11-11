"""The Azure Checkpoints implementation: the shared conformance suite of `test_checkpoints.py`
run against PostgreSQL in `azurite`-marked cases the ordinary run leaves out, plus the cases
only this implementation has, over a stand-in token source."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from agent_build_kit import orchestration
from agent_build_kit.orchestration.azure.checkpoints import (
    TOKEN_SCOPE,
    AzureCheckpoints,
    build_checkpoints,
    token_connection_kwargs,
)
from agent_build_kit.orchestration.checkpoints import INTERFACE, Checkpoints
from tests.conftest import make_installation
from tests.orchestration.test_checkpoints import (  # noqa: F401  (the conformance suite, collected here)
    test_a_checkpoint_written_is_read_back,
    test_a_stored_type_outside_the_allowlist_is_not_deserialised,
    test_a_threads_checkpoints_are_listed_newest_first,
)

# The connection string of a PostgreSQL database; the `azurite` cases skip without it.
POSTGRES_SETTING = "ABK_TEST_POSTGRES_CONNECTION_STRING"


class IssuedToken(NamedTuple):
    """The shape `azure.identity` credentials return from `get_token`."""

    token: str
    expires_on: int


class FakeCredential:
    """A credential that issues a numbered token valid for an hour from its clock."""

    def __init__(self) -> None:
        self.now = 1_900_000_000
        self.scopes: list[str] = []

    def get_token(self, *scopes: str) -> IssuedToken:
        self.scopes.extend(scopes)
        return IssuedToken(f"token-{len(self.scopes)}", self.now + 3600)


@pytest.fixture(autouse=True)
def fresh_registry() -> Iterator[None]:
    orchestration.reset()
    yield
    orchestration.reset()


@pytest.fixture
def postgres_checkpoints() -> Iterator[AzureCheckpoints]:
    dsn = os.environ.get(POSTGRES_SETTING)
    if not dsn:
        pytest.skip(f"{POSTGRES_SETTING} is not set: no PostgreSQL database to run against")
    psycopg = pytest.importorskip("psycopg")
    schema = f"checkpoints_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {schema}")
        try:
            yield AzureCheckpoints(lambda: dict(conninfo=dsn, options=f"-c search_path={schema}"))
        finally:
            admin.execute(f"DROP SCHEMA {schema} CASCADE")


@pytest.fixture(params=[pytest.param("postgres", marks=pytest.mark.azurite)])
def checkpoints(request: pytest.FixtureRequest) -> Checkpoints:
    """The implementation under test, which the conformance suite imported above runs over."""
    return request.getfixturevalue("postgres_checkpoints")


def test_each_new_connection_takes_a_freshly_obtained_token_as_its_password() -> None:
    credential = FakeCredential()
    connection_kwargs = token_connection_kwargs("db.example.test", credential)

    passwords = [connection_kwargs()["password"] for _ in range(3)]

    assert passwords == ["token-1", "token-2", "token-3"]
    assert credential.scopes == [TOKEN_SCOPE] * 3


def test_a_connection_opened_after_an_earlier_token_expired_uses_a_new_token() -> None:
    credential = FakeCredential()
    connection_kwargs = token_connection_kwargs("db.example.test", credential)
    first = connection_kwargs()
    expired_at = credential.now + 3600

    credential.now = expired_at + 1
    later = connection_kwargs()

    assert first["password"] == "token-1"
    assert later["password"] == "token-2"
    assert later["host"] == "db.example.test"


def test_the_managed_identitys_client_id_from_the_deployment_is_the_credential_used(
    tmp_path: Path,
) -> None:
    installation = make_installation(
        tmp_path / "planning",
        deployment=dict(
            kind="azure",
            azure=dict(database_host="db.example.test", identity_client_id="client-id-1"),
        ),
    )
    credentials: list[str | None] = []

    def make_credential(client_id: str | None) -> Any:
        credentials.append(client_id)
        return FakeCredential()

    build_checkpoints(installation, make_credential=make_credential)

    assert credentials == ["client-id-1"]


def test_an_azure_deployment_without_a_database_host_is_refused_before_any_credential_is_built(
    tmp_path: Path,
) -> None:
    installation = make_installation(tmp_path / "planning", deployment=dict(kind="azure"))
    built: list[str | None] = []

    def make_credential(client_id: str | None) -> Any:
        built.append(client_id)
        return FakeCredential()

    with pytest.raises(orchestration.Refused, match=r"deployment\.azure\.database_host"):
        build_checkpoints(installation, make_credential=make_credential)

    assert built == []


def test_the_registry_finds_the_azure_implementation_for_an_azure_deployment(
    tmp_path: Path,
) -> None:
    installation = make_installation(
        tmp_path / "planning",
        deployment=dict(kind="azure", azure=dict(database_host="db.example.test")),
    )

    assert orchestration.names(INTERFACE) == ["azure", "local"]
    assert isinstance(orchestration.get(INTERFACE, installation), AzureCheckpoints)
