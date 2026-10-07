"""Registering a unit's pull request in the host's stack as it is opened.

The pipeline already builds a chain: a unit's pull request targets its newest
still-open same-repo dependency's branch. What the host needs told is that the
two are one series. So the step that opens a pull request, once it has one,
asks the host which stack the base pull request is in and creates or extends
it — and a host that refuses costs the unit nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges import RepoId, Stack, StackRefused
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, UnitState
from agent_build_kit.pipeline.wiring import build_open_pr
from tests.factories import stored_unit
from tests.factories import unit as plan_unit

REPO = RepoId(forge="fake", account="example", name="app")


class StackingForge:
    """A code host with stacks, recording what it was asked.

    `stacks` maps a pull request to the stack it is in; `refusals` are raised,
    in turn, by the next create or append.
    """

    name = "fake"
    implemented = True
    deletes_head_branch_on_merge = True
    denied_commands = ()
    read_commands = ()

    def __init__(
        self,
        *,
        supports_stacks: bool = True,
        existing: int | None = None,
        number: int = 12,
        stacks: dict[int, Stack] | None = None,
        refusals: list[StackRefused] | None = None,
    ) -> None:
        self.supports_stacks = supports_stacks
        self.existing = existing
        self.number = number
        self.stacks = stacks or {}
        self.refusals = list(refusals or [])
        self.calls: list[tuple] = []

    def find_pr(self, repo, *, head):
        return self.existing

    def create_pr(self, repo, *, head, base, title, body):
        self.calls.append(("create_pr", base))
        return self.number

    def update_pr(self, repo, pr, *, base="", body=""):
        self.calls.append(("update_pr", pr, base))

    def stack_of(self, repo, pr):
        self._stacks_used()
        self.calls.append(("stack_of", pr))
        return self.stacks.get(pr)

    def create_stack(self, repo, pulls):
        self._stacks_used()
        self.calls.append(("create_stack", list(pulls)))
        if self.refusals:
            raise self.refusals.pop(0)
        return Stack(number=9, open=True, pulls=tuple(pulls))

    def add_to_stack(self, repo, stack, pulls):
        self._stacks_used()
        self.calls.append(("add_to_stack", stack, list(pulls)))
        if self.refusals:
            raise self.refusals.pop(0)
        return Stack(number=stack, open=True, pulls=(*self.stacks_of(stack), *pulls))

    def stacks_of(self, number: int) -> tuple[int, ...]:
        return next(s.pulls for s in self.stacks.values() if s.number == number)

    def _stacks_used(self) -> None:
        assert self.supports_stacks, "a host without stacks was asked about one"

    def registered(self) -> list[tuple]:
        return [c for c in self.calls if c[0] in ("create_stack", "add_to_stack")]


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    """feature/2 sits on feature/1, whose pull request is #11."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("feature/1"), stored_unit("feature/2", depends_on=("feature/1",))])
    store.set_state("feature/1", IN_REVIEW, pr=11, branch="spec/feature/1")
    store.set_state("feature/2", UnitState.RUNNING, branch="spec/feature/2")
    return store


CHILD = plan_unit("feature/2", change="feature", depends_on=("feature/1",))


def open_with(
    forge: StackingForge,
    store: UnitStore,
    logged: list[str] | None = None,
    slept: list[float] | None = None,
):
    log = logged.append if logged is not None else (lambda message: None)
    sleep = slept.append if slept is not None else (lambda seconds: None)
    return build_open_pr(for_repo=lambda repo: (forge, REPO), store=store, log=log, sleep=sleep)


def test_the_capability_flag_decides_whether_anything_is_registered(
    store: UnitStore, tmp_path: Path
) -> None:
    """The same chain on two hosts: the one with stacks is told about it; the
    one without is never asked, and its pull request is opened as today."""
    with_stacks = StackingForge(supports_stacks=True)
    without = StackingForge(supports_stacks=False)

    open_with(with_stacks, store)(CHILD, body="b", base="spec/feature/1", cwd=tmp_path)
    number = open_with(without, store)(CHILD, body="b", base="spec/feature/1", cwd=tmp_path)

    assert with_stacks.registered(), "a host with stacks is told about the chain"
    assert number == 12
    assert without.calls == [("create_pr", "spec/feature/1")]
    assert store.get("feature/2").stack_refusal == ""


def test_the_second_pull_request_of_a_chain_creates_a_stack_bottom_first(
    store: UnitStore, tmp_path: Path
) -> None:
    """The first, on the trunk, registers nothing: a stack of one is not a
    stack. The second creates it with both."""
    forge = StackingForge()
    open_pr = open_with(forge, store)

    forge.number = 11
    open_pr(plan_unit("feature/1", change="feature"), body="b", base="main", cwd=tmp_path)
    forge.number = 12
    open_pr(CHILD, body="b", base="spec/feature/1", cwd=tmp_path)

    assert ("stack_of", 11) in forge.calls, "asked of the host, not remembered"
    assert forge.registered() == [("create_stack", [11, 12])]


