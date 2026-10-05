"""A unit's state, written onto an Azure DevOps pull request.

The state label writer over the real Azure forge, the host answering at the
wire; and a forge that has no labels, which still says so once.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

from agent_build_kit.forges.azure_devops import FORGE
from agent_build_kit.forges.base import RepoId
from agent_build_kit.pipeline.labels import StateLabels
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.vocabulary import change_label
from agent_build_kit.settings import settings
from tests.factories import stored_unit as unit
from tests.forges.azure_host import AzureLabelsHost
from tests.forges.stand_in import StandInForge, lookup

PR = 7
REPO = RepoId(forge="azure_devops", account="example", project="Proj", name="app")


def store_over(labels: StateLabels, tmp_path: Path) -> UnitStore:
    return UnitStore(
        tmp_path / "units.json",
        on_state=lambda unit, units, opened: labels.follow(unit, units, opened=opened),
    )


def azure_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: AzureLabelsHost, logged: list[str]
) -> UnitStore:
    monkeypatch.setattr(settings, "ado_pat", "a-secret")
    monkeypatch.setattr(urllib.request, "urlopen", host.open_url)
    return store_over(StateLabels(lambda repo: (FORGE, REPO), log=logged.append), tmp_path)


def test_the_state_follows_the_unit_on_azure(tmp_path: Path, monkeypatch) -> None:
    host, logged = AzureLabelsHost(), []
    store = azure_store(tmp_path, monkeypatch, host, logged)
    store.upsert([unit("add-marker/1")])

    store.set_state("add-marker/1", "running", branch="spec/add-marker/1")
    store.set_state("add-marker/1", "in_review", pr=PR)
    store.set_state("add-marker/1", "held")

    assert sorted(host.names(PR)) == sorted(["held", change_label("add-marker").name])
    assert not any("no labels" in line for line in logged), logged


def test_a_refused_label_write_is_logged_and_the_unit_goes_on(tmp_path: Path, monkeypatch) -> None:
    host, logged = AzureLabelsHost(refuse="TF401027: you need permission"), []
    store = azure_store(tmp_path, monkeypatch, host, logged)
    store.upsert([unit("add-marker/1")])

    store.set_state("add-marker/1", "in_review", pr=PR, branch="spec/add-marker/1")
    store.set_state("add-marker/1", "held")

    assert store.get("add-marker/1").state == "held"
    assert any("failed" in line and "403" in line for line in logged), logged
    assert not any("no labels" in line for line in logged), logged


class NoLabelsForge(StandInForge):
    def add_label(self, *args, **kwargs) -> None:
        raise NotImplementedError

    def set_exclusive_label(self, *args, **kwargs) -> None:
        raise NotImplementedError

    def remove_label(self, *args, **kwargs) -> None:
        raise NotImplementedError


def test_a_host_without_labels_still_says_so_once(tmp_path: Path) -> None:
    logged: list[str] = []
    store = store_over(StateLabels(lookup(NoLabelsForge()), log=logged.append), tmp_path)
    store.upsert([unit("add-marker/1")])

    store.set_state("add-marker/1", "in_review", pr=PR, branch="spec/add-marker/1")
    store.set_state("add-marker/1", "held")

    assert len([line for line in logged if "keeps no labels" in line]) == 1
