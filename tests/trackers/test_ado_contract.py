"""The shared contract suite passes against the Azure DevOps tracker through the in-memory host,
and a work item call is authenticated by the same cached credential as a pull request call."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import RepoId
from agent_build_kit.settings import settings
from agent_build_kit.trackers.azure_devops import AzureDevOpsWorkItems
from agent_build_kit.trackers.base import ItemKind
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost
from tests.trackers import contract
from tests.trackers.ado_support import section, tracker_on
from tests.trackers.ado_work_item_host import WorkItemHost

pytestmark = pytest.mark.usefixtures("rest_env")

OTHER = "other@example.com"
# The processes and the levels each has a type for.
BOARDS = [
    (process, key)
    for process, keys in {
        "basic": ("change", "change-group"),
        "scrum": tuple(contract.LEVEL_SETS),
        "agile": tuple(contract.LEVEL_SETS),
    }.items()
    for key in keys
]


@pytest.fixture(params=BOARDS, ids=[f"{process}-{key}" for process, key in BOARDS])
def board(request: pytest.FixtureRequest) -> tuple[str, tuple[ItemKind, ...]]:
    process, key = request.param
    return process, contract.LEVEL_SETS[key]


@pytest.fixture(params=[False, True], ids=["no-epic", "epic"])
def with_epic(request: pytest.FixtureRequest) -> bool:
    return request.param


@pytest.fixture
def shape(board: tuple[str, tuple[ItemKind, ...]], with_epic: bool) -> contract.Shape:
    process, levels = board
    host = WorkItemHost()
    tracker = tracker_on(host, process, levels=levels, epic=with_epic)
    competitor = AzureDevOpsWorkItems(
        section(process, levels=levels, epic=with_epic), http=host.as_identity(OTHER)
    )
    epic = tracker.get(host.seed("Epic", "Epic")) if with_epic else None
    return contract.shape_of(tracker, competitor, levels, epic)


@pytest.mark.parametrize("scenario", list(contract.SCENARIOS))
def test_the_tracker_passes_every_scenario(scenario: str, shape: contract.Shape) -> None:
    contract.SCENARIOS[scenario](shape)


# --- one credential for the forge and the tracker ---------------------------------------

REPO = RepoId(forge="azure_devops", account="example", project="Some Project", name="Some Repo")


class Session:
    """`az` as a subprocess.run stand-in: each read answers the next token."""

    def __init__(self, *tokens: str) -> None:
        self.tokens = list(tokens)
        self.commands: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, f"{self.tokens.pop(0)}\n", "")


def pull_request_call(forge_host: RestHost) -> None:
    AzureDevOpsForge(http=forge_host).list_prs(REPO)


def work_item_call(work_host: WorkItemHost) -> None:
    tracker_on(work_host).identity()


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setattr(settings, "ado_pat", "")
    made = Session("tok-az")
    monkeypatch.setattr(subprocess, "run", made)
    return made


def test_a_pull_request_call_and_a_work_item_call_share_one_cached_credential(
    session: Session,
) -> None:
    forge_host, work_host = RestHost(azure_answers.OPEN), WorkItemHost()

    pull_request_call(forge_host)
    work_item_call(work_host)

    assert len(session.commands) == 1
    assert {call.authorization for call in forge_host.seen + work_host.seen} == {"Bearer tok-az"}


@pytest.mark.parametrize("first", ["forge", "tracker"])
def test_a_rejected_token_is_dropped_and_retried_once_for_either(
    first: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ado_pat", "")
    made = Session("tok-old", "tok-new")
    monkeypatch.setattr(subprocess, "run", made)
    forge_host, work_host = RestHost(azure_answers.OPEN), WorkItemHost()
    forge_host.rejected_tokens.add("tok-old")
    work_host.rejected_tokens.add("tok-old")
    calls = {
        "forge": lambda: pull_request_call(forge_host),
        "tracker": lambda: work_item_call(work_host),
    }

    calls[first]()
    calls["forge" if first == "tracker" else "tracker"]()

    assert len(made.commands) == 2, "one fresh read, shared by the other call"
    hosts = {"forge": forge_host, "tracker": work_host}
    assert {call.authorization for call in hosts[first].seen} == {
        "Bearer tok-old",
        "Bearer tok-new",
    }