def test_a_later_pull_request_is_appended_to_its_base_s_stack(
    store: UnitStore, tmp_path: Path
) -> None:
    """And only once: every restack reopens the pull request, and the second
    pass finds it already where it belongs."""
    forge = StackingForge(stacks={11: Stack(number=4, open=True, pulls=(10, 11))})
    open_pr = open_with(forge, store)

    open_pr(CHILD, body="b", base="spec/feature/1", cwd=tmp_path)
    forge.existing = 12
    forge.stacks[12] = Stack(number=4, open=True, pulls=(10, 11, 12))
    open_pr(CHILD, body="b", base="spec/feature/1", cwd=tmp_path)

    assert forge.registered() == [("add_to_stack", 4, [12])]


def test_a_stack_that_cannot_be_extended_starts_a_new_one(store: UnitStore, tmp_path: Path) -> None:
    """Its pull requests have all merged: that is a finished stack, not a
    failure to report."""
    forge = StackingForge(stacks={11: Stack(number=4, open=False, pulls=(10, 11))})

    open_with(forge, store)(CHILD, body="b", base="spec/feature/1", cwd=tmp_path)

    assert forge.registered() == [("create_stack", [11, 12])]
    assert store.get("feature/2").stack_refusal == ""


REFUSALS = [
    pytest.param(StackRefused("HTTP 404: Not Found"), id="feature-unavailable"),
    pytest.param(
        StackRefused("HTTP 422: Stacks are not enabled for this repository"),
        id="repository-ineligible",
    ),
    pytest.param(
        StackRefused("HTTP 422: Pull request #12 base ref does not match #11 head ref"),
        id="chain-rejected",
    ),
]


@pytest.mark.parametrize("refusal", REFUSALS)
def test_a_refusal_costs_the_unit_nothing(
    store: UnitStore, tmp_path: Path, refusal: StackRefused
) -> None:
    """The pull request is opened, its number returned for the runner's later
    steps, the unit's state untouched, and the reason on its record."""
    forge = StackingForge(refusals=[refusal])
    before = store.get("feature/2")

    number = open_with(forge, store)(CHILD, body="b", base="spec/feature/1", cwd=tmp_path)

    after = store.get("feature/2")
    assert number == 12
    assert after.state == before.state
    assert after.history == before.history
    assert [c for c in forge.calls if c[0] in ("create_pr", "update_pr")] == [
        ("create_pr", "spec/feature/1")
    ], "the pull request is neither closed, retargeted nor edited over it"
    assert refusal.reason in after.stack_refusal


def test_a_refusal_is_logged_once_however_often_the_unit_is_reopened(
    store: UnitStore, tmp_path: Path
) -> None:
    """The step runs again on every restack; a host that never has stacks
    would otherwise say so in the tick log every time."""
    reason = "HTTP 404: Not Found"
    logged: list[str] = []
    forge = StackingForge(refusals=[StackRefused(reason), StackRefused(reason)])
    open_pr = open_with(forge, store, logged)

    open_pr(CHILD, body="b", base="spec/feature/1", cwd=tmp_path)
    forge.existing = 12
    open_pr(CHILD, body="b", base="spec/feature/1", cwd=tmp_path)

    assert sum(reason in line for line in logged) == 1


def test_a_concurrent_modification_is_retried(store: UnitStore, tmp_path: Path) -> None:
    """Overlapping ticks make it ordinary: two units of one change finishing
    close together both append to the same stack."""
    forge = StackingForge(
        stacks={11: Stack(number=4, open=True, pulls=(10, 11))},
        refusals=[StackRefused("HTTP 409: stack is being modified", concurrent=True)],
    )
    slept: list[float] = []

    open_with(forge, store, slept=slept)(CHILD, body="b", base="spec/feature/1", cwd=tmp_path)

    assert forge.registered() == [("add_to_stack", 4, [12]), ("add_to_stack", 4, [12])]
    assert store.get("feature/2").stack_refusal == ""
    assert slept and slept[0] > 0, "asked again after a pause, not straight back into the 409"


def test_a_stack_that_stays_busy_is_recorded_not_raised(store: UnitStore, tmp_path: Path) -> None:
    busy = [StackRefused("HTTP 409: stack is being modified", concurrent=True)] * 20
    forge = StackingForge(stacks={11: Stack(number=4, open=True, pulls=(10, 11))}, refusals=busy)

    number = open_with(forge, store)(CHILD, body="b", base="spec/feature/1", cwd=tmp_path)

    assert number == 12
    assert "409" in store.get("feature/2").stack_refusal
    assert len(forge.registered()) < 20, "retried a bounded number of times"


