"""No test reaches Azure DevOps through the registered forge.

The registered forge is built with the network as its transport, so a caller that
asks `forges.get("azure_devops")` would read `dev.azure.com`, for up to the forge
timeout a read. The suite registers a stand-in host for every test, as it does for GitHub.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest

from agent_build_kit import forges
from agent_build_kit.cli.doctor import run_doctor
from agent_build_kit.config import dump
from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from tests.conftest import make_installation


def test_the_registered_azure_devops_forge_has_a_stand_in_host() -> None:
    forge = forges.get("azure_devops")

    assert isinstance(forge, AzureDevOpsForge)
    assert forge.http is not None


def test_the_doctor_checks_an_azure_devops_repo_without_reaching_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sends: list[httpx.Request] = []

    def refuse(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        sends.append(request)
        raise AssertionError("a test reached the network")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    inst = make_installation(
        tmp_path / "planning",
        repos={
            "azure": {
                "path": str(tmp_path / "azure"),
                "forge": "azure_devops",
                "azure_devops": {"org": "acme", "project": "Proj", "repo": "azure"},
            }
        },
    )
    (inst.root / "abk.yaml").write_text(dump(inst.config))

    def answer_all(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, "enabled\n", "")

    checks = run_doctor(
        inst.root / "abk.yaml",
        run=answer_all,
        which=lambda tool, path=None: f"/usr/bin/{tool}",
        units=tmp_path / "units",
    )

    names = {check.name for check in checks}
    assert "forge azure" in names
    assert "merge guard azure" in names
    assert sends == [], "a test reached the network"
