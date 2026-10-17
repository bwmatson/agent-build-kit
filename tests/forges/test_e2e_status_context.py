"""A unit's e2e-test result is posted as the commit status `local/e2e-test`, on both hosts.

The unit goes through the runner with the real e2e session, whose lock is the installation's,
and the real adapters over their HTTP stand-ins. Only a unit of the `e2e-test` kind posts a
status, takes the lock or reads an `e2e_*` setting: a unit of the `integration-test` kind is a
unit-test there.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import Forge, RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.transport import clear_credentials
from agent_build_kit.installation import Installation
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.wiring import E2eSession, build_post_status
from agent_build_kit.settings import settings
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost
from tests.forges.github_host import HOSTS, GitHubHost, answer
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import fresh


@pytest.fixture(autouse=True)
def credentials(installation: Installation, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Both hosts have a token. The runner shells out to git, so unlike the adapter tests
    this one does not refuse a subprocess."""
    monkeypatch.setattr(settings, "gh_token", "gh-secret")
    monkeypatch.setattr(settings, "ado_pat", "pat-secret")
    clear_credentials()
    yield
    clear_credentials()
    HOSTS.clear()


SHA = "abc1234def"
GITHUB_REPO = RepoId(forge="github", account="example", name="app")
AZURE_REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")

Hosted = tuple[Forge, RepoId, Callable[[], list[str]]]


def github() -> Hosted:
    status = ("POST", f"/repos/example/app/statuses/{SHA}")
    host = GitHubHost(routes={status: answer({"id": 1, "state": "success"}, 201)})

    def contexts() -> list[str]:
        return [call.body["context"] for call in host.calls(*status)]

    return GitHubForge(http=host), GITHUB_REPO, contexts


def azure() -> Hosted:
    host = RestHost(azure_answers.OPEN)

    def contexts() -> list[str]:
        return [
            f"{w.body['context']['genre']}/{w.body['context']['name']}"
            for w in host.writes()
            if w.route.startswith("commits/")
        ]

    return AzureDevOpsForge(http=host), AZURE_REPO, contexts


def refusing(name: str) -> Callable[..., Any]:
    def called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"a unit that is not e2e-test reached {name}")

    return called


def run_unit(tmp_path: Path, installation: Installation, kind: TestTier, hosted: Hosted) -> None:
    forge, repo, _ = hosted
    recorder = fresh(tmp_path, tier=kind.value)
    (tmp_path / "tree" / "scripts").mkdir(parents=True)
    (tmp_path / "tree" / "scripts" / "dev-stack.sh").write_text("#!/bin/sh\n")

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "5 passed in 1.00s", "")

    session = E2eSession(
        recorder.store.get("add-marker/1"),
        lock=installation.e2e_lock,
        timeout=5,
        run=run,
        sha=lambda cwd: SHA,
        status=build_post_status(for_repo=lambda name: (forge, repo)),
    )
    # The e2e_* settings are read through the splits, the gate and the scope of the run.
    settings: dict[str, Any] = (
        {}
        if kind == TestTier.E2E_TEST
        else {name: refusing(name) for name in ("on_e2e_gate", "e2e_splits", "e2e_runs_whole")}
    )
    build(
        tmp_path,
        recorder,
        run_e2e=session.run,
        post_status=session.post,
        head=lambda cwd: SHA,
        **settings,
    )


@pytest.mark.parametrize("make", [github, azure], ids=["github", "azure-devops"])
def test_an_e2e_test_unit_posts_local_e2e_test_and_holds_the_e2e_lock(
    make: Callable[[], Hosted], tmp_path: Path, installation: Installation
) -> None:
    hosted = make()

    run_unit(tmp_path, installation, TestTier.E2E_TEST, hosted)

    assert hosted[2]() == ["local/e2e-test"]
    assert installation.e2e_lock.name == "e2e.lock"
    assert installation.e2e_lock.exists()


@pytest.mark.parametrize("make", [github, azure], ids=["github", "azure-devops"])
def test_an_integration_test_unit_posts_no_status_and_takes_no_lock_or_setting(
    make: Callable[[], Hosted], tmp_path: Path, installation: Installation
) -> None:
    hosted = make()

    run_unit(tmp_path, installation, TestTier.INTEGRATION_TEST, hosted)

    assert hosted[2]() == []
    assert installation.e2e_lock.name == "e2e.lock"
    assert not list(installation.state_dir.glob("*.lock"))
