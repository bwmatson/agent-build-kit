"""The local forge keeps pull requests in the state directory (spec: local-forge).

Nothing here has a host: the forge is built over a temporary state directory, any
network connection fails the test, and reviews are written with the real review store.
"""

from __future__ import annotations

import inspect
import socket
from pathlib import Path
from typing import Any, NoReturn

import pytest

from agent_build_kit import forges
from agent_build_kit.config import RepoConfig
from agent_build_kit.forges import Label, RepoId
from agent_build_kit.forges.base import Forge
from agent_build_kit.forges.local import LocalForge
from agent_build_kit.forges.operations import OPERATIONS
from agent_build_kit.forges.resilient import ResilientForge
from agent_build_kit.pipeline.pr_poller import Poller
from agent_build_kit.pipeline.unit_store import ReworkKind, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING
from agent_build_kit.serve.review import ReviewStore
from tests.conftest import make_installation

REPO = RepoId(forge="local", account="local", name="app")
UNIT = "feature/2"
HEAD = "spec/feature/2"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> NoReturn:
        raise AssertionError("the local forge made a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def state(tmp_path: Path) -> Path:
    directory = tmp_path / "state"
    directory.mkdir()
    return directory


@pytest.fixture
def forge(state: Path) -> LocalForge:
    return LocalForge(state)


def open_pr(forge: LocalForge, head: str = HEAD, base: str = "main") -> int:
    return forge.create_pr(REPO, head=head, base=base, title="Feature", body="Body")


def unit_in_review(state: Path, number: int, unit: str = UNIT, head: str = HEAD) -> None:
    units = UnitStore(state / "units.json")
    units.set_state(unit, RUNNING, branch=head)
    units.set_state(unit, IN_REVIEW, pr=number)


def thread(state: Path, body: str = "why this?", unit: str = UNIT) -> str:
    return (
        ReviewStore(state / "reviews")
        .add_thread(
            unit, path="a.py", side="new", line=3, start_line=None, commit="c" * 40, body=body
        )
        .id
    )


# --- opening, finding, updating and closing -------------------------------------------


def test_a_created_pull_request_is_found_by_its_head(forge: LocalForge) -> None:
    number = open_pr(forge)

    assert forge.find_pr(REPO, head=HEAD) == number


def test_a_head_with_no_pull_request_is_not_found(forge: LocalForge) -> None:
    open_pr(forge)

    assert forge.find_pr(REPO, head="spec/other/1") is None


def test_a_created_pull_request_is_listed_with_its_number_head_and_base(
    forge: LocalForge,
) -> None:
    number = open_pr(forge, base="spec/feature/1")

    [pull] = forge.list_prs(REPO)

    assert (pull.number, pull.head, pull.base, pull.state) == (
        number,
        HEAD,
        "spec/feature/1",
        "open",
    )


def test_each_pull_request_has_a_number_of_its_own(forge: LocalForge) -> None:
    first = open_pr(forge)
    second = open_pr(forge, head="spec/feature/3")

    assert first != second
    assert sorted(p.number for p in forge.list_prs(REPO)) == sorted([first, second])


def test_listing_by_head_prefix_keeps_only_the_matching_pull_requests(forge: LocalForge) -> None:
    open_pr(forge)
    open_pr(forge, head="other/branch")

    assert [p.head for p in forge.list_prs(REPO, head_prefix="spec/")] == [HEAD]


def test_pull_requests_are_kept_in_the_state_directory(state: Path, forge: LocalForge) -> None:
    number = open_pr(forge)

    again = LocalForge(state)

    assert again.find_pr(REPO, head=HEAD) == number
    assert [p.number for p in again.list_prs(REPO)] == [number]


def test_updating_the_base_is_recorded(state: Path, forge: LocalForge) -> None:
    number = open_pr(forge)

    forge.update_pr(REPO, number, base="develop")

    assert [p.base for p in LocalForge(state).list_prs(REPO)] == ["develop"]


def test_updating_the_body_leaves_the_base(forge: LocalForge) -> None:
    number = open_pr(forge)

    forge.update_pr(REPO, number, body="New body")

    assert [p.base for p in forge.list_prs(REPO)] == ["main"]


def test_closing_a_pull_request_is_recorded(state: Path, forge: LocalForge) -> None:
    number = open_pr(forge)

    forge.close_pr(REPO, number)

    [pull] = LocalForge(state).list_prs(REPO)
    assert (pull.number, pull.state) == (number, "closed")


# --- reading the review ---------------------------------------------------------------


def test_a_pull_request_with_no_review_has_no_conversation(state: Path, forge: LocalForge) -> None:
    unit_in_review(state, open_pr(forge))

    [pull] = forge.list_prs(REPO)

    assert pull.conversation == ()
    assert pull.comment_bodies == ()
    assert pull.review_decision == ""


def test_listing_carries_the_ids_and_bodies_of_the_review_s_comments(
    state: Path, forge: LocalForge
) -> None:
    unit_in_review(state, open_pr(forge))
    first = thread(state, "why this?")
    second = thread(state, "and this?")
    ReviewStore(state / "reviews").reply(UNIT, first, "also here")

    [pull] = forge.list_prs(REPO)

    assert first in pull.conversation
    assert second in pull.conversation
    assert {"why this?", "and this?", "also here"} <= set(pull.comment_bodies)
    assert len(pull.conversation) == len(pull.comment_bodies)


def test_listing_carries_a_request_for_changes_as_the_decision(
    state: Path, forge: LocalForge
) -> None:
    unit_in_review(state, open_pr(forge))
    ReviewStore(state / "reviews").decide(
        UNIT, round=1, decision="request_changes", summary="rework it"
    )

    [pull] = forge.list_prs(REPO)

    assert pull.review_decision == "changes_requested"
    assert "rework it" in pull.comment_bodies


def test_an_approval_is_the_decision_and_the_pull_request_stays_open(
    state: Path, forge: LocalForge
) -> None:
    unit_in_review(state, open_pr(forge))
    ReviewStore(state / "reviews").decide(UNIT, round=1, decision="approve", summary="looks good")

    [pull] = forge.list_prs(REPO)

    assert pull.review_decision == "approved"
    assert pull.state == "open"


def test_another_unit_s_review_is_not_this_pull_request_s(state: Path, forge: LocalForge) -> None:
    unit_in_review(state, open_pr(forge))
    unit_in_review(state, open_pr(forge, head="spec/feature/3"), "feature/3", "spec/feature/3")
    thread(state, "there", unit="feature/3")

    pulls = {p.head: p for p in forge.list_prs(REPO)}

    assert pulls[HEAD].conversation == ()
    assert len(pulls["spec/feature/3"].conversation) == 1


class Poll:
    """The poller over the local forge, as it is over a host's listing."""

    def __init__(self, state: Path, forge: LocalForge) -> None:
        self.events: list[tuple[str, Any]] = []
        self.poller = Poller(
            repo="app",
            state_path=state / "poll.json",
            list_prs=lambda: forge.list_prs(REPO),
            dispatch=lambda event, number, **kw: self.events.append((event, kw.get("rework"))),
        )

    def poll(self) -> list[tuple[str, Any]]:
        self.events.clear()
        self.poller.poll()
        return list(self.events)


def test_a_ui_comment_on_a_local_pull_request_sends_the_unit_back(
    state: Path, forge: LocalForge
) -> None:
    unit_in_review(state, open_pr(forge))
    poll = Poll(state, forge)
    poll.poll()
    thread(state)

    assert poll.poll() == [("rework", ReworkKind.COMMENT)]
    assert poll.poll() == []


def test_requesting_changes_on_a_local_pull_request_sends_the_unit_back(
    state: Path, forge: LocalForge
) -> None:
    unit_in_review(state, open_pr(forge))
    poll = Poll(state, forge)
    poll.poll()
    ReviewStore(state / "reviews").decide(
        UNIT, round=1, decision="request_changes", summary="rework it"
    )

    assert poll.poll() == [("rework", ReworkKind.CHANGES_REQUESTED)]


def test_an_approval_on_a_local_pull_request_is_not_rework(state: Path, forge: LocalForge) -> None:
    unit_in_review(state, open_pr(forge))
    poll = Poll(state, forge)
    poll.poll()
    ReviewStore(state / "reviews").decide(UNIT, round=1, decision="approve", summary="ok")

    assert poll.poll() == []


# --- what has no local meaning --------------------------------------------------------


def test_labels_drafts_statuses_and_checks_change_nothing(forge: LocalForge) -> None:
    number = open_pr(forge)
    [before] = forge.list_prs(REPO)
    label = Label(name="needs-rework", color="ff0000")

    forge.add_label(REPO, number, label)
    forge.set_exclusive_label(REPO, number, label, family=["needs-rework", "approved"])
    forge.remove_label(REPO, number, "approved")
    forge.set_draft(REPO, number, True)
    forge.post_status(REPO, sha="a" * 40, ok=False, context="tier1", description="failed")
    forge.rerun_checks(REPO, before)
    forge.delete_remote_branch(REPO, HEAD)

    assert forge.failed_check_logs(REPO, before) == ""
    assert forge.list_prs(REPO) == [before]
    assert before.labels == () and not before.draft and before.checks == ()


def test_stacks_do_nothing_and_the_forge_says_it_has_none(forge: LocalForge) -> None:
    first = open_pr(forge)
    second = open_pr(forge, head="spec/feature/3")
    before = forge.list_prs(REPO)

    forge.create_stack(REPO, [first, second])
    forge.add_to_stack(REPO, first, [second])

    assert forge.supports_stacks is False
    assert forge.stack_of(REPO, first) is None
    assert forge.list_prs(REPO) == before


def test_access_is_always_fine(forge: LocalForge) -> None:
    assert forge.check_access(REPO) == ""
    assert forge.requires == ()
    assert forge.client is None


def test_a_comment_that_was_never_posted_does_not_exist(forge: LocalForge) -> None:
    number = open_pr(forge)

    assert forge.comment_exists(REPO, number, "<!-- marker -->", "body") is None


def test_the_identity_of_a_repo_needs_no_host_facts(forge: LocalForge, tmp_path: Path) -> None:
    repo = RepoConfig(path=tmp_path / "app", forge="local")

    assert forge.identity(repo).forge == "local"


# --- registration and selection -------------------------------------------------------


def protocol_attributes() -> list[str]:
    return sorted(
        {
            name
            for klass in Forge.__mro__
            for name in getattr(klass, "__annotations__", {})
            if not name.startswith("_")
        }
    )


def protocol_methods() -> list[str]:
    return sorted(
        {
            name
            for klass in Forge.__mro__
            for name, member in vars(klass).items()
            if inspect.isfunction(member) and not name.startswith("_")
        }
    )


def test_the_local_forge_is_registered_by_name() -> None:
    assert "local" in forges.names()
    assert forges.get("local").name == "local"


def test_the_registered_local_forge_is_behind_the_retry_layer() -> None:
    assert isinstance(forges.get("local"), ResilientForge)


@pytest.mark.parametrize("name", protocol_methods())
def test_every_protocol_method_is_declared_and_implemented_on_the_local_forge(name: str) -> None:
    assert name in OPERATIONS
    assert callable(getattr(forges.get("local"), name))


@pytest.mark.parametrize("name", protocol_attributes())
def test_every_protocol_attribute_is_implemented_on_the_local_forge(name: str) -> None:
    assert hasattr(forges.get("local"), name)


def test_a_repo_selects_the_local_forge_by_its_setting(tmp_path: Path) -> None:
    app = {"path": str(tmp_path / "app"), "forge": "local"}
    inst = make_installation(tmp_path / "planning", repos={"app": app})

    forge, repo = inst.forge_of("app")

    assert forge.name == "local"
    assert repo.forge == "local"


def test_a_repo_with_a_github_slug_still_uses_the_forge_it_sets(tmp_path: Path) -> None:
    app = {"path": str(tmp_path / "app"), "forge": "local", "slug": "example/app"}
    inst = make_installation(tmp_path / "planning", repos={"app": app})

    assert inst.forge_of("app")[0].name == "local"


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:example/app.git",
        "https://github.com/example/app",
        "/srv/git/app.git",
        "local",
        "",
    ],
)
def test_no_remote_is_taken_for_a_local_repo(url: str) -> None:
    assert forges.get("local").parse_remote(url) is None
    identified = forges.identify(url)
    assert identified is None or identified.forge != "local"
