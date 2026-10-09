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
from collections.abc import Callable, Collection, Sequence
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol

from agent_build_kit.model import Frozen

if TYPE_CHECKING:
    # config imports this package to check a repo's forge at load.
    from agent_build_kit.config import RepoConfig

# Injected so a check can be tested against recorded answers, the way
# `tier2.post_status` and the `wiring.build_*` factories already take one.
Run = Callable[..., subprocess.CompletedProcess]


DESCRIPTION_CUT_NOTE = "_Description cut to fit the host's limit._"


def fit_description(body: str, limit: int) -> str:
    """The body as it was if it fits, else cut on a line boundary to at most
    `limit` characters, with an open code fence and details block closed and a
    note saying so. A forge calls this on every description it sends."""
    if len(body) <= limit:
        return body
    lines = body.split("\n")
    for count in range(len(lines), 0, -1):
        kept = lines[:count]
        fenced = sum(line.lstrip().startswith("```") for line in kept) % 2 == 1
        depth = sum(line.strip().startswith("<details") for line in kept) - sum(
            "</details>" in line for line in kept
        )
        closers = (["```"] if fenced else []) + ["</details>"] * max(depth, 0)
        cut = "\n".join([*kept, *closers, "", DESCRIPTION_CUT_NOTE])
        if len(cut) <= limit:
            return cut
    return DESCRIPTION_CUT_NOTE[:limit]


class BaseMissing(RuntimeError):
    """A pull request refused because its base branch is not on the host.

    Distinct from any other refusal: the base was deleted — a parent merged —
    and the unit moves onto its current base rather than failing.
    """


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


class FileChange(Frozen):
    """One file a pull request changes, with the host's own line counts."""

    path: str
    additions: int
    deletions: int


class CheckStatus(StrEnum):
    """What a check came to, in the pipeline's words rather than a host's."""

    PASSED = "passed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PENDING = "pending"


class Check(Frozen):
    """One check on a pull request: a name, a status and the host's link, if any."""

    name: str
    status: CheckStatus
    url: str = ""


def _named(checks: Sequence[Check], status: CheckStatus) -> tuple[str, ...]:
    return tuple(sorted(check.name for check in checks if check.status == status))


def failing_names(checks: Sequence[Check]) -> tuple[str, ...]:
    """The names of the failed checks, sorted."""
    return _named(checks, CheckStatus.FAILED)


def cancelled_names(checks: Sequence[Check]) -> tuple[str, ...]:
    """The names of the cancelled checks, sorted."""
    return _named(checks, CheckStatus.CANCELLED)


def overall_result(checks: Sequence[Check]) -> str:
    """`failed`, `pending`, `passed`, or `none` for an empty list.

    A list of cancelled checks only reads as pending: a cancelled check is neither
    a pass nor a verdict, and the re-run path expects it to be waited on.
    """
    if not checks:
        return "none"
    statuses = {check.status for check in checks}
    if CheckStatus.FAILED in statuses:
        return "failed"
    if statuses & {CheckStatus.PENDING, CheckStatus.CANCELLED}:
        return "pending"
    return "passed"


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
    # Every check the host reports on the newest commit, each with a status.
    checks: tuple[Check, ...] = ()
    # Whether the host says the branch merges into its base; None while the
    # host has not worked it out, which is not a conflict.
    mergeable: bool | None = None


class Label(Frozen):
    """A label as a host keeps it: a name, a colour and what it means.

    `color` is six hex digits without the hash, which is how both hosts take it.
    """

    name: str
    color: str
    description: str = ""


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
    # Which side of the diff `line` numbers: a comment on a deleted line is on the old side.
    side: Literal["old", "new"] = "new"
    # The diff hunk holding `line`, from `@@` on; empty where the diff has none for it.
    hunk: str = ""


class Stack(Frozen):
    """A series of pull requests the host knows about, bottom first.

    `open` is false once every pull request in it has merged: such a stack
    cannot be extended, and a later unit of the chain starts a new one.
    """

    number: int
    open: bool
    pulls: tuple[int, ...]


# What every comment and reply the pipeline posts carries, so that a person's
# can be told from it and a post that landed can be found again.
COMMENT_MARKER = "<!-- spec-driven:reply -->"


