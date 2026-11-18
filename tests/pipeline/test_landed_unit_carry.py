"""A unit that landed off the default branch is carried onto it (spec: landed-carry).

Real git in temporary repositories (the landing world the re-check tests share), the forge
stand-in for the pull request, and a stub resolver."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path

import pytest

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.carry import carry, carry_held
from agent_build_kit.pipeline.restack import RestackConflict
from agent_build_kit.pipeline.unit_store import Cause, Pull
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED, SETTLING
from tests.factories import commit_files, git
from tests.forges.stand_in import StandInForge
from tests.landing_world import CHILD, CHILD_CHANGE, Landing

CARRY_BRANCH = f"spec/{CHILD}/carry"
CARRY_PR = 7


class Carrying:
    """A held unit, the forge stand-in, and the carry call over them."""

    def __init__(self, root: Path, *, as_merge_commit: bool = False) -> None:
        self.landing = Landing(
            root,
            child_state=HELD,
            cause=Cause.LANDED_OFF_DEFAULT,
            as_merge_commit=as_merge_commit,
        )
        self.landing.store.set_pulls(
            CHILD, (Pull(number=2, role="original", merge_sha=self.landing.child_sha),)
        )
        self.forge = StandInForge(number=CARRY_PR)
        self.worktrees = root / "worktrees"
        self.prompts: list[str] = []
        self.resolver: Callable[..., None] = self.resolve

    @property
    def clone(self) -> Path:
        return self.landing.clone

    def resolve(self, prompt: str, *, cwd: Path) -> None:
        """The stub resolver: keeps both sides of the one conflicted file it is asked about."""
        self.prompts.append(prompt)
        (cwd / "a.txt").write_text("two and three\n")

    def run(self) -> None:
        carry(
            self.landing.store,
            CHILD,
            forge=self.forge,
            repo_id=self.forge.repo_id(),
            repo=self.clone,
            default_branch="main",
            worktrees=self.worktrees,
            resolve=self.resolver,
        )

    def round(self) -> list[str]:
        """The round's carry step over the held unit, as the poll pass runs it."""
        return carry_held(
            self.landing.store,
            repos={"app": self.clone},
            forge_of=lambda repo: (self.forge, self.forge.repo_id()),
            default_of=lambda repo: "main",
            worktrees=self.worktrees,
            claim=lambda unit: nullcontext(),
            resolver_for=lambda unit: self.resolver,
            log=lambda _line: None,
        )

    def on_carry_branch(self, name: str) -> str:
        return git(self.clone, "show", f"{CARRY_BRANCH}:{name}")


@pytest.fixture
def carrying(tmp_path: Path) -> Carrying:
    return Carrying(tmp_path)


def test_a_held_unit_gets_a_carry_branch_off_the_default_branch_with_its_commit(
    carrying: Carrying,
) -> None:
    carrying.run()

    assert carrying.on_carry_branch("a.txt") == CHILD_CHANGE["a.txt"].strip()
    assert git(carrying.clone, "merge-base", "--is-ancestor", "main", CARRY_BRANCH) == ""


def test_the_carry_opens_a_pull_request_against_the_default_branch(carrying: Carrying) -> None:
    carrying.run()

    assert [(c["head"], c["base"]) for c in carrying.forge.created] == [(CARRY_BRANCH, "main")]


def test_the_unit_is_in_review_on_the_carry_with_the_first_pull_request_in_its_history(
    carrying: Carrying,
) -> None:
    carrying.run()

    unit = carrying.landing.store.get(CHILD)
    assert (unit.state, unit.cause, unit.pr) == (IN_REVIEW, "carried", CARRY_PR)
    assert [(p.number, p.role) for p in unit.pulls] == [(2, "original"), (CARRY_PR, "carry")]


def test_the_carry_keeps_the_commit_the_first_pull_request_recorded(carrying: Carrying) -> None:
    carrying.run()

    first = carrying.landing.store.get(CHILD).pulls[0]
    assert first.merge_sha == carrying.landing.child_sha


def test_a_merge_commit_is_picked_against_its_first_parent(tmp_path: Path) -> None:
    carrying = Carrying(tmp_path, as_merge_commit=True)

    carrying.run()

    assert carrying.on_carry_branch("b.txt") == CHILD_CHANGE["b.txt"].strip()


def test_a_conflict_asks_the_resolver_about_the_conflicted_files_only(tmp_path: Path) -> None:
    carrying = Carrying(tmp_path)
    carrying.landing.land_on_main({"a.txt": "three\n"})

    carrying.run()

    assert len(carrying.prompts) == 1
    assert "a.txt" in carrying.prompts[0]
    assert "b.txt" not in carrying.prompts[0]


def test_a_conflict_carries_on_with_the_resolvers_answer(tmp_path: Path) -> None:
    carrying = Carrying(tmp_path)
    carrying.landing.land_on_main({"a.txt": "three\n"})

    carrying.run()

    assert carrying.on_carry_branch("a.txt") == "two and three"
    assert [c["head"] for c in carrying.forge.created] == [CARRY_BRANCH]


def test_a_unit_already_carrying_is_not_carried_again(carrying: Carrying) -> None:
    carrying.run()

    carrying.run()

    assert len(carrying.forge.created) == 1


