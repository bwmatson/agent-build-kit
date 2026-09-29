"""A code host that is neither GitHub nor Azure DevOps: a plain class
satisfying the Protocol, as a third forge or a test double would.

A call site given one proves it reaches its host through the seam alone —
nothing it sends can be a `gh` flag, because nothing here reads one. What it
was asked is kept as plain records; what it answers, the test decides. The
argv each real forge builds is asserted in that forge's own tests.

The methods a test does not configure answer emptily rather than raising: a
double that blows up on an unrelated call makes tests assert on call order
they do not care about.
"""

from __future__ import annotations

from collections.abc import Collection

from agent_build_kit.config import RepoConfig
from agent_build_kit.forges import Forge, PullRequest, RepoId, ReviewNote
from agent_build_kit.forges.base import Run


class StandInForge:
    name: str = "stand_in"
    implemented: bool = True
    deletes_head_branch_on_merge: bool = False
    denied_commands: tuple[tuple[str, ...], ...] = ()

    def __init__(
        self,
        *,
        existing: int | None = None,
        number: int = 7,
        prs: Collection[PullRequest] = (),
        notes: Collection[ReviewNote] = (),
        files: Collection[str] = (),
        logs: str = "",
        access: str = "",
        failing_replies: Collection[str] = (),
    ) -> None:
        self.existing = existing
        self.number = number
        self.prs = list(prs)
        self.notes = list(notes)
        self.files = list(files)
        self.logs = logs
        self.access = access
        self.failing_replies = failing_replies
        self.created: list[dict] = []
        self.updated: list[dict] = []
        self.replies: list[tuple[str, str]] = []
        self.comments: list[str] = []
        self.statuses: list[dict] = []
        self.deleted: list[str] = []

    # --- identity -----------------------------------------------------------

    def parse_remote(self, url: str) -> RepoId | None:
        return self.repo_id() if url else None

    def identity(self, repo: RepoConfig) -> RepoId:
        return self.repo_id()

    def repo_id(self) -> RepoId:
        return RepoId(forge=self.name, account="example", name="app")

    def web_url(self, repo: RepoId, *, pr: int | None = None) -> str:
        base = f"https://stand-in.example/{repo.account}/{repo.name}"
        return f"{base}/pull/{pr}" if pr else base

    def check_access(self, repo: RepoId, *, run: Run | None = None) -> str:
        return self.access

    def access_fix(self, repo: RepoId) -> str:
        return "sign in to the stand-in host"

    def merge_guard(self, repo: RepoId, *, branch: str) -> str:
        return ""

    # --- pull requests ------------------------------------------------------

    def list_prs(self, repo: RepoId, *, head_prefix: str = "") -> list[PullRequest]:
        return [pr for pr in self.prs if pr.head.startswith(head_prefix)]

    def find_pr(self, repo: RepoId, *, head: str) -> int | None:
        return self.existing

    def create_pr(self, repo: RepoId, *, head: str, base: str, title: str, body: str) -> int:
        self.created.append({"head": head, "base": base, "title": title, "body": body})
        return self.number

    def update_pr(self, repo: RepoId, pr: int, *, base: str = "", body: str = "") -> None:
        self.updated.append({"pr": pr, "base": base, "body": body})

    # --- review -------------------------------------------------------------

    def pr_files(self, repo: RepoId, pr: int) -> list[str]:
        return list(self.files)

    def review_notes(self, repo: RepoId, pr: int) -> list[ReviewNote]:
        return self.notes

    def post_reply(self, repo: RepoId, pr: int, *, note_id: str, body: str) -> list[str]:
        if note_id in self.failing_replies:
            raise RuntimeError("404 Not Found")
        self.replies.append((note_id, body))
        return [f"reply-{note_id}", f"review-{note_id}"]

    def post_comment(self, repo: RepoId, pr: int, *, body: str) -> list[str]:
        self.comments.append(body)
        return ["comment-1"]

    def post_status(
        self, repo: RepoId, *, sha: str, ok: bool, context: str, description: str
    ) -> None:
        self.statuses.append(
            {"sha": sha, "ok": ok, "context": context, "description": description}
        )

    # --- cleanup ------------------------------------------------------------

    def failed_check_logs(self, repo: RepoId, pull: PullRequest) -> str:
        return self.logs

    def delete_remote_branch(self, repo: RepoId, branch: str) -> None:
        self.deleted.append(branch)


def lookup(forge: StandInForge):
    """A `for_repo` the `wiring.build_*` factories accept: every repo name
    resolves to this one stand-in."""

    def for_repo(repo: str) -> tuple[StandInForge, RepoId]:
        return forge, forge.repo_id()

    return for_repo


_: Forge = StandInForge()
