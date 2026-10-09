"""The forge for a repo whose pull requests are kept in the state directory.

Pull requests live in `local-prs.json`, one list per repo. Review comments and decisions are
read from the review store the web UI writes. A merge is a person's, with git, and is not
recorded here.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from agent_build_kit.forges.base import (
    FileChange,
    Label,
    PullRequest,
    RepoId,
    ReviewNote,
    Run,
    Stack,
    fit_description,
    key,
)
from agent_build_kit.pipeline.file_lock import file_lock

if TYPE_CHECKING:
    from agent_build_kit.config import RepoConfig
    from agent_build_kit.pipeline.unit_store import StoredUnit
    from agent_build_kit.serve.review import Review

FILE = "local-prs.json"

T = TypeVar("T")
Stored = dict[str, object]


class LocalForge:
    name: str = "local"
    implemented: bool = True
    client: str | None = None
    deletes_head_branch_on_merge: bool = False
    supports_stacks: bool = False
    denied_commands: tuple[tuple[str, ...], ...] = ()
    read_commands: tuple[tuple[str, ...], ...] = (("abk", "pr", "view"), ("abk", "pr", "diff"))
    requires: tuple[str, ...] = ()
    ci_name: str = "no CI"
    description_limit: int = 65_536

    def __init__(self, state_dir: Path | None = None) -> None:
        # None is the active workspace's state directory.
        self._state_dir = state_dir

    @property
    def state_dir(self) -> Path:
        if self._state_dir is not None:
            return self._state_dir
        from agent_build_kit import config
        from agent_build_kit.installation import Installation

        root = config.active_root()
        if root is None:
            raise RuntimeError("the local forge needs an active workspace for its state directory")
        return Installation(config.active(), root).state_dir

    # --- the file -------------------------------------------------------------------

    def _path(self) -> Path:
        return self.state_dir / FILE

    def _read(self) -> dict[str, list[Stored]]:
        path = self._path()
        return json.loads(path.read_text()) if path.exists() else {}

    def _pulls(self, repo: RepoId) -> list[Stored]:
        return self._read().get(key(repo), [])

    def _change(self, repo: RepoId, change: Callable[[list[Stored]], T]) -> T:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(path.with_suffix(".lock")):
            stored = self._read()
            result = change(stored.setdefault(key(repo), []))
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(stored, indent=2))
            temporary.replace(path)
        return result

    # --- identity -------------------------------------------------------------------

    def parse_remote(self, url: str) -> RepoId | None:
        return None

    def identity(self, repo: RepoConfig) -> RepoId:
        return RepoId(forge=self.name, account="local", name=repo.path.name)

    def config_entry(self, repo: RepoId) -> dict[str, object]:
        return {}

    def web_url(self, repo: RepoId, *, pr: int | None = None) -> str:
        return ""

    def check_access(self, repo: RepoId, *, run: Run | None = None) -> str:
        return ""

    def access_fix(self, repo: RepoId) -> str:
        return ""

    def merge_guard(self, repo: RepoId, *, branch: str, run: Run | None = None) -> str:
        return ""

    # --- pull requests --------------------------------------------------------------

    def find_pr(self, repo: RepoId, *, head: str) -> int | None:
        found = [int(str(p["number"])) for p in self._pulls(repo) if _is_open(p, head)]
        return max(found) if found else None

    def comment_exists(
        self, repo: RepoId, pr: int, marker: str, body: str, *, reply_to: str | None = None
    ) -> str | None:
        return None

    def create_pr(self, repo: RepoId, *, head: str, base: str, title: str, body: str) -> int:
        def add(pulls: list[Stored]) -> int:
            number = max((int(str(p["number"])) for p in pulls), default=0) + 1
            pulls.append(
                {
                    "number": number,
                    "head": head,
                    "base": base,
                    "title": title,
                    "body": fit_description(body, self.description_limit),
                    "state": "open",
                }
            )
            return number

        return self._change(repo, add)

    def update_pr(self, repo: RepoId, pr: int, *, base: str = "", body: str = "") -> None:
        def update(pulls: list[Stored]) -> None:
            for pull in pulls:
                if pull["number"] == pr:
                    if base:
                        pull["base"] = base
                    if body:
                        pull["body"] = fit_description(body, self.description_limit)

        self._change(repo, update)

    def list_prs(self, repo: RepoId, *, head_prefix: str = "") -> list[PullRequest]:
        from agent_build_kit.pipeline.ui_review import unit_of, with_ui_review
        from agent_build_kit.pipeline.unit_store import UnitStore
        from agent_build_kit.serve.review import ReviewStore

        pulls = [
            PullRequest(
                number=int(str(p["number"])),
                head=str(p["head"]),
                base=str(p["base"]),
                state=str(p["state"]),
            )
            for p in self._pulls(repo)
            if str(p["head"]).startswith(head_prefix)
        ]
        units = UnitStore(self.state_dir / "units.json")
        reviews = ReviewStore(self.state_dir / "reviews")

        def review_of(pull: PullRequest) -> Review | None:
            unit: StoredUnit | None = unit_of(units, repo.name, pull.number)
            return reviews.read(unit.id) if unit else None

        return with_ui_review(lambda: pulls, review_of=review_of)()

    def pr_files(self, repo: RepoId, pr: int) -> list[str]:
        return []

    def pr_changes(self, repo: RepoId, pr: int) -> list[FileChange]:
        return []

    def review_notes(self, repo: RepoId, pr: int) -> list[ReviewNote]:
        # The pipeline takes the UI review's notes itself, placed at the branch tip.
        return []

    def post_reply(self, repo: RepoId, pr: int, *, note_id: str, body: str) -> list[str]:
        return []

    def post_comment(self, repo: RepoId, pr: int, *, body: str) -> list[str]:
        return []

    def close_pr(self, repo: RepoId, pr: int) -> None:
        def close(pulls: list[Stored]) -> None:
            for pull in pulls:
                if pull["number"] == pr:
                    pull["state"] = "closed"

        self._change(repo, close)

    # --- what has no local meaning --------------------------------------------------

    def post_status(
        self, repo: RepoId, *, sha: str, ok: bool, context: str, description: str, head: str = ""
    ) -> None:
        return None

    def failed_check_logs(self, repo: RepoId, pull: PullRequest) -> str:
        return ""

    def rerun_checks(self, repo: RepoId, pull: PullRequest) -> None:
        return None

    def delete_remote_branch(self, repo: RepoId, branch: str) -> None:
        return None

    def add_label(self, repo: RepoId, pr: int, label: Label) -> None:
        return None

    def set_exclusive_label(
        self, repo: RepoId, pr: int, label: Label, *, family: Collection[str]
    ) -> None:
        return None

    def remove_label(self, repo: RepoId, pr: int, name: str) -> None:
        return None

    def set_draft(self, repo: RepoId, pr: int, draft: bool) -> None:
        return None

    def stack_of(self, repo: RepoId, pr: int) -> Stack | None:
        return None

    def create_stack(self, repo: RepoId, pulls: Sequence[int]) -> Stack:
        return Stack(number=0, open=True, pulls=tuple(pulls))

    def add_to_stack(self, repo: RepoId, stack: int, pulls: Sequence[int]) -> Stack:
        return Stack(number=stack, open=True, pulls=tuple(pulls))


def _is_open(pull: Stored, head: str) -> bool:
    return pull["head"] == head and pull["state"] == "open"


FORGE = LocalForge()