def test_a_cherry_pick_that_leaves_nothing_opens_no_pull_request(tmp_path: Path) -> None:
    carrying = Carrying(tmp_path)
    carrying.landing.land_on_main(CHILD_CHANGE)

    carrying.run()

    assert carrying.forge.created == []


def test_a_cherry_pick_that_leaves_nothing_records_the_unit_merged(tmp_path: Path) -> None:
    carrying = Carrying(tmp_path)
    carrying.landing.land_on_main(CHILD_CHANGE)

    carrying.run()

    assert carrying.landing.store.get(CHILD).state == MERGED


def test_the_merge_sha_stays_unset_until_the_carry_merges(carrying: Carrying) -> None:
    carrying.run()

    unit = carrying.landing.store.get(CHILD)
    assert (unit.state, unit.merge_sha) == (IN_REVIEW, None)


def test_the_merge_sha_becomes_the_commit_the_carry_merged_as(carrying: Carrying) -> None:
    carrying.run()
    carry_merged_as = carrying.landing.land_on_main({"c.txt": "carried\n"})

    events.on_merged(
        CARRY_PR,
        repo="app",
        store=carrying.landing.store,
        restack=lambda **kwargs: None,
        merge_commit=carry_merged_as,
        merge_record=lambda unit: (unit.merge_sha, None),
        log=lambda _line: None,
    )

    unit = carrying.landing.store.get(CHILD)
    assert (unit.state, unit.merge_sha) == (SETTLING, carry_merged_as)


def test_the_round_carries_a_held_unit_whose_work_is_not_on_the_default_branch(
    carrying: Carrying,
) -> None:
    carried = carrying.round()

    assert carried == [CHILD]
    assert [(c["head"], c["base"]) for c in carrying.forge.created] == [(CARRY_BRANCH, "main")]


def test_the_round_records_merged_a_held_unit_whose_work_is_already_there(
    tmp_path: Path,
) -> None:
    carrying = Carrying(tmp_path)
    carrying.landing.land_on_main(CHILD_CHANGE)

    carrying.round()

    assert carrying.landing.store.get(CHILD).state == MERGED
    assert carrying.forge.created == []


def test_a_second_round_does_not_start_a_second_carry(carrying: Carrying) -> None:
    carrying.round()

    carrying.round()

    assert len(carrying.forge.created) == 1


def leave_markers(prompt: str, *, cwd: Path, **_: object) -> None:
    """A resolver that gives up and leaves the conflict in the file."""
    (cwd / "a.txt").write_text("<<<<<<< ours\n")


def test_a_resolution_that_leaves_conflict_markers_opens_no_pull_request(
    tmp_path: Path,
) -> None:
    carrying = Carrying(tmp_path)
    carrying.landing.land_on_main({"a.txt": "three\n"})
    carrying.resolver = leave_markers

    with pytest.raises(RestackConflict):
        carrying.run()

    unit = carrying.landing.store.get(CHILD)
    assert carrying.forge.created == []
    assert (unit.state, unit.cause) == (HELD, Cause.LANDED_OFF_DEFAULT)


def test_a_round_leaves_a_unit_held_whose_conflict_cannot_be_resolved(tmp_path: Path) -> None:
    carrying = Carrying(tmp_path)
    carrying.landing.land_on_main({"a.txt": "three\n"})
    carrying.resolver = leave_markers

    assert carrying.round() == []

    unit = carrying.landing.store.get(CHILD)
    assert carrying.forge.created == []
    assert (unit.state, unit.cause) == (HELD, Cause.LANDED_OFF_DEFAULT)


def test_a_carry_abandoned_in_one_round_is_not_asked_of_the_resolver_again(
    tmp_path: Path,
) -> None:
    carrying = Carrying(tmp_path)
    carrying.landing.land_on_main({"a.txt": "three\n"})
    carrying.resolver = leave_markers
    carrying.round()
    asked: list[str] = []
    carrying.resolver = lambda prompt, *, cwd, **_: asked.append(prompt)

    carrying.round()

    assert asked == []


def test_a_resolver_that_raises_aborts_the_cherry_pick_and_opens_no_pull_request(
    tmp_path: Path,
) -> None:
    carrying = Carrying(tmp_path)
    carrying.landing.land_on_main({"a.txt": "three\n"})

    def broken(prompt: str, *, cwd: Path, **_: object) -> None:
        raise RuntimeError("the model is down")

    carrying.resolver = broken

    with pytest.raises(RestackConflict):
        carrying.run()

    assert carrying.forge.created == []
    assert carrying.landing.store.get(CHILD).state == HELD


def test_the_carry_branch_starts_from_the_remote_default_branch_not_a_stale_local_one(
    tmp_path: Path,
) -> None:
    carrying = Carrying(tmp_path)
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(tmp_path / "origin.git"), str(other))
    git(other, "config", "user.email", "t@t.t")
    git(other, "config", "user.name", "t")
    commit_files(other, "elsewhere", {"c.txt": "elsewhere\n"})
    git(other, "push", "-q", "origin", "main")
    origin_head = git(other, "rev-parse", "HEAD")

    carrying.run()

    assert git(carrying.clone, "merge-base", "--is-ancestor", origin_head, CARRY_BRANCH) == ""


def test_the_carry_pull_request_names_the_pull_request_that_landed_off_the_default_branch(
    carrying: Carrying,
) -> None:
    carrying.run()

    assert "#2" in carrying.forge.created[0]["body"]
