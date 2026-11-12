"""The tracker mirror against real boards (spec: tracker-operations, group 3).

The installed `abk` commands run as a person runs them, in a scratch planning repo whose one
repo names a `tracker` section, against a throwaway Azure DevOps project and a scratch GitHub
repository. What is asserted is read back from the files the commands write (`tracker.yaml`,
`tasks.md`) and from the start check's answer; the board is changed and read only at the
service's own protocol (HTTPS JSON), by a person's credential, never through the kit's tracker
code, so a fault in that code cannot hide in the stand-in.

The targets and credentials come from environment variables, named below. A provider whose
variables are unset is held (skipped) with their names, not failed:

- Azure DevOps: `ABK_LIVE_ADO_ORGANIZATION`, `ABK_LIVE_ADO_PROJECT`, `ABK_LIVE_ADO_TEAM`,
  `ABK_LIVE_ADO_AREA_PATH`, `ABK_LIVE_ADO_ITERATION_PATH` and the sync account's personal access
  token in `ABK_LIVE_ADO_PAT`. `ABK_LIVE_ADO_PROCESS` is `agile` (the default) or `scrum`: a
  process whose items have a Removed state. The start check needs a second account's token in
  `ABK_LIVE_ADO_SECOND_PAT`; without it only that check is held.
- GitHub: the scratch repository as `owner/name` in `ABK_LIVE_GITHUB_REPO` and the sync account's
  token in `ABK_LIVE_GITHUB_TOKEN`; the start check needs a second account's token in
  `ABK_LIVE_GITHUB_SECOND_TOKEN`.

Needs the real services, bills nothing, and writes items to the board it is pointed at (each
test removes what it made, or closes it where the host cannot delete). It is marked e2e-test
and excluded from the default suite.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Protocol

import httpx
import pytest
import yaml

from agent_build_kit import config
from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.tracker_file import TrackerFile, read_tracker
from agent_build_kit.settings import settings
from agent_build_kit.trackers.levels import group_key, task_key
from agent_build_kit.trackers.start_decision import start_decision
from tests.factories import init_repo, unit
from tests.scratch_tick import ABK

pytestmark = pytest.mark.e2e

AZURE_NAMES = (
    "ABK_LIVE_ADO_ORGANIZATION",
    "ABK_LIVE_ADO_PROJECT",
    "ABK_LIVE_ADO_TEAM",
    "ABK_LIVE_ADO_AREA_PATH",
    "ABK_LIVE_ADO_ITERATION_PATH",
    "ABK_LIVE_ADO_PAT",
)
AZURE_SECOND = "ABK_LIVE_ADO_SECOND_PAT"
GITHUB_NAMES = ("ABK_LIVE_GITHUB_REPO", "ABK_LIVE_GITHUB_TOKEN")
GITHUB_SECOND = "ABK_LIVE_GITHUB_SECOND_TOKEN"

# The board's word for a finished and for a removed item, and the type of each level, by process.
AZURE_PROCESSES = {
    "agile": {"done": "Closed", "removed": "Removed", "group": "User Story"},
    "scrum": {"done": "Done", "removed": "Removed", "group": "Product Backlog Item"},
}
GITHUB_TYPES = {"change": "abk-change", "group": "abk-group", "task": "abk-task"}

TASKS = """\
# Live check

## 1. [app] [unit-test] The first group

