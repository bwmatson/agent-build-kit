"""`abk doctor`'s deployment section (spec: deployment-selection)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from agent_build_kit.cli.doctor import Check, run_doctor
from tests.cli.in_repo_doctor import in_repo, named
from tests.cli.public_content_repo import said
from tests.cli.test_doctor import Answers
from tests.factories import which_all

SECTION = "deployment"
SETTINGS = {
    "subscription": "sub-1",
    "resource_group": "rg-1",
    "storage_account": "store1",
    "database_host": "db.example.test",
    "key_vault": "vault1",
    "identity_client_id": "client-1",
}


class Token:
    token = "t"


class Credential:
    """An Azure credential as doctor reads it: a token for a scope, or an error."""

    def __init__(self, *, fail: str | None = None) -> None:
        self.fail = fail

    def get_token(self, *scopes: str) -> Token:
        if self.fail:
            raise RuntimeError(self.fail)
        return Token()


def azure(root: Path, *, overlay: dict[str, str]) -> Path:
    """An installation whose committed file says `azure`, with `overlay` as its settings."""
    config = in_repo(root)
    data = yaml.safe_load(config.read_text())
    data["deployment"] = {"kind": "azure"}
    config.write_text(yaml.safe_dump(data))
    (root / "abk.local.yaml").write_text(yaml.safe_dump({"deployment": {"azure": overlay}}))
    return config


def section(config: Path, credential: Credential | None = None) -> list[Check]:
    checks = run_doctor(
        config,
        run=Answers(),
        which=which_all,
        azure_credential=lambda client_id: credential or Credential(),
    )
    return named(checks, SECTION)


@pytest.fixture
def extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `azure` extra, installed: a module for the SDK's import."""
    monkeypatch.setitem(sys.modules, "azure.identity", ModuleType("azure.identity"))


def test_a_local_deployment_lists_the_state_checks_in_its_section(tmp_path: Path) -> None:
    config = in_repo(tmp_path / "app")

    checks = run_doctor(config, run=Answers(), which=which_all)

    found = named(checks, SECTION)
    assert any("state location" in c.name for c in found)
    assert any("local dir" in c.name for c in found)
    assert not any("azure" in said(c).lower() for c in found)


def test_an_azure_deployment_fails_when_the_extra_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "azure.identity", None)
    config = azure(tmp_path / "app", overlay=SETTINGS)

    failed = [c for c in section(config) if c.status == "FAIL"]

    assert len(failed) == 1
    assert "azure" in failed[0].detail
    assert failed[0].fix


@pytest.mark.usefixtures("extra")
@pytest.mark.parametrize("setting", sorted(SETTINGS))
def test_an_azure_deployment_fails_naming_a_missing_overlay_setting(
    tmp_path: Path, setting: str
) -> None:
    config = azure(tmp_path / "app", overlay={k: v for k, v in SETTINGS.items() if k != setting})

    failed = [c for c in section(config) if c.status == "FAIL"]

    assert [setting in said(c) for c in failed] == [True]
    assert "abk.local.yaml" in said(failed[0])
    assert failed[0].fix


@pytest.mark.usefixtures("extra")
def test_an_azure_deployment_fails_naming_the_identity_and_reason_when_no_token(
    tmp_path: Path,
) -> None:
    config = azure(tmp_path / "app", overlay=SETTINGS)

    found = section(config, Credential(fail="no managed identity"))

    failed = [c for c in found if c.status == "FAIL"]
    assert len(failed) == 1
    assert "client-1" in failed[0].detail
    assert "no managed identity" in failed[0].detail
    assert failed[0].fix


@pytest.mark.usefixtures("extra")
def test_an_azure_deployment_with_everything_in_place_passes_each_check(tmp_path: Path) -> None:
    config = azure(tmp_path / "app", overlay=SETTINGS)

    found = [c for c in section(config) if "azure" in c.name]

    assert {c.name: c.status for c in found} == {
        "deployment: azure extra": "ok",
        "deployment: azure credential": "ok",
    }