def test_a_refusal_from_an_earlier_base_is_cleared_once_it_is_on_the_trunk(
    store: UnitStore, tmp_path: Path
) -> None:
    """Its base merged and the PR was retargeted to the trunk: nothing is
    beneath it, so the old reason is no longer true of it."""
    store.set_stack_refusal("feature/2", "HTTP 404: Not Found")
    forge = StackingForge(existing=12)

    open_with(forge, store)(CHILD, body="b", base="main", cwd=tmp_path)

    assert store.get("feature/2").stack_refusal == ""


class Unreadable(StackingForge):
    """A host whose stacks call throws something that is not a refusal."""

    def stack_of(self, repo, pr):
        raise RuntimeError("the host answered with something unreadable")


def test_anything_the_host_throws_costs_the_unit_nothing(store: UnitStore, tmp_path: Path) -> None:
    """Registering is advisory, and the PR is already open when it is tried:
    an error of any kind is recorded as the refusal, never raised."""
    forge = Unreadable()
    before = store.get("feature/2")

    number = open_with(forge, store)(CHILD, body="b", base="spec/feature/1", cwd=tmp_path)

    after = store.get("feature/2")
    assert number == 12
    assert after.state == before.state
    assert after.history == before.history
    assert "unreadable" in after.stack_refusal


class BodyRecordingForge(StackingForge):
    """Keeps every body the PR was given, in order."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.bodies: list[str] = []

    def create_pr(self, repo, *, head, base, title, body):
        self.bodies.append(body)
        return super().create_pr(repo, head=head, base=base, title=title, body=body)

    def update_pr(self, repo, pr, *, base="", body=""):
        self.bodies.append(body)
        super().update_pr(repo, pr, base=base, body=body)


BODIES = {"body": "Stacked on `spec/feature/1`. Merge feature/1 first.", "stacked_body": "linear"}


def test_a_base_reached_through_a_satisfied_dependency_is_still_registered(
    store: UnitStore, tmp_path: Path
) -> None:
    """feature/2 landed without a PR of its own to stack on; feature/3 depends on
    it only, but its PR targets feature/1's branch, so that is the one beneath."""
    store.set_state("feature/2", UnitState.SATISFIED)
    store.upsert([stored_unit("feature/3", depends_on=("feature/2",))])
    forge = BodyRecordingForge()

    open_with(forge, store)(
        plan_unit("feature/3", change="feature", depends_on=("feature/2",)),
        base="spec/feature/1",
        cwd=tmp_path,
        **BODIES,
    )

    assert forge.registered() == [("create_stack", [11, 12])]
    assert forge.bodies[-1] == BODIES["stacked_body"]


def test_a_pull_request_the_host_would_not_stack_keeps_the_order_in_its_body(
    store: UnitStore, tmp_path: Path
) -> None:
    """Opened expecting a stack, refused in the same call: the host shows no
    order, so the body has to again."""
    forge = BodyRecordingForge(refusals=[StackRefused("HTTP 422: Stacks are not enabled")])

    open_with(forge, store)(CHILD, base="spec/feature/1", cwd=tmp_path, **BODIES)

    assert "Stacked on" in forge.bodies[-1]


def test_a_unit_refused_before_is_opened_with_the_order_in_its_body(
    store: UnitStore, tmp_path: Path
) -> None:
    """A refusal already on the record: every body it is given states the
    order, since the host is expected to refuse again."""
    store.set_stack_refusal("feature/2", "HTTP 422: Stacks are not enabled")
    forge = BodyRecordingForge(
        existing=12, refusals=[StackRefused("HTTP 422: Stacks are not enabled")]
    )

    open_with(forge, store)(CHILD, base="spec/feature/1", cwd=tmp_path, **BODIES)

    assert forge.bodies and all("Stacked on" in body for body in forge.bodies)


def test_a_pull_request_the_host_stacked_leaves_the_order_to_the_host(
    store: UnitStore, tmp_path: Path
) -> None:
    """Including one refused before and accepted now: its body stops
    restating the order once the host shows it."""
    store.set_stack_refusal("feature/2", "HTTP 404: Not Found")
    forge = BodyRecordingForge(existing=12)

    open_with(forge, store)(CHILD, base="spec/feature/1", cwd=tmp_path, **BODIES)

    assert forge.bodies[-1] == "linear"
    assert store.get("feature/2").stack_refusal == ""


def test_a_host_without_stacks_gets_the_body_that_states_the_order(
    store: UnitStore, tmp_path: Path
) -> None:
    forge = BodyRecordingForge(supports_stacks=False)

    open_with(forge, store)(CHILD, base="spec/feature/1", cwd=tmp_path, **BODIES)

    assert forge.bodies == [BODIES["body"]]
