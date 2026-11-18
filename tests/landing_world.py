"""The world the landing re-check tests share: an origin and a clone, a parent unit's branch with
the child's merge on it, and a store holding the child in the state under test."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import MERGED, SETTLING, UnitState
from tests.factories import commit_files, git, init_repo, stored_unit

PARENT = "feature/1"
CHILD = "feature/2"
BASE = {"a.txt": "one\n", "b.txt": "one\n"}
CHILD_CHANGE = {"a.txt": "two\n", "b.txt": "two\n"}


class Landing:
    """An origin and a clone, a parent branch with the child's merge commit on it, and a store
    holding the child in the state under test. The child's merge is a plain commit, or with
    `as_merge_commit` a `--no-ff` merge of a side branch."""

    def __init__(
        self,
        root: Path,
        *,
        child_state: UnitState,
        cause: Cause | None,
        as_merge_commit: bool = False,
    ) -> None:
        origin = root / "origin.git"
        origin.mkdir(parents=True)
        git(origin, "init", "-q", "--bare", "-b", "main")
        self.clone = init_repo(root / "clone")
        git(self.clone, "remote", "add", "origin", str(origin))
        commit_files(self.clone, "base", BASE)
        git(self.clone, "push", "-q", "origin", "main")
        git(self.clone, "checkout", "-q", "-b", f"spec/{PARENT}")
        if as_merge_commit:
            git(self.clone, "checkout", "-q", "-b", "child")
            commit_files(self.clone, "child", CHILD_CHANGE)
            git(self.clone, "checkout", "-q", f"spec/{PARENT}")
            git(self.clone, "merge", "-q", "--no-ff", "-m", "merge child", "child")
        else:
            commit_files(self.clone, "child", CHILD_CHANGE)
        self.child_sha = git(self.clone, "rev-parse", "HEAD")
        git(self.clone, "push", "-q", "origin", f"spec/{PARENT}")
        git(self.clone, "checkout", "-q", "main")
        self.store = UnitStore(root / "units.json")
        self.store.upsert(
            [
                stored_unit(PARENT, change="feature"),
                stored_unit(CHILD, change="feature", depends_on=(PARENT,)),
            ]
        )
        self.store.set_state(PARENT, MERGED, pr=1, branch=f"spec/{PARENT}")
        self.store.set_state(CHILD, child_state, pr=2, branch=f"spec/{CHILD}", cause=cause)
        self.store.set_merge_record(CHILD, self.child_sha, None)
        if child_state == SETTLING:
            self.store.set_settling_behind(CHILD, f"spec/{PARENT}")
        self.resumed: list[tuple[str, str]] = []

    def carry_parent_to_main(self) -> None:
        """The parent's branch merged into the default branch, as a carry or a person's merge
        leaves it: the child's commit is then an ancestor of `main`."""
        git(self.clone, "checkout", "-q", "main")
        git(self.clone, "merge", "-q", "--no-ff", "-m", "carry", f"spec/{PARENT}")
        git(self.clone, "push", "-q", "origin", "main")

    def land_on_main(self, files: dict[str, str]) -> str:
        """A commit on the default branch with other history than the unit's, as a squash
        leaves it; the origin's head after it."""
        git(self.clone, "checkout", "-q", "main")
        commit_files(self.clone, "squash", files)
        git(self.clone, "push", "-q", "origin", "main")
        return git(self.clone, "rev-parse", "HEAD")

    def resume(self, unit: StoredUnit, kind: str, reason: str, feedback: str) -> bool:
        self.resumed.append((unit.id, kind))
        return True

    def recheck(self) -> list[str]:
        return events.recheck_landings(
            self.store,
            repos={"app": self.clone},
            merge_record=lambda unit: (unit.merge_sha, None),
            resume=self.resume,
            log=lambda _line: None,
        )
