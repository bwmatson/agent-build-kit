"""The orchestration registry: an interface's implementation is found for the deployment.

Laid out like the forge registry. A cloud deployment must never run on local state by
accident, so a lookup that cannot be met is refused with the names involved.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import orchestration
from agent_build_kit.installation import Installation
from tests.conftest import make_installation

CHILD_MODULES = Path(__file__).parents[1] / "child_modules" / "orchestration"


@pytest.fixture(autouse=True)
def fresh_registry() -> Iterator[None]:
    orchestration.reset()
    yield
    orchestration.reset()


def installation_of(tmp_path: Path, kind: str) -> Installation:
    return make_installation(tmp_path / "planning", deployment=dict(kind=kind))


def test_an_implementation_registered_for_local_is_returned_to_a_local_installation(
    tmp_path: Path,
) -> None:
    built = object()
    orchestration.register("store", "local", lambda installation: built)

    assert orchestration.get("store", installation_of(tmp_path, "local")) is built


def test_a_factory_receives_the_installation(tmp_path: Path) -> None:
    installation = installation_of(tmp_path, "local")
    orchestration.register("store", "local", lambda inst: inst)

    assert orchestration.get("store", installation) is installation


def test_an_azure_installation_is_refused_an_interface_with_only_a_local_implementation(
    tmp_path: Path,
) -> None:
    orchestration.register("store", "local", lambda installation: object())

    with pytest.raises(orchestration.Refused) as caught:
        orchestration.get("store", installation_of(tmp_path, "azure"))

    message = str(caught.value)
    assert "store" in message
    assert "azure" in message
    assert "local" in message


def test_the_kinds_registered_for_an_interface_are_listed() -> None:
    orchestration.register("store", "local", lambda installation: object())
    orchestration.register("store", "azure", lambda installation: object())

    assert orchestration.names("store") == ["azure", "local"]


def test_the_built_in_registrations_load_on_the_first_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(CHILD_MODULES))
    monkeypatch.setattr(orchestration, "BUILTIN_MODULES", ("builtin_example_impls",))

    assert orchestration.get("store", installation_of(tmp_path, "local")) == "built-in"


def test_an_sdk_that_cannot_be_imported_is_refused_naming_the_extra_and_the_install_command() -> (
    None
):
    with pytest.raises(orchestration.Refused) as caught:
        orchestration.import_sdk("azure", "azure_sdk_that_is_not_installed")

    message = str(caught.value)
    assert "azure" in message
    assert "agent-build-kit[azure]" in message
    assert "install" in message


def test_an_azure_implementation_whose_sdk_is_missing_is_refused_when_it_is_looked_up(
    tmp_path: Path,
) -> None:
    def factory(installation: Installation) -> object:
        return orchestration.import_sdk("azure", "azure_sdk_that_is_not_installed")

    orchestration.register("store", "azure", factory)

    with pytest.raises(orchestration.Refused) as caught:
        orchestration.get("store", installation_of(tmp_path, "azure"))

    assert "agent-build-kit[azure]" in str(caught.value)


def test_looking_up_a_local_implementation_imports_no_azure_module(tmp_path: Path) -> None:
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            str(CHILD_MODULES / "lookup_without_azure.py"),
            str(tmp_path / "planning"),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"


def test_an_sdk_that_is_installed_but_fails_on_a_dependency_is_not_reported_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(CHILD_MODULES))

    with pytest.raises(ModuleNotFoundError) as caught:
        orchestration.import_sdk("azure", "broken_sdk")

    assert caught.value.name == "azure_dependency_that_is_not_installed"
