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

import re
import subprocess
from collections.abc import Callable, Collection, Sequence
from typing import TYPE_CHECKING, Protocol

from agent_build_kit.model import Frozen

if TYPE_CHECKING:
    # config imports this package to check a repo's forge at load.
    from agent_build_kit.config import RepoConfig

# Injected so a check can be tested against recorded answers, the way
# `tier2.post_status` and the `wiring.build_*` factories already take one.
Run = Callable[..., subprocess.CompletedProcess]


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
    # Checks the host cancelled: neither a pass nor a verdict on the commit.
    cancelled_checks: tuple[str, ...] = ()
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


class Stack(Frozen):
    """A series of pull requests the host knows about, bottom first.

    `open` is false once every pull request in it has merged: such a stack
    cannot be extended, and a later unit of the chain starts a new one.
    """

    number: int
    open: bool
    pulls: tuple[int, ...]


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


class PermittedCommand(Frozen):
    """One exact command shape allowed under a denied prefix.

    `flags` maps each permitted flag, spelled in full, to a regex its value
    must match completely. Anything else about the command - another flag, an
    abbreviation, a repeat, a missing value, a positional - is a different
    shape and stays denied.
    """

    prefix: tuple[str, ...]
    flags: tuple[tuple[str, str], ...]

    def matches(self, tokens: list[str]) -> bool:
        n = len(self.prefix)
        if tuple(tokens[:n]) != self.prefix:
            return False
        allowed = dict(self.flags)
        seen: set[str] = set()
        rest = iter(tokens[n:])
        for token in rest:
            flag, joined, value = token.partition("=")
            if flag not in allowed or flag in seen:
                return False
            seen.add(flag)
            if not joined:
                value = next(rest, "")
                if value.startswith("--"):
                    return False
            if not re.fullmatch(allowed[flag], value):
                return False
        return True


class Forge(RegistersStacks, Protocol):
    """The host a repo lives on."""

    name: str
    # False while a forge is declared but unfinished: callers hold the unit
    # rather than failing it. The `node_npm` profile does the same.
    implemented: bool
    # The command this forge's calls go through (`gh`, `az`), which a scheduled
    # unit has to be able to find: it starts with no login environment, so a
    # client that is on a person's PATH is not necessarily on the unit's.
    client: str
    # Whether merging removes the source branch, which decides who cleans up.
    deletes_head_branch_on_merge: bool
    # Command prefixes no agent may run on any repo - merging, voting, and the
    # raw API escapes that reach both. Folded together by `denies`.
    denied_commands: tuple[tuple[str, ...], ...]
    # Command prefixes an agent may run to read its own PR. No prefix here may
    # overlap any forge's `denied_commands`; `wiring.allowed_tools` composes the
    # allow-list from them.
    read_commands: tuple[tuple[str, ...], ...]
    # The exact command shapes allowed although a denied prefix covers them,
    # for the calls the pipeline itself makes. Empty when nothing needs one.
    permitted_commands: tuple[PermittedCommand, ...]
    # The facts this forge cannot name a repo without, by their key in that
    # repo's abk.yaml entry (dotted for a nested block). A repo declaring this
    # forge and leaving one out fails at load, as a runtime selection does.
    requires: tuple[str, ...]
    # What this host's CI is called, for a pull request body that says who runs
    # the checks.
    ci_name: str

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
