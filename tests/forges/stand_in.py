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

from collections.abc import Collection, Sequence

from agent_build_kit.config import RepoConfig
from agent_build_kit.forges import (
    Forge,
    Label,
    PullRequest,
    RepoId,
    ReviewNote,
    Stack,
    StackRefused,
)
from agent_build_kit.forges.base import PermittedCommand, Run


class StandInForge:
    name: str = "stand_in"
    implemented: bool = True
    client: str = ""
    deletes_head_branch_on_merge: bool = False
    supports_stacks: bool = False
    denied_commands: tuple[tuple[str, ...], ...] = ()
    read_commands: tuple[tuple[str, ...], ...] = ()
    permitted_commands: tuple[PermittedCommand, ...] = ()
    requires: tuple[str, ...] = ()
    ci_name: str = "the stand-in CI"

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
        guard: str = "",
        failing_replies: Collection[str] = (),
        close_error: str = "",
        comment_error: bool = False,
        label_errors: Collection[str] = (),
        draft_error: type[Exception] | None = None,
    ) -> None:
        self.existing = existing
        self.number = number
        self.prs = list(prs)
        self.notes = list(notes)
        self.files = list(files)
        self.logs = logs
        self.access = access
        self.guard = guard
        self.failing_replies = failing_replies
        self.close_error = close_error
        self.comment_error = comment_error
        # Which label calls fail: any of "add", "set", "remove".
        self.label_errors = label_errors
        # What `set_draft` raises, when it should.
        self.draft_error = draft_error
        # Each pull request's draft state now. The calls themselves are in
        # `calls`: this stand-in logs calls, not host writes, so a call to the
        # state a pull request is already in is logged too.
        self.is_draft: dict[int, bool] = {}
        # What the repo knows as a label, and every creation of one, so a test
        # can tell "created once" from "created each time".
        self.repo_labels: dict[str, Label] = {}
        self.label_creations: list[Label] = []
        # Every `add_label` call, creation or not, so a test can tell "added
        # once" from "added each time".
        self.added: list[tuple[int, Label]] = []
        # The labels on each pull request, by number.
        self.on_pr: dict[int, set[str]] = {}
        self.created: list[dict] = []
        self.updated: list[dict] = []
        self.replies: list[tuple[str, str]] = []
        self.comments: list[str] = []
        self.statuses: list[dict] = []
        self.deleted: list[str] = []
        self.closed: list[int] = []
        # Every post, close and draft call ("draft" or "ready"), in the order
        # they happened — a post and a close each land in their own list too,
        # but those don't tell apart a close that came first from one that
        # came after.
        self.calls: list[tuple[str, int]] = []

    # --- identity -----------------------------------------------------------

    def parse_remote(self, url: str) -> RepoId | None:
        return self.repo_id() if url else None

    def identity(self, repo: RepoConfig) -> RepoId:
        return self.repo_id()

    def repo_id(self) -> RepoId:
        return RepoId(forge=self.name, account="example", name="app")

    def config_entry(self, repo: RepoId) -> dict[str, object]:
        return {"slug": f"{repo.account}/{repo.name}"}

    def web_url(self, repo: RepoId, *, pr: int | None = None) -> str:
        base = f"https://stand-in.example/{repo.account}/{repo.name}"
        return f"{base}/pull/{pr}" if pr else base

    def check_access(self, repo: RepoId, *, run: Run | None = None) -> str:
        return self.access

    def access_fix(self, repo: RepoId) -> str:
        return "sign in to the stand-in host"

    def merge_guard(self, repo: RepoId, *, branch: str, run: Run | None = None) -> str:
        return self.guard

    # --- pull requests ------------------------------------------------------

    def list_prs(self, repo: RepoId, *, head_prefix: str = "") -> list[PullRequest]:
        return [
            pr.model_copy(
                update={"labels": tuple(sorted({*pr.labels, *self.on_pr.get(pr.number, ())}))}
            )
            for pr in self.prs
            if pr.head.startswith(head_prefix)
        ]

    def find_pr(self, repo: RepoId, *, head: str) -> int | None:
        return self.existing

    def create_pr(self, repo: RepoId, *, head: str, base: str, title: str, body: str) -> int:
        self.created.append({"head": head, "base": base, "title": title, "body": body})
        return self.number

    def update_pr(self, repo: RepoId, pr: int, *, base: str = "", body: str = "") -> None:
        self.updated.append({"pr": pr, "base": base, "body": body})

    # --- stacks -------------------------------------------------------------

    def stack_of(self, repo: RepoId, pr: int) -> Stack | None:
        return None

    def create_stack(self, repo: RepoId, pulls: Sequence[int]) -> Stack:
        raise StackRefused("the stand-in host has no stacks")

    def add_to_stack(self, repo: RepoId, stack: int, pulls: Sequence[int]) -> Stack:
        raise StackRefused("the stand-in host has no stacks")

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
        if self.comment_error:
            # What a real forge call answers when it fails: `GitHubForge`'s
            # `gh_json(..., default={})` swallows the error and this reads an
            # empty dict back; the Azure forge answers the same way when it
            # cannot read the response.
            return []
        self.comments.append(body)
        self.calls.append(("comment", pr))
        return ["comment-1"]

    def post_status(
        self, repo: RepoId, *, sha: str, ok: bool, context: str, description: str, head: str = ""
    ) -> None:
        self.statuses.append(
            {"sha": sha, "ok": ok, "context": context, "description": description, "head": head}
        )

    # --- cleanup ------------------------------------------------------------

    def failed_check_logs(self, repo: RepoId, pull: PullRequest) -> str:
        return self.logs

    def rerun_checks(self, repo: RepoId, pull: PullRequest) -> None:
        pass

    def delete_remote_branch(self, repo: RepoId, branch: str) -> None:
        self.deleted.append(branch)

    # --- labels -------------------------------------------------------------

    def _create(self, label: Label) -> None:
        if label.name not in self.repo_labels:
            self.repo_labels[label.name] = label
            self.label_creations.append(label)

    def add_label(self, repo: RepoId, pr: int, label: Label) -> None:
        if "add" in self.label_errors:
            raise RuntimeError("403 Forbidden")
        self._create(label)
        self.added.append((pr, label))
        self.on_pr.setdefault(pr, set()).add(label.name)

    def set_exclusive_label(
        self, repo: RepoId, pr: int, label: Label, *, family: Collection[str]
    ) -> None:
        if "set" in self.label_errors:
            raise RuntimeError("403 Forbidden")
        self._create(label)
        present = self.on_pr.setdefault(pr, set())
        present.difference_update(family)
        present.add(label.name)

    def remove_label(self, repo: RepoId, pr: int, name: str) -> None:
        if "remove" in self.label_errors:
            raise RuntimeError("403 Forbidden")
        self.on_pr.setdefault(pr, set()).discard(name)

    def set_draft(self, repo: RepoId, pr: int, draft: bool) -> None:
        if self.draft_error:
            raise self.draft_error("the stand-in host refuses drafts")
        self.is_draft[pr] = draft
        self.calls.append(("draft" if draft else "ready", pr))

    def close_pr(self, repo: RepoId, pr: int) -> None:
        if self.close_error:
            raise RuntimeError(self.close_error)
        self.closed.append(pr)
        self.calls.append(("close", pr))


def lookup(forge: StandInForge):
    """A `for_repo` the `wiring.build_*` factories accept: every repo name
    resolves to this one stand-in."""

    def for_repo(repo: str) -> tuple[StandInForge, RepoId]:
        return forge, forge.repo_id()

    return for_repo


_: Forge = StandInForge()
