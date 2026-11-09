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

NO_AZURE_IMPORTED = """
import sys
from pathlib import Path
from agent_build_kit import orchestration
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.installation import Installation

root = Path(sys.argv[1])
root.mkdir(parents=True, exist_ok=True)
installation = Installation(WorkspaceConfig.model_validate(dict(repos=dict())), root)
orchestration.register("store", "local", lambda inst: "local")
assert orchestration.get("store", installation) == "local"
print(sorted(m for m in sys.modules if m.split(".")[0] == "azure"))
"""

BUILTIN_MODULE = """
from agent_build_kit import orchestration

orchestration.register("store", "local", lambda installation: "built-in")
"""


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
    module = tmp_path / "plugins" / "builtin_example_impls.py"
    module.parent.mkdir()
    module.write_text(BUILTIN_MODULE)
    monkeypatch.syspath_prepend(str(module.parent))
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
        [sys.executable, "-I", "-c", NO_AZURE_IMPORTED, str(tmp_path / "planning")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"
