"""The Azure Checkpoints implementation: the shared conformance suite of `test_checkpoints.py`
run against PostgreSQL in `azurite`-marked cases the ordinary run leaves out, plus the cases
only this implementation has, over a stand-in token source."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable, Iterator
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
def postgres_kwargs() -> Iterator[Callable[[], dict[str, Any]]]:
    """Connection arguments for a schema of its own in the database named by the setting."""
    dsn = os.environ.get(POSTGRES_SETTING)
    if not dsn:
        pytest.skip(f"{POSTGRES_SETTING} is not set: no PostgreSQL database to run against")
    psycopg = pytest.importorskip("psycopg")
    schema = f"checkpoints_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {schema}")
        try:
            yield lambda: dict(conninfo=dsn, options=f"-c search_path={schema}")
        finally:
            admin.execute(f"DROP SCHEMA {schema} CASCADE")


@pytest.fixture
def postgres_checkpoints(postgres_kwargs: Callable[[], dict[str, Any]]) -> AzureCheckpoints:
    return AzureCheckpoints(postgres_kwargs)


@pytest.fixture(params=[pytest.param("postgres", marks=pytest.mark.azurite)])
def checkpoints(request: pytest.FixtureRequest) -> Checkpoints:
    """The implementation under test, which the conformance suite imported above runs over."""
    return request.getfixturevalue("postgres_checkpoints")


@pytest.mark.azurite
def test_the_pool_asks_for_new_connection_arguments_once_for_each_connection_it_opens(
    postgres_kwargs: Callable[[], dict[str, Any]],
) -> None:
    calls: list[int] = []

    def counting() -> dict[str, Any]:
        calls.append(len(calls))
        return postgres_kwargs()

    async def run() -> tuple[int, int]:
        async with AzureCheckpoints(counting).open() as saver:
            pool: Any = saver.conn  # type: ignore[attr-defined]
            async with pool.connection(), pool.connection():
                pass
            return len(calls), pool.get_stats()["connections_num"]

    asked, opened = asyncio.run(run())

    assert asked == opened
    assert asked >= 2


def test_each_new_connection_takes_a_freshly_obtained_token_as_its_password() -> None:
    credential = FakeCredential()
    connection_kwargs = token_connection_kwargs(
        "db.example.test", credential, user="abk-identity", dbname="units"
    )

    found = [connection_kwargs() for _ in range(3)]

    assert [kwargs["password"] for kwargs in found] == ["token-1", "token-2", "token-3"]
    assert credential.scopes == [TOKEN_SCOPE] * 3
    assert {kwargs["host"] for kwargs in found} == {"db.example.test"}


def test_a_connection_opened_after_an_earlier_token_expired_uses_a_new_token() -> None:
    credential = FakeCredential()
    connection_kwargs = token_connection_kwargs("db.example.test", credential, user="abk-identity")
    first = connection_kwargs()

    credential.now += 3601  # the first token has expired
    later = connection_kwargs()

    assert (first["password"], later["password"]) == ("token-1", "token-2")


def test_the_connection_arguments_carry_the_deployments_database_role_and_name(
    tmp_path: Path,
) -> None:
    installation = make_installation(
        tmp_path / "planning",
        deployment=dict(
            kind="azure",
            azure=dict(
                database_host="db.example.test",
                database_user="abk-identity",
                database_name="units",
            ),
        ),
    )
    checkpoints = build_checkpoints(installation, make_credential=lambda _: FakeCredential())

    kwargs = checkpoints.connection_kwargs()

    assert (kwargs["host"], kwargs["user"], kwargs["dbname"]) == (
        "db.example.test",
        "abk-identity",
        "units",
    )


def test_the_database_name_defaults_to_postgres(tmp_path: Path) -> None:
    installation = make_installation(
        tmp_path / "planning",
        deployment=dict(
            kind="azure",
            azure=dict(database_host="db.example.test", database_user="abk-identity"),
        ),
    )

    kwargs = build_checkpoints(
        installation, make_credential=lambda _: FakeCredential()
    ).connection_kwargs()

    assert kwargs["dbname"] == "postgres"


def test_an_azure_deployment_without_a_database_user_is_refused_before_any_credential_is_built(
    tmp_path: Path,
) -> None:
    installation = make_installation(
        tmp_path / "planning",
        deployment=dict(kind="azure", azure=dict(database_host="db.example.test")),
    )
    built: list[str | None] = []

    def make_credential(client_id: str | None) -> Any:
        built.append(client_id)
        return FakeCredential()

    with pytest.raises(orchestration.Refused, match=r"deployment\.azure\.database_user"):
        build_checkpoints(installation, make_credential=make_credential)

    assert built == []


def test_the_managed_identitys_client_id_from_the_deployment_is_the_credential_used(
    tmp_path: Path,
) -> None:
    installation = make_installation(
        tmp_path / "planning",
        deployment=dict(
            kind="azure",
            azure=dict(
                database_host="db.example.test",
                database_user="abk-identity",
                identity_client_id="client-id-1",
            ),
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
        deployment=dict(
            kind="azure",
            azure=dict(database_host="db.example.test", database_user="abk-identity"),
        ),
    )

    assert orchestration.names(INTERFACE) == ["azure", "local"]
    assert isinstance(orchestration.get(INTERFACE, installation), AzureCheckpoints)
