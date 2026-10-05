"""The Azure DevOps forge's label writes, as the `az devops invoke` calls each sends.

Mirrors `test_github_labels.py`. The runner is a stand-in at the wire: it keeps
labels unique case-insensitively, deletes by name, and keeps them off the single
pull request document, as the real host does. The CLI handles credentials, so
no label call fetches a token or makes a REST request of its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.forges.azure_devops import FORGE
from agent_build_kit.forges.base import Label, RepoId
from agent_build_kit.pipeline.az import AzError
from tests.forges.azure_host import AzureLabelsHost

REPO = RepoId(forge="azure_devops", account="example", project="Proj", name="app")
STATE_FAMILY = ("planned", "running", "in-review", "held")
HELD = Label(name="held", color="d97706")


def never_opened(*args, **kwargs):
    pytest.fail("a label call went out over REST")


def invoke(method: str, *route: str) -> list[str]:
    """The argv a label call is expected to send, less the body file."""
    return [
        "az",
        "devops",
        "invoke",
        "--area",
        "git",
        "--resource",
        "pullRequestLabels",
        "--route-parameters",
        "project=Proj",
        "repositoryId=app",
        "pullRequestId=7",
        *route,
        "--http-method",
        method,
        "--api-version",
        "7.1",
        "--org",
        "https://dev.azure.com/example",
        "--output",
        "json",
    ]


def add(host: AzureLabelsHost, label: Label) -> None:
    FORGE.add_label(REPO, 7, label, run=host, open_url=never_opened)


def move(host: AzureLabelsHost, label: Label) -> None:
    FORGE.set_exclusive_label(REPO, 7, label, family=STATE_FAMILY, run=host, open_url=never_opened)


def remove(host: AzureLabelsHost, name: str) -> None:
    FORGE.remove_label(REPO, 7, name, run=host, open_url=never_opened)


def test_a_label_is_added(monkeypatch: pytest.MonkeyPatch) -> None:
    host = AzureLabelsHost()
    bodies: list[object] = []
    ask = host.__call__

    def reading(args, **kwargs):
        bodies.append(json.loads(Path(args[args.index("--in-file") + 1]).read_text()))
        return ask(args, **kwargs)

    FORGE.add_label(REPO, 7, Label(name="change-feature", color="2563eb"), run=reading)

    assert host.names(7) == ["change-feature"]
    [call] = host.calls
    in_file = call.index("--in-file")
    assert call[:in_file] + call[in_file + 2 :] == invoke("post")
    assert bodies == [{"name": "change-feature"}]


def test_adding_it_again_in_another_case_leaves_one() -> None:
    host = AzureLabelsHost({7: ["in-review"]})

    add(host, Label(name="In-Review", color="2563eb"))

    assert [name.casefold() for name in host.names(7)] == ["in-review"]


def test_a_colour_and_a_description_are_not_an_error() -> None:
    host = AzureLabelsHost()

    add(host, Label(name="running", color="d97706", description="Building"))

    assert host.names(7) == ["running"]


def test_the_state_label_moves_and_leaves_the_rest() -> None:
    host = AzureLabelsHost({7: ["in-review", "change-feature", "bug"]})

    move(host, HELD)

    assert sorted(host.names(7)) == ["bug", "change-feature", "held"]
    assert [call[call.index("--http-method") + 1] for call in host.calls] == [
        "get",
        "post",
        "delete",
    ]
    assert host.calls[2] == invoke("delete", "labelIdOrName=in-review")


def test_a_family_member_in_another_case_is_still_removed() -> None:
    host = AzureLabelsHost({7: ["In-Review"]})

    move(host, HELD)

    assert host.names(7) == ["held"]


def test_a_state_already_there_writes_nothing() -> None:
    host = AzureLabelsHost({7: ["held", "bug"]})

    move(host, HELD)

    assert host.writes() == []


def test_the_current_labels_come_from_one_list_call() -> None:
    """The host's pull request document carries none, so a writer that trusted
    it would leave `in-review` beside `held`."""
    host = AzureLabelsHost({7: ["in-review"]})

    move(host, HELD)

    assert host.calls[0] == invoke("get")
    assert [call for call in host.calls if "get" in call].count(host.calls[0]) == 1
    assert host.names(7) == ["held"]


def test_removing_a_label_is_one_delete_by_name() -> None:
    host = AzureLabelsHost({7: ["needs:review", "bug"]})

    remove(host, "needs:review")

    assert host.names(7) == ["bug"]
    assert host.calls == [invoke("delete", "labelIdOrName=needs:review")]


def test_removing_a_label_that_is_gone_returns_normally() -> None:
    host = AzureLabelsHost({7: ["bug"]})

    remove(host, "agent-rework")

    assert len(host.calls) == 1
    assert host.names(7) == ["bug"]


def test_a_refused_removal_raises() -> None:
    host = AzureLabelsHost({7: ["bug"]}, refuse="TF401027: no rights")

    with pytest.raises(AzError, match="no rights"):
        remove(host, "bug")


def test_no_access_token_is_requested() -> None:
    host = AzureLabelsHost({7: ["in-review"]})

    move(host, HELD)
    remove(host, "held")

    assert not [call for call in host.calls if "get-access-token" in call]
