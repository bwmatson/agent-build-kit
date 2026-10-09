"""The forge for a repo whose pull requests are kept in the state directory."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from pathlib import Path

from agent_build_kit.config import RepoConfig
from agent_build_kit.forges.base import (
    FileChange,
    Label,
    PullRequest,
    RepoId,
    ReviewNote,
    Run,
    Stack,
)


class LocalForge:
    name: str = "local"
    implemented: bool = True
    client: str | None = None
    deletes_head_branch_on_merge: bool = False
    supports_stacks: bool = False
    denied_commands: tuple[tuple[str, ...], ...] = ()
    read_commands: tuple[tuple[str, ...], ...] = ()
    requires: tuple[str, ...] = ()
    ci_name: str = "no CI"
    description_limit: int = 65_536

    def __init__(self, state_dir: Path | None = None) -> None:
        # None is the active workspace's state directory.
        self.state_dir = state_dir

    def parse_remote(self, url: str) -> RepoId | None:
        raise NotImplementedError

    def identity(self, repo: RepoConfig) -> RepoId:
        raise NotImplementedError

    def config_entry(self, repo: RepoId) -> dict[str, object]:
        raise NotImplementedError

    def web_url(self, repo: RepoId, *, pr: int | None = None) -> str:
        raise NotImplementedError

    def check_access(self, repo: RepoId, *, run: Run | None = None) -> str:
        raise NotImplementedError

    def access_fix(self, repo: RepoId) -> str:
        raise NotImplementedError

    def merge_guard(self, repo: RepoId, *, branch: str, run: Run | None = None) -> str:
        raise NotImplementedError

    def find_pr(self, repo: RepoId, *, head: str) -> int | None:
        raise NotImplementedError

    def comment_exists(
        self, repo: RepoId, pr: int, marker: str, body: str, *, reply_to: str | None = None
    ) -> str | None:
        raise NotImplementedError

    def create_pr(self, repo: RepoId, *, head: str, base: str, title: str, body: str) -> int:
        raise NotImplementedError

    def update_pr(self, repo: RepoId, pr: int, *, base: str = "", body: str = "") -> None:
        raise NotImplementedError

    def list_prs(self, repo: RepoId, *, head_prefix: str = "") -> list[PullRequest]:
        raise NotImplementedError

    def pr_files(self, repo: RepoId, pr: int) -> list[str]:
        raise NotImplementedError

    def pr_changes(self, repo: RepoId, pr: int) -> list[FileChange]:
        raise NotImplementedError

    def review_notes(self, repo: RepoId, pr: int) -> list[ReviewNote]:
        raise NotImplementedError

    def post_reply(self, repo: RepoId, pr: int, *, note_id: str, body: str) -> list[str]:
        raise NotImplementedError

    def post_comment(self, repo: RepoId, pr: int, *, body: str) -> list[str]:
        raise NotImplementedError

    def post_status(
        self, repo: RepoId, *, sha: str, ok: bool, context: str, description: str, head: str = ""
    ) -> None:
        raise NotImplementedError

    def failed_check_logs(self, repo: RepoId, pull: PullRequest) -> str:
        raise NotImplementedError

    def rerun_checks(self, repo: RepoId, pull: PullRequest) -> None:
        raise NotImplementedError

    def delete_remote_branch(self, repo: RepoId, branch: str) -> None:
        raise NotImplementedError

    def add_label(self, repo: RepoId, pr: int, label: Label) -> None:
        raise NotImplementedError

    def set_exclusive_label(
        self, repo: RepoId, pr: int, label: Label, *, family: Collection[str]
    ) -> None:
        raise NotImplementedError

    def remove_label(self, repo: RepoId, pr: int, name: str) -> None:
        raise NotImplementedError

    def set_draft(self, repo: RepoId, pr: int, draft: bool) -> None:
        raise NotImplementedError

    def close_pr(self, repo: RepoId, pr: int) -> None:
        raise NotImplementedError

    def stack_of(self, repo: RepoId, pr: int) -> Stack | None:
        raise NotImplementedError

    def create_stack(self, repo: RepoId, pulls: Sequence[int]) -> Stack:
        raise NotImplementedError

    def add_to_stack(self, repo: RepoId, stack: int, pulls: Sequence[int]) -> Stack:
        raise NotImplementedError
