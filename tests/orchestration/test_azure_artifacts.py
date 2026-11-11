"""The Azure Artifacts implementation: the shared conformance suite of `test_artifacts.py` run
over an in-memory fake of the blob clients (and, in `azurite` cases the ordinary run leaves out,
over Azurite), plus the cases only this implementation has."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from agent_build_kit import orchestration
from agent_build_kit.orchestration.artifacts import INTERFACE, Artifacts
from agent_build_kit.orchestration.azure.artifacts import AzureArtifacts, build_artifacts
from tests.conftest import make_installation
from tests.orchestration.blob_fakes import CONTAINER, FakeContainer, FakeService
from tests.orchestration.test_artifacts import (  # noqa: F401  (the conformance suite, collected here)
    test_a_key_reads_as_empty_once_a_writer_has_opened_it,
    test_a_missing_key_is_reported_as_missing_not_as_empty,
    test_a_text_value_holding_a_registered_secret_is_stored_redacted,
    test_a_value_put_under_a_key_is_got_back,
    test_a_writer_appends_to_what_an_earlier_writer_left,
    test_a_writers_flushed_lines_are_read_before_it_closes,
    test_a_writers_text_holding_a_registered_secret_is_stored_redacted,
    test_bytes_are_stored_unchanged,
    test_delete_removes_the_keys_under_the_prefix_and_keeps_the_rest,
    test_list_returns_the_keys_under_the_prefix_and_no_others,
)
from tests.redaction_fakes import known

NOW = datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)

# The connection string of an Azurite blob service; the `azurite` cases skip without it.
AZURITE_SETTING = "ABK_TEST_AZURITE_CONNECTION_STRING"


@pytest.fixture(autouse=True)
def active_redactor() -> Iterator[None]:
    with known():
        yield


@pytest.fixture(autouse=True)
def fresh_registry() -> Iterator[None]:
    orchestration.reset()
    yield
    orchestration.reset()


@pytest.fixture
def fake_azure_artifacts() -> AzureArtifacts:
    return AzureArtifacts(FakeContainer(), service=FakeService())


@pytest.fixture
def azurite_artifacts() -> Iterator[AzureArtifacts]:
    connection = os.environ.get(AZURITE_SETTING)
    if not connection:
        pytest.skip(f"{AZURITE_SETTING} is not set: no Azurite blob service to run against")
    blob = pytest.importorskip("azure.storage.blob")
    service = blob.BlobServiceClient.from_connection_string(connection)
    container = service.create_container(f"artifacts-{uuid.uuid4().hex}")
    try:
        yield AzureArtifacts(container, service=service)
    finally:
        container.delete_container()


@pytest.fixture(params=["azure-fake", pytest.param("azurite", marks=pytest.mark.azurite)])
def artifacts(request: pytest.FixtureRequest) -> Artifacts:
    """The implementation under test, which the conformance suite imported above runs over."""
    return request.getfixturevalue(
        {"azure-fake": "fake_azure_artifacts", "azurite": "azurite_artifacts"}[request.param]
    )


def test_a_writer_buffers_lines_and_appends_them_to_an_append_blob_in_one_block() -> None:
    container = FakeContainer()
    writer = AzureArtifacts(container, service=FakeService()).writer("transcripts/live.jsonl")

    for number in range(100):
        writer.write(f"line {number}\n")

    assert container.append_calls == []
    writer.flush()
    assert len(container.append_calls) == 1
    assert "transcripts/live.jsonl" in container.append_blobs
    writer.close()


def test_a_flush_larger_than_the_block_size_is_appended_in_blocks_no_larger_than_it() -> None:
    container = FakeContainer()
    artifacts = AzureArtifacts(container, service=FakeService(), block_size=16)
    writer = artifacts.writer("unit-logs/a.log")

    writer.write("x" * 50)
    writer.flush()

    assert all(len(data) <= 16 for _, data in container.append_calls)
    assert len(container.append_calls) > 1
    assert artifacts.get("unit-logs/a.log") == b"x" * 50
    writer.close()


def test_a_read_link_names_the_blob_reads_it_and_expires_after_the_given_time() -> None:
    service = FakeService()
    artifacts = AzureArtifacts(FakeContainer(), service=service, clock=lambda: NOW)

    link = urlparse(artifacts.read_link("unit-logs/a.log", expires_in=timedelta(minutes=15)))

    query = parse_qs(link.query)
    assert link.path == f"/{CONTAINER}/unit-logs/a.log"
    assert query["sp"] == ["r"]
    assert query["se"] == ["2030-01-01T12:15:00Z"]
    assert all(expiry >= NOW + timedelta(minutes=15) for _, expiry in service.key_requests)
    assert len(service.key_requests) == 1


def test_the_managed_identitys_client_id_from_the_deployment_is_the_credential_used(
    tmp_path: Path,
) -> None:
    installation = make_installation(
        tmp_path / "planning",
        deployment=dict(
            kind="azure",
            azure=dict(storage_account="stacct", identity_client_id="client-id-1"),
        ),
    )
    credentials: list[str | None] = []
    clients: list[tuple[str, object]] = []
    credential = object()

    def make_credential(client_id: str | None) -> object:
        credentials.append(client_id)
        return credential

    def make_clients(account_url: str, used: object) -> tuple[FakeContainer, FakeService]:
        clients.append((account_url, used))
        return FakeContainer(), FakeService()

    build_artifacts(installation, make_credential=make_credential, make_clients=make_clients)

    assert credentials == ["client-id-1"]
    assert clients == [("https://stacct.blob.core.windows.net", credential)]


def test_the_registry_finds_the_azure_implementation_for_an_azure_deployment(
    tmp_path: Path,
) -> None:
    installation = make_installation(
        tmp_path / "planning",
        deployment=dict(kind="azure", azure=dict(storage_account="stacct")),
    )

    assert orchestration.names(INTERFACE) == ["azure", "local"]
    assert isinstance(orchestration.get(INTERFACE, installation), AzureArtifacts)


def test_an_azure_deployment_without_a_storage_account_is_refused_before_any_client_is_built(
    tmp_path: Path,
) -> None:
    installation = make_installation(tmp_path / "planning", deployment=dict(kind="azure"))
    built: list[str] = []

    def make_credential(client_id: str | None) -> object:
        built.append("credential")
        return object()

    def make_clients(account_url: str, used: object) -> tuple[FakeContainer, FakeService]:
        built.append("clients")
        return FakeContainer(), FakeService()

    with pytest.raises(orchestration.Refused, match=r"deployment\.azure\.storage_account"):
        build_artifacts(installation, make_credential=make_credential, make_clients=make_clients)

    assert built == []


def test_a_second_writer_opened_on_a_key_keeps_what_the_first_appended() -> None:
    artifacts = AzureArtifacts(FakeContainer(), service=FakeService())
    first = artifacts.writer("unit-logs/a.log")
    first.write("one\n")
    first.flush()
    second = artifacts.writer("unit-logs/a.log")
    second.write("two\n")
    second.flush()

    assert artifacts.get("unit-logs/a.log") == b"one\ntwo\n"
    first.close()
    second.close()
