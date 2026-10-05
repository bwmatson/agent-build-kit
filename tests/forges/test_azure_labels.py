"""The Azure DevOps forge's label writes, as the REST calls each one sends.

Mirrors `test_github_labels.py`. The host is a stand-in at the wire: it keeps
labels unique case-insensitively, deletes by name, and keeps them off the single
pull request document, as the real one does.
"""

from __future__ import annotations

import urllib.request

import pytest

from agent_build_kit.forges.azure_devops import FORGE
from agent_build_kit.forges.base import Label, RepoId
from agent_build_kit.pipeline.az import AzError
from agent_build_kit.settings import settings
from tests.forges.azure_host import AzureLabelsHost

REPO = RepoId(forge="azure_devops", account="example", project="Proj", name="app")
STATE_FAMILY = ("planned", "running", "in-review", "held")
LABELS = "/example/Proj/_apis/git/repositories/app/pullRequests/7/labels"
HELD = Label(name="held", color="d97706")


def install(monkeypatch: pytest.MonkeyPatch, host: AzureLabelsHost) -> AzureLabelsHost:
    monkeypatch.setattr(settings, "ado_pat", "a-secret")
    monkeypatch.setattr(urllib.request, "urlopen", host.open_url)
    return host


def test_a_label_is_added(monkeypatch: pytest.MonkeyPatch) -> None:
    host = install(monkeypatch, AzureLabelsHost())

    FORGE.add_label(REPO, 7, Label(name="change-feature", color="2563eb"))

    assert host.names(7) == ["change-feature"]
    assert host.writes() == [("POST", LABELS)]


def test_adding_it_again_in_another_case_leaves_one(monkeypatch: pytest.MonkeyPatch) -> None:
    host = install(monkeypatch, AzureLabelsHost({7: ["in-review"]}))

    FORGE.add_label(REPO, 7, Label(name="In-Review", color="2563eb"))

    assert [name.casefold() for name in host.names(7)] == ["in-review"]


def test_a_colour_and_a_description_are_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    host = install(monkeypatch, AzureLabelsHost())

    FORGE.add_label(REPO, 7, Label(name="running", color="d97706", description="Building"))

    assert host.names(7) == ["running"]


def test_the_state_label_moves_and_leaves_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    host = install(monkeypatch, AzureLabelsHost({7: ["in-review", "change-feature", "bug"]}))

    FORGE.set_exclusive_label(REPO, 7, HELD, family=STATE_FAMILY)

    assert sorted(host.names(7)) == ["bug", "change-feature", "held"]
    assert [method for method, _ in host.writes()] == ["POST", "DELETE"]


def test_a_family_member_in_another_case_is_still_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    host = install(monkeypatch, AzureLabelsHost({7: ["In-Review"]}))

    FORGE.set_exclusive_label(REPO, 7, HELD, family=STATE_FAMILY)

    assert host.names(7) == ["held"]


def test_a_state_already_there_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    host = install(monkeypatch, AzureLabelsHost({7: ["held", "bug"]}))

    FORGE.set_exclusive_label(REPO, 7, HELD, family=STATE_FAMILY)

    assert host.writes() == []


def test_the_current_labels_come_from_the_labels_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """The host's pull request document carries none, so a writer that trusted
    it would leave `in-review` beside `held`."""
    host = install(monkeypatch, AzureLabelsHost({7: ["in-review"]}))

    FORGE.set_exclusive_label(REPO, 7, HELD, family=STATE_FAMILY)

    assert ("GET", LABELS) in host.requests
    assert host.names(7) == ["held"]


def test_removing_a_label_is_one_delete_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    host = install(monkeypatch, AzureLabelsHost({7: ["agent-rework", "bug"]}))

    FORGE.remove_label(REPO, 7, "agent-rework")

    assert host.names(7) == ["bug"]
    [(method, path)] = host.requests
    assert method == "DELETE" and path.endswith("/labels/agent-rework")


def test_removing_a_label_that_is_gone_returns_normally(monkeypatch: pytest.MonkeyPatch) -> None:
    host = install(monkeypatch, AzureLabelsHost({7: ["bug"]}))

    FORGE.remove_label(REPO, 7, "agent-rework")

    assert [method for method, _ in host.requests] == ["DELETE"]
    assert host.names(7) == ["bug"]


def test_a_refused_removal_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, AzureLabelsHost({7: ["bug"]}, refuse="no rights"))

    with pytest.raises(AzError, match="403"):
        FORGE.remove_label(REPO, 7, "bug")