- [ ] 1.1 Test: the first thing. Verify: red.
- [ ] 1.2 Test: the second thing. Verify: red.
- [ ] 1.3 Add the thing. Verify: 1.1 and 1.2 pass.
"""
TICKED_TASK = 1
REMOVED_TASK = 2
TIMEOUT = 300


class Board(Protocol):
    """What a live test does to a board as a person would, at the host's own protocol."""

    section: dict[str, Any]
    env: dict[str, str]
    second: bool

    def finish(self, item_id: str) -> None: ...

    def remove(self, item_id: str) -> None: ...

    def assign_second(self, item_id: str) -> str:
        """Assign the item to the second account; its display name."""
        ...

    def discard(self, item_id: str) -> None:
        """Leave the board tidy: delete the item, or close it where the host cannot."""
        ...

    def use_credential(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Make this process act as the sync account, as the commands do."""
        ...


class AzureBoard:
    def __init__(self, values: dict[str, str]) -> None:
        self._org = values["ABK_LIVE_ADO_ORGANIZATION"]
        self._project = values["ABK_LIVE_ADO_PROJECT"]
        self._pat = values["ABK_LIVE_ADO_PAT"]
        self._second_pat = values.get(AZURE_SECOND, "")
        self.second = bool(self._second_pat)
        self._process = AZURE_PROCESSES[values.get("ABK_LIVE_ADO_PROCESS", "agile")]
        self.env = {"ABK_LIVE_ADO_PAT": self._pat, "AZURE_DEVOPS_EXT_PAT": self._pat}
        self.section = {
            "kind": "azure_devops",
            "token_env": "ABK_LIVE_ADO_PAT",
            "levels": ["change", "group", "task"],
            "azure_devops": {
                "organization": self._org,
                "project": self._project,
                "team": values["ABK_LIVE_ADO_TEAM"],
                "area_path": values["ABK_LIVE_ADO_AREA_PATH"],
                "iteration_path": values["ABK_LIVE_ADO_ITERATION_PATH"],
                "process": values.get("ABK_LIVE_ADO_PROCESS", "agile"),
                "types": {"change": "Feature", "group": self._process["group"], "task": "Task"},
            },
        }

    def _call(self, method: str, path: str, pat: str, **kwargs: Any) -> httpx.Response:
        token = base64.b64encode(f":{pat}".encode()).decode()
        response = httpx.request(
            method,
            f"https://dev.azure.com/{self._org}/{path}",
            headers={"Authorization": f"Basic {token}", **kwargs.pop("headers", {})},
            timeout=60,
            **kwargs,
        )
        response.raise_for_status()
        return response

    def _set(self, item_id: str, field: str, value: str, pat: str | None = None) -> None:
        self._call(
            "PATCH",
            f"{self._project}/_apis/wit/workitems/{item_id}",
            pat or self._pat,
            params={"api-version": "7.1"},
            headers={"Content-Type": "application/json-patch+json"},
            json=[{"op": "add", "path": f"/fields/{field}", "value": value}],
        )

    def finish(self, item_id: str) -> None:
        self._set(item_id, "System.State", self._process["done"])

    def remove(self, item_id: str) -> None:
        self._set(item_id, "System.State", self._process["removed"])

    def assign_second(self, item_id: str) -> str:
        me = self._call(
            "GET",
            "_apis/connectionData",
            self._second_pat,
            params={"api-version": "7.1-preview.1"},
        ).json()["authenticatedUser"]
        account = me["properties"]["Account"]["$value"]
        self._set(item_id, "System.AssignedTo", account, self._second_pat)
        return me["providerDisplayName"]

    def discard(self, item_id: str) -> None:
        self._call(
            "DELETE",
            f"{self._project}/_apis/wit/workitems/{item_id}",
            self._pat,
            params={"api-version": "7.1"},
        )

    def use_credential(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "ado_pat", self._pat)


class GithubBoard:
    def __init__(self, values: dict[str, str]) -> None:
        self._repo = values["ABK_LIVE_GITHUB_REPO"]
        owner, _, name = self._repo.partition("/")
        self._token = values["ABK_LIVE_GITHUB_TOKEN"]
        self._second_token = values.get(GITHUB_SECOND, "")
        self.second = bool(self._second_token)
        self.env = {"ABK_LIVE_GITHUB_TOKEN": self._token, "GH_TOKEN": self._token}
        self.section = {
            "kind": "github",
            "token_env": "ABK_LIVE_GITHUB_TOKEN",
            "levels": ["change", "group", "task"],
            "github": {"owner": owner, "repo": name, "types": GITHUB_TYPES},
        }

    def _call(self, method: str, path: str, token: str, **kwargs: Any) -> httpx.Response:
        response = httpx.request(
            method,
            f"https://api.github.com/{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=60,
            **kwargs,
        )
        response.raise_for_status()
        return response

    def _issue(self, item_id: str, token: str, **fields: Any) -> None:
        self._call("PATCH", f"repos/{self._repo}/issues/{item_id}", token, json=fields)

    def finish(self, item_id: str) -> None:
        self._issue(item_id, self._token, state="closed", state_reason="completed")

    def remove(self, item_id: str) -> None:
        self._issue(item_id, self._token, state="closed", state_reason="not_planned")

    def assign_second(self, item_id: str) -> str:
        login = self._call("GET", "user", self._second_token).json()["login"]
        # The sync account assigns on the second one's behalf: an issue takes any collaborator.
        self._issue(item_id, self._token, assignees=[login])
        return login

    def discard(self, item_id: str) -> None:
        # An issue cannot be deleted over the REST API.
        self._issue(item_id, self._token, state="closed", state_reason="not_planned")

    def use_credential(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "gh_token", self._token)


PROVIDERS: dict[str, tuple[tuple[str, ...], Callable[[dict[str, str]], Board]]] = {
    "azure_devops": (AZURE_NAMES, AzureBoard),
    "github": (GITHUB_NAMES, GithubBoard),
}


@pytest.fixture(params=sorted(PROVIDERS))
def board(request: pytest.FixtureRequest) -> Board:
    """The board of one provider, or the test is held naming the variables that are unset."""
    names, make = PROVIDERS[request.param]
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        pytest.skip(f"held: the {request.param} target is not configured; unset: {missing}")
    return make({name: os.environ[name] for name in os.environ if name.startswith("ABK_LIVE_")})


class Flow:
    """A scratch planning repo with one change, and the `abk` commands run in it."""

    def __init__(self, root: Path, board: Board, change: str) -> None:
        self.board = board
        self.change = change
        self.root = init_repo(root)
        self.config = {
            "repos": {
                "app": {
                    "path": ".",
                    "slug": "example/app",
                    "tracker": board.section,
                }
            }
        }
        (root / "abk.yaml").write_text(yaml.safe_dump(self.config))
        self.folder = root / "openspec" / "changes" / change
        self.folder.mkdir(parents=True)
        (self.folder / "tasks.md").write_text(TASKS)
        (self.folder / "proposal.md").write_text(f"# {change}\n\nA live check of the mirror.\n")
        self.env = {
            **os.environ,
            **board.env,
        }
        self.env.pop(config.CONFIG_ENV, None)

    def abk(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(ABK), "--config", str(self.root / "abk.yaml"), *args],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
        )

    def sync(self) -> dict[str, Any]:
        """A sync as a person runs it, its JSON document."""
        ran = self.abk("tracker", "sync", "--json")
        assert ran.returncode == 0, f"{ran.stdout}\n{ran.stderr}"
        return json.loads(ran.stdout)["repos"]["app"]

    @property
    def tasks(self) -> Path:
        return self.folder / "tasks.md"

    def recorded(self) -> TrackerFile:
        found = read_tracker(self.folder)
        assert found is not None, "the sync wrote no tracker.yaml"
        return found

    def item_ids(self) -> list[str]:
        found = read_tracker(self.folder)
        if found is None:
            return []
        entries = [*found.groups.values(), *found.tasks.values()]
        if found.change is not None:
            entries.insert(0, found.change)
        return [entry.id for entry in entries]


@pytest.fixture
def flow(board: Board, tmp_path: Path, new_session_id: Callable[[], str]) -> Iterator[Flow]:
    change = f"live-check-{new_session_id()[:8]}"
    made = Flow(tmp_path / "planning", board, change)
    yield made
    for item_id in made.item_ids():
        try:
            board.discard(item_id)
        except httpx.HTTPError:
            pass  # already gone, or closed by the test


@pytest.fixture
def mirrored(flow: Flow) -> Flow:
    """The change after its first sync: the board holds the change, its group and its tasks."""
    flow.sync()
    return flow


def test_a_configured_repo_passes_doctor_and_a_sync_creates_the_board(flow: Flow) -> None:
    doctor = flow.abk("doctor")
    tracker_lines = [line for line in doctor.stdout.splitlines() if "tracker app" in line]
    assert tracker_lines, f"doctor said nothing of the tracker:\n{doctor.stdout}\n{doctor.stderr}"
    assert not any("FAIL" in line for line in tracker_lines), "\n".join(tracker_lines)

    dry = flow.abk("tracker", "sync", "--dry-run")
    assert dry.returncode == 0, f"{dry.stdout}\n{dry.stderr}"
    assert not (flow.folder / "tracker.yaml").exists(), "a dry run wrote the board's ids"

    result = flow.sync()
    assert result.get("error") is None, result
    recorded = flow.recorded()
    assert recorded.change is not None
    assert group_key(flow.change, 1) in recorded.groups
    assert len(recorded.tasks) == 3, sorted(recorded.tasks)
    assert result["created"] == 1 + 1 + 3, result


def test_a_group_item_assigned_to_a_second_account_is_skipped_by_the_start_check(
    mirrored: Flow, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = mirrored.board
    if not board.second:
        pytest.skip(f"held: a second account is not configured ({AZURE_SECOND}, {GITHUB_SECOND})")
    group = mirrored.recorded().groups[group_key(mirrored.change, 1)]
    display_name = board.assign_second(group.id)

    installation = Installation(WorkspaceConfig.model_validate(mirrored.config), mirrored.root)
    installation.activate()
    board.use_credential(monkeypatch)
    try:
        decision = start_decision(
            unit(f"{mirrored.change}/1", change=mirrored.change, repo="app", groups=(1,)),
            changes_dir=installation.changes_dir,
            claim=False,
        )
    finally:
        config.activate(WorkspaceConfig(), None)

    assert decision.outcome == "skip", decision
    assert display_name in decision.reason, decision.reason
    assert group.id in decision.items


def test_a_task_ticked_on_the_board_ticks_its_box(mirrored: Flow) -> None:
    before = mirrored.tasks.read_text()
    task = mirrored.recorded().tasks[task_key(mirrored.change, 1, TICKED_TASK)]
    mirrored.board.finish(task.id)

    mirrored.sync()

    assert mirrored.tasks.read_text() == before.replace("- [ ] 1.1 ", "- [x] 1.1 ", 1)


def test_a_task_removed_on_the_board_is_recorded_and_not_applied(mirrored: Flow) -> None:
    before = mirrored.tasks.read_text()
    task = mirrored.recorded().tasks[task_key(mirrored.change, 1, REMOVED_TASK)]
    mirrored.board.remove(task.id)

    mirrored.sync()

    assert mirrored.tasks.read_text() == before, "a removal on the board changed the spec"
    listed = mirrored.abk("tracker", "conflicts", "--json")
    assert listed.returncode == 0, f"{listed.stdout}\n{listed.stderr}"
    rows = json.loads(listed.stdout)["conflicts"]
    assert [row["item_id"] for row in rows if row["field"] == "removed"] == [task.id], rows
