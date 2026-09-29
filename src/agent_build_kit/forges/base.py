"""What a code host has to answer, and the values it answers with.

A workspace can hold repos on more than one host - GitHub and Azure DevOps here
- so the pipeline asks a forge rather than shelling `gh`. Two rules shape this
file:

The forge returns **typed values, not the host's JSON**. Every `mergedAt` and
`CHANGES_REQUESTED` the pipeline used to read is an attribute below, so a second
host is a translation at one boundary rather than a second document shape
running through the poller, the rework loop and the runner.

It is a `Protocol`, not a base class, for the reason `runtimes.AgentRuntime`
and `ToolchainProfile` are: implementations own their own code, a test double
is a plain class (`tests/forges/stand_in.py`), and the shared parts are free
functions here rather than inherited behaviour.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from agent_build_kit.model import Frozen

if TYPE_CHECKING:
    # config imports this package to check a repo's forge at load.
    from agent_build_kit.config import RepoConfig

# Injected so a check can be tested against recorded answers, the way
# `tier2.post_status` and the `wiring.build_*` factories already take one.
Run = Callable[..., subprocess.CompletedProcess]


class RepoId(Frozen):
    """A repo, named the way its host names it, decoded.

    GitHub has two segments and Azure DevOps three; `project` is empty on the
    hosts that have no such thing. Decoded, because an Azure remote
    percent-encodes a project with a space in it and every API and CLI call
    wants the readable form back.
    """

    forge: str
    account: str
    name: str
    project: str = ""


class PullRequest(Frozen):
    """One pull request, as the poller needs to see it.

    `state` uses the vocabulary in `pipeline/units.py`, so nothing downstream
    learns a second set of words for the same three outcomes.
    """

    number: int
    head: str
    base: str
    state: str
    draft: bool = False
    labels: tuple[str, ...] = ()
    # Every comment and review id, opaque: the poller only ever diffs them.
    conversation: tuple[str, ...] = ()
    # The comment bodies, oldest first. A rework quotes the newest of them
    # when the reviewer left no inline notes, which is why they travel with
    # the poll rather than costing a second request. Review bodies are not
    # here: the rework path fetches those through `review_notes`, and having
    # them in both places would quote one twice.
    comment_bodies: tuple[str, ...] = ()
    review_decision: str = ""
    failing_checks: tuple[str, ...] = ()


class ReviewNote(Frozen):
    """One piece of review feedback, and whether it is still worth answering.

    `live` is the generalisation of GitHub's outdated-comment convention: it
    reports `line: null` once the code a comment sat on has changed, and Azure
    DevOps marks the thread resolved instead. Either way a rework should not be
    handed feedback it has already addressed.
    """

    id: str
    body: str
    path: str = ""
    line: int | None = None
    live: bool = True


class Forge(Protocol):
    """The host a repo lives on."""

    name: str
    # False while a forge is declared but unfinished: callers hold the unit
    # rather than failing it. The `node_npm` profile does the same.
    implemented: bool
    # Whether merging removes the source branch, which decides who cleans up.
    deletes_head_branch_on_merge: bool
    # Command prefixes no agent may run on any repo - merging, voting, and the
    # raw API escapes that reach both. Folded together by `denies`.
    denied_commands: tuple[tuple[str, ...], ...]

    def parse_remote(self, url: str) -> RepoId | None: ...

    def identity(self, repo: RepoConfig) -> RepoId: ...

    def web_url(self, repo: RepoId, *, pr: int | None = None) -> str: ...

    def check_access(self, repo: RepoId, *, run: Run | None = None) -> str: ...

    def access_fix(self, repo: RepoId) -> str: ...

    def merge_guard(self, repo: RepoId, *, branch: str) -> str: ...

    def find_pr(self, repo: RepoId, *, head: str) -> int | None: ...

    def create_pr(self, repo: RepoId, *, head: str, base: str, title: str, body: str) -> int: ...

    def update_pr(self, repo: RepoId, pr: int, *, base: str = "", body: str = "") -> None: ...

    def list_prs(self, repo: RepoId, *, head_prefix: str = "") -> list[PullRequest]: ...

    def pr_files(self, repo: RepoId, pr: int) -> list[str]:
        """The paths a PR touches, which is what `abk verify` checks a change
        against. Raises when the host cannot answer: an empty list reads as
        "this change touched nothing"."""
        ...

    def review_notes(self, repo: RepoId, pr: int) -> list[ReviewNote]: ...

    def post_reply(self, repo: RepoId, pr: int, *, note_id: str, body: str) -> list[str]: ...

    def post_comment(self, repo: RepoId, pr: int, *, body: str) -> list[str]: ...

    def post_status(
        self, repo: RepoId, *, sha: str, ok: bool, context: str, description: str
    ) -> None:
        """Publish one result against one commit.

        The description is truncated by the forge, not by its caller - every
        host has its own limit and a caller has no business knowing them.
        """
        ...

    def failed_check_logs(self, repo: RepoId, pull: PullRequest) -> str: ...

    def delete_remote_branch(self, repo: RepoId, branch: str) -> None: ...


def key(repo: RepoId) -> str:
    """The identity as one string, for the keys already written to disk.

    `own-posts.json` and the poller's state files key on this, so it stays
    `owner/name` on GitHub: changing it would orphan a running installation's
    record of which comments it wrote.
    """
    return "/".join(part for part in (repo.account, repo.project, repo.name) if part)
