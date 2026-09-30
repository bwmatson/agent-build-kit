"""The GitHub forge's label writes, as the `gh` argv each one sends.

The host answers with what `gh` prints for a pull request's labels; the fake
records every call, whichever of the shell helpers made it.
"""

import json
import subprocess

import pytest

from agent_build_kit.forges.base import Label, RepoId
from agent_build_kit.forges.github import FORGE

REPO = RepoId(forge="github", account="example", name="app")
RUNNING = Label(name="running", color="d97706", description="An agent is building this unit")
STATE_FAMILY = ("planned", "running", "in-review", "held")


class Recorder:
    """Every gh call, answering as a repo whose pull request 7 carries
    `in-review` and `bug`, and which has no `running` label yet."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def _answer(self, args: list[str]) -> object:
        if args[:3] == ["gh", "label", "list"]:
            return [{"name": "in-review", "color": "2563eb", "description": ""}]
        return {"labels": [{"name": "in-review"}, {"name": "bug"}]}

    def gh(self, args: list[str], *, slug: str = "", **_) -> subprocess.CompletedProcess:
        self.commands.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps(self._answer(args)), "")

    def out(self, args: list[str], *, slug: str = "") -> str:
        self.commands.append(args)
        return json.dumps(self._answer(args))

    def json(self, args: list[str], *, slug: str = "", default: object = None) -> object:
        self.commands.append(args)
        return self._answer(args)


@pytest.fixture
def gh(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr("agent_build_kit.forges.github.gh", recorder.gh)
    monkeypatch.setattr("agent_build_kit.forges.github.gh_out", recorder.out)
    monkeypatch.setattr("agent_build_kit.forges.github.gh_json", recorder.json)
    return recorder


def flag_values(commands: list[list[str]], flag: str) -> list[str]:
    return [c[i + 1] for c in commands for i, token in enumerate(c) if token == flag]


def test_a_label_the_repo_lacks_is_created_with_its_colour_and_description(gh: Recorder) -> None:
    FORGE.add_label(REPO, 7, RUNNING)

    (create,) = [c for c in gh.commands if c[:3] == ["gh", "label", "create"]]
    assert "running" in create
    assert flag_values([create], "--color") == ["d97706"]
    assert flag_values([create], "--description") == ["An agent is building this unit"]
    assert flag_values([create], "--repo") == ["example/app"]


def test_a_label_the_repo_has_is_not_created_again(gh: Recorder) -> None:
    FORGE.add_label(REPO, 7, Label(name="in-review", color="2563eb", description="In review"))

    assert not [c for c in gh.commands if c[:3] == ["gh", "label", "create"]]


def test_adding_a_label_puts_it_on_the_pull_request(gh: Recorder) -> None:
    FORGE.add_label(REPO, 7, RUNNING)

    edits = [c for c in gh.commands if c[:3] == ["gh", "pr", "edit"]]
    assert flag_values(edits, "--add-label") == ["running"]
    assert all("7" in c and "example/app" in c for c in edits)


def test_setting_an_exclusive_label_removes_the_rest_of_its_family_only(gh: Recorder) -> None:
    FORGE.set_exclusive_label(REPO, 7, RUNNING, family=STATE_FAMILY)

    edits = [c for c in gh.commands if c[:3] == ["gh", "pr", "edit"]]
    assert flag_values(edits, "--add-label") == ["running"]
    assert flag_values(edits, "--remove-label") == ["in-review"], "`bug` is not the pipeline's"


def test_removing_a_label_takes_it_off_the_pull_request(gh: Recorder) -> None:
    FORGE.remove_label(REPO, 7, "agent-rework")

    edits = [c for c in gh.commands if c[:3] == ["gh", "pr", "edit"]]
    assert flag_values(edits, "--remove-label") == ["agent-rework"]
    assert all("7" in c and "example/app" in c for c in edits)


def test_a_label_the_repo_has_under_another_case_is_not_created_again(gh: Recorder) -> None:
    FORGE.add_label(REPO, 7, Label(name="In-Review", color="2563eb", description="In review"))

    assert not [c for c in gh.commands if c[:3] == ["gh", "label", "create"]]
