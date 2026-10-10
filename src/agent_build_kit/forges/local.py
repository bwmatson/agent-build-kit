"""The forge for a repo whose pull requests are kept in the state directory.

Pull requests live in `local-prs.json`, one list per repo. Review comments and decisions are
read from the review store the web UI writes. A merge is a person's, made with git; once git
shows it the forge records it, with the branch's tip, so deleting the branch loses neither.
"""

from __future__ import annotations

import hashlib
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
    key,
)
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.units import MERGED, build_ref

if TYPE_CHECKING:
    from agent_build_kit.config import RepoConfig
    from agent_build_kit.pipeline.unit_store import StoredUnit
    from agent_build_kit.serve.review import Review
    from agent_build_kit.settings import Settings

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

    def api_url(self, machine: Settings) -> str | None:
        return None

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
        # The checkout's full path, hashed, tells apart two repos whose directories share a name.
        where = hashlib.sha1(str(repo.path.expanduser().resolve()).encode()).hexdigest()[:8]
        return RepoId(forge=self.name, account="local", name=repo.path.name, project=where)

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

    def _checkout(self, repo: RepoId) -> Path | None:
        """Where the repo is checked out, found by identity among the active workspace's repos."""
        from agent_build_kit import config

        for candidate in config.active().repos.values():
            if candidate.forge == self.name and self.identity(candidate) == repo:
                return candidate.path.expanduser()
        return None

    # --- pull requests --------------------------------------------------------------

    def find_pr(self, repo: RepoId, *, head: str) -> int | None:
        found = [int(str(p["number"])) for p in self._pulls(repo) if _is_open(p, head)]
        return max(found) if found else None

    def record(self, repo: RepoId, pr: int) -> dict[str, object] | None:
        """The pull request as stored, or None when this forge holds no such number."""
        return next((dict(p) for p in self._pulls(repo) if p["number"] == pr), None)

    def state_of(self, repo: RepoId, pr: int) -> str | None:
        """The state git shows for the pull request, worked out without recording it; None
        when this forge holds no such number."""
        pull = self.record(repo, pr)
        if pull is None:
            return None
        checkout = self._checkout(repo)
        if pull["state"] == "open" and checkout is not None and _seen(checkout, pull)[1]:
            return MERGED
        return str(pull["state"])

    def _settle(self, repo: RepoId) -> None:
        """Write down what git shows: the branch's own tip while it has work beyond the trunk,
        and merged once the trunk holds that work, so deleting the branch afterwards loses
        neither."""
        checkout = self._checkout(repo)
        if checkout is None:
            return
        found: dict[int, Stored] = {}
        for pull in self._pulls(repo):
            if pull["state"] != "open":
                continue
            tip, merged = _seen(checkout, pull)
            settled: Stored = {}
            if tip and tip != pull.get("tip"):
                settled["tip"] = tip
            if merged:
                settled["state"] = MERGED
            if settled:
                found[int(str(pull["number"]))] = settled
        if not found:
            return

        def write(pulls: list[Stored]) -> None:
            for pull in pulls:
                number = int(str(pull["number"]))
                if number in found and pull["state"] == "open":
                    pull.update(found[number])

        self._change(repo, write)

    def diff(self, repo: RepoId, pr: int) -> str | None:
        """The branch's own work over its base, as `git diff` prints it; None when the
        pull request, the checkout or either ref is missing."""
        pull = self.record(repo, pr)
        checkout = self._checkout(repo)
        if pull is None or checkout is None:
            return None
        trunk = build_ref(checkout, str(pull["base"]))
        shown = git(checkout, "diff", f"{trunk}...refs/heads/{pull['head']}", check=False)
        return None if shown.returncode else shown.stdout

    def comment_exists(
        self, repo: RepoId, pr: int, marker: str, body: str, *, reply_to: str | None = None
    ) -> str | None:
        for pull in self._pulls(repo):
            if pull["number"] == pr:
                return next(
                    (
                        str(c["id"])
                        for c in _comments(pull)
                        if c["body"] == body and c["reply_to"] == reply_to and marker in body
                    ),
                    None,
                )
        return None

    def create_pr(self, repo: RepoId, *, head: str, base: str, title: str, body: str) -> int:
        checkout = self._checkout(repo)
        tip = _seen(checkout, {"head": head, "base": base})[0] if checkout else ""

        def add(pulls: list[Stored]) -> int:
            number = max((int(str(p["number"])) for p in pulls), default=0) + 1
            pulls.append(
                {
                    "number": number,
                    "head": head,
                    "base": base,
                    "title": title,
                    "body": body,
                    "state": "open",
                    **({"tip": tip} if tip else {}),
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
                        pull["body"] = body

        self._change(repo, update)

    def list_prs(self, repo: RepoId, *, head_prefix: str = "") -> list[PullRequest]:
        from agent_build_kit.pipeline.ui_review import with_ui_review
        from agent_build_kit.pipeline.unit_store import UnitStore
        from agent_build_kit.serve.review import ReviewStore

        self._settle(repo)
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
            # A unit's branch is unique across repos, so this needs no repo name.
            unit: StoredUnit | None = next(
                (u for u in units.all() if u.pr == pull.number and u.branch == pull.head), None
            )
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
        return self._post(repo, pr, body, note_id)

    def post_comment(self, repo: RepoId, pr: int, *, body: str) -> list[str]:
        return self._post(repo, pr, body, None)

    def _post(self, repo: RepoId, pr: int, body: str, reply_to: str | None) -> list[str]:
        """Keep a comment on the pull request and return its id; none for a pull request
        this forge does not hold, as a host's refused post."""

        def add(pulls: list[Stored]) -> list[str]:
            for pull in pulls:
                if pull["number"] == pr:
                    comments = _comments(pull)
                    made = f"local-{pr}-{len(comments) + 1}"
                    comments.append({"id": made, "body": body, "reply_to": reply_to})
                    pull["comments"] = comments
                    return [made]
            return []

        return self._change(repo, add)

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


def _seen(checkout: Path, pull: Stored) -> tuple[str, bool]:
    """The tip to remember for an open pull request, and whether the trunk holds its work.

    The tip is the branch's current one only while that has commits of its own beyond the trunk.
    A branch the pipeline reset onto the trunk, or one a person deleted, keeps the tip stored
    before, and the merge is judged on that: an ancestor of the trunk (a merge commit or a
    fast-forward), or its change found there by patch identity (a squash)."""
    trunk = build_ref(checkout, str(pull["base"]))
    if not _commit(checkout, trunk):
        return "", False
    current = _commit(checkout, f"refs/heads/{pull['head']}")
    own = current if current and not _is_ancestor(checkout, current, trunk) else ""
    tip = own or str(pull.get("tip", ""))
    if not tip or not _commit(checkout, tip):
        return own, False
    return own, _in_trunk(checkout, tip, trunk)


def _commit(checkout: Path, ref: str) -> str:
    found = git(checkout, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False)
    return "" if found.returncode else found.stdout.strip()


def _is_ancestor(checkout: Path, ancestor: str, ref: str) -> bool:
    return not git(checkout, "merge-base", "--is-ancestor", ancestor, ref, check=False).returncode


def _in_trunk(checkout: Path, tip: str, trunk: str) -> bool:
    """Is the tip in the trunk, or its change found there by patch identity: the whole branch as
    one commit (a squash), or each of its commits on its own (a rebase)?"""
    if _is_ancestor(checkout, tip, trunk):
        return True
    fork = git(checkout, "merge-base", trunk, tip, check=False).stdout.strip()
    ours = (
        _patch_ids(checkout, git(checkout, "diff", fork, tip, check=False).stdout) if fork else []
    )
    if not ours:
        return False
    since = git(checkout, "log", "-p", "--no-merges", f"{fork}..{trunk}", check=False).stdout
    if ours[0] in _patch_ids(checkout, since):
        return True
    marks = git(checkout, "cherry", trunk, tip, check=False).stdout.split("\n")
    marks = [line for line in marks if line]
    return bool(marks) and all(line.startswith("-") for line in marks)


def _patch_ids(checkout: Path, patch: str) -> list[str]:
    """The stable patch id of each commit in `patch`, as `git patch-id` reads it."""
    found = git(checkout, "patch-id", "--stable", check=False, input=patch)
    return [line.split()[0] for line in found.stdout.splitlines() if line.split()]


def _comments(pull: Stored) -> list[Stored]:
    comments = pull.get("comments", [])
    return comments if isinstance(comments, list) else []


def _is_open(pull: Stored, head: str) -> bool:
    return pull["head"] == head and pull["state"] == "open"


FORGE = LocalForge()