class StackRefused(RuntimeError):
    """The host would not register a stack, and why.

    `concurrent` when another request was changing the same stack at the
    time - ordinary while ticks overlap, and worth asking again.
    """

    def __init__(self, reason: str, *, concurrent: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.concurrent = concurrent


class RegistersStacks(Protocol):
    """The slice of a host that registers the chain the pipeline builds."""

    # Whether the host has first-class stacks at all; where it does not,
    # nothing in this role is called.
    supports_stacks: bool

    def stack_of(self, repo: RepoId, pr: int) -> Stack | None: ...

    def create_stack(self, repo: RepoId, pulls: Sequence[int]) -> Stack: ...

    def add_to_stack(self, repo: RepoId, stack: int, pulls: Sequence[int]) -> Stack: ...


class Forge(RegistersStacks, Protocol):
    """The host a repo lives on."""

    name: str
    # False while a forge is declared but unfinished: callers hold the unit
    # rather than failing it. The `node_npm` profile does the same.
    implemented: bool
    # A command the forge needs on the machine (`gh`, `az`), which a scheduled
    # unit has to be able to find: it starts with no login environment, so a
    # client that is on a person's PATH is not necessarily on the unit's. None
    # (or empty) for a host reached over HTTP alone.
    client: str | None
    # Whether merging removes the source branch, which decides who cleans up.
    deletes_head_branch_on_merge: bool
    # Command prefixes no agent may run on any repo - merging, voting, and the
    # raw API escapes that reach both. Folded together by `denies`.
    denied_commands: tuple[tuple[str, ...], ...]
    # Command prefixes an agent may run to read its own PR. No prefix here may
    # overlap any forge's `denied_commands`; `wiring.allowed_tools` composes the
    # allow-list from them.
    read_commands: tuple[tuple[str, ...], ...]
    # The facts this forge cannot name a repo without, by their key in that
    # repo's abk.yaml entry (dotted for a nested block). A repo declaring this
    # forge and leaving one out fails at load, as a runtime selection does.
    requires: tuple[str, ...]
    # What this host's CI is called, for a pull request body that says who runs
    # the checks.
    ci_name: str
    # The most characters this host takes in a pull request description; the
    # forge cuts what it is handed to it with `fit_description`.
    description_limit: int

    def parse_remote(self, url: str) -> RepoId | None: ...

    def identity(self, repo: RepoConfig) -> RepoId: ...

    def config_entry(self, repo: RepoId) -> dict[str, object]:
        """The abk.yaml fields that name this repo, keyed as its entry.

        The other side of `requires`: what `abk init` writes, so a drafted
        file is one that loads.
        """
        ...

    def web_url(self, repo: RepoId, *, pr: int | None = None) -> str: ...

    def check_access(self, repo: RepoId, *, run: Run | None = None) -> str: ...

    def access_fix(self, repo: RepoId) -> str: ...

    def merge_guard(self, repo: RepoId, *, branch: str, run: Run | None = None) -> str:
        """What stops a merge on the server, or "" when nothing does.

        A host that answers "nothing" is answering honestly, and it is worth
        saying out loud: the command hook is then the only thing between an
        agent and its own merge.
        """
        ...

    def find_pr(self, repo: RepoId, *, head: str) -> int | None:
        """The pull request for a head branch: None only when the host answered
        that there is none, and a raise when it could not tell."""
        ...

    def comment_exists(
        self, repo: RepoId, pr: int, marker: str, body: str, *, reply_to: str | None = None
    ) -> str | None:
        """The id of the comment on a pull request (or, with `reply_to`, the reply
        to that note) that carries `marker` and exactly `body`; None when no
        comment matches. The read that shows a repeated post would duplicate."""
        ...

    def create_pr(self, repo: RepoId, *, head: str, base: str, title: str, body: str) -> int: ...

    def update_pr(self, repo: RepoId, pr: int, *, base: str = "", body: str = "") -> None: ...

    def list_prs(self, repo: RepoId, *, head_prefix: str = "") -> list[PullRequest]: ...

    def pr_files(self, repo: RepoId, pr: int) -> list[str]:
        """The paths a PR touches, which is what `abk verify` checks a change
        against. Raises when the host cannot answer: an empty list reads as
        "this change touched nothing"."""
        ...

    def pr_changes(self, repo: RepoId, pr: int) -> list[FileChange]:
        """Every file a PR changes with the host's additions and deletions for
        it, which is what a unit's actual size is summed from."""
        ...

    def review_notes(self, repo: RepoId, pr: int) -> list[ReviewNote]: ...

    def post_reply(self, repo: RepoId, pr: int, *, note_id: str, body: str) -> list[str]: ...

    def post_comment(self, repo: RepoId, pr: int, *, body: str) -> list[str]: ...

    def post_status(
        self, repo: RepoId, *, sha: str, ok: bool, context: str, description: str, head: str = ""
    ) -> None:
        """Publish one result against one commit.

        The description is truncated by the forge, not by its caller - every
        host has its own limit and a caller has no business knowing them.
        """
        ...

    def failed_check_logs(self, repo: RepoId, pull: PullRequest) -> str: ...

    def rerun_checks(self, repo: RepoId, pull: PullRequest) -> None:
        """Ask the host to run `pull`'s cancelled checks again."""
        ...

    def delete_remote_branch(self, repo: RepoId, branch: str) -> None: ...

    def add_label(self, repo: RepoId, pr: int, label: Label) -> None:
        """Put `label` on a pull request, creating it in the repo first when the
        repo lacks it. Raises where the host refuses."""
        ...

    def set_exclusive_label(
        self, repo: RepoId, pr: int, label: Label, *, family: Collection[str]
    ) -> None:
        """Put `label` on, and take off every other label named in `family`,
        so one member of the family is present at a time. Labels outside the
        family are left as they are. Raises where the host refuses."""
        ...

    def remove_label(self, repo: RepoId, pr: int, name: str) -> None:
        """Take a label off a pull request. Raises where the host refuses."""
        ...

    def set_draft(self, repo: RepoId, pr: int, draft: bool) -> None:
        """Make a pull request a draft, or publish it for review.

        Reads the pull request's current state first and writes only when it
        differs from `draft`. Raises where the host refuses, and raises
        `NotImplementedError` for a forge with no drafts.
        """
        ...

    def close_pr(self, repo: RepoId, pr: int) -> None:
        """Close without merging - a satisfied unit's stale pull request,
        once the reason has been posted on it.

        Raises where the host refuses, rather than swallowing the way
        `update_pr` does: a satisfied unit stays satisfied either way, but the
        caller needs to know a close failed so it can record it.
        """
        ...


def key(repo: RepoId) -> str:
    """The identity as one string, for the keys already written to disk.

    `own-posts.json` and the poller's state files key on this, so it stays
    `owner/name` on GitHub: changing it would orphan a running installation's
    record of which comments it wrote.
    """
    return "/".join(part for part in (repo.account, repo.project, repo.name) if part)
