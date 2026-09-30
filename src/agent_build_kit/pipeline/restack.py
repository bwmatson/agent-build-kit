"""Moving a stack after review or a merge.

When a lower PR gains a commit, or merges, everything above it has to move.
This is the riskiest code here: it rewrites branches that already exist on the
remote, where a mistake destroys work rather than merely failing.

Two rules follow from that, and both come from something that has already gone
wrong once:

- **Every rewritten push carries an explicit lease.** `git branchless submit`
  was verified to force-push with a *bare* lease immediately after fetching,
  which advances the very ref the lease compares against — it overwrote a
  concurrent commit and reported success. So the runner passes the SHA it last
  pushed, and a remote that has moved since is a refusal, not a retry.
- **A conflict is resolved with both intents in hand, or it stops the run.**
  A restack conflict is not a random merge conflict: both sides are known
  work, each with a change, a title and acceptance criteria. Given that, an
  LLM can usually keep both. What it may not do is make the conflict go away
  by dropping a side, leave markers behind, or use the rebase as cover for
  unreviewed edits — each of which is checked, and any of which aborts the
  move and leaves it for a human. A half-finished rebase is never left in the
  worktree, since it would break every later run there.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from agent_build_kit import runtimes
from agent_build_kit.config import active
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import shell
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.base import AgentInterrupted, AgentRateLimited, AgentRuntime

Runner = Callable[[list[str]], str]

# Takes the prompt and the worktree, and edits the conflicted files in place.
Resolver = Callable[..., None]

CONFLICT_MARKERS = ("<<<<<<<", ">>>>>>>", "=======")

# `-c`, not the repository's own config: an operator working in the same
# checkout is unaffected unless they turn rerere on themselves. `autoUpdate`
# stays off deliberately — a replayed resolution lands in the file, but the
# path stays unmerged until something stages it, so the resolver still has to
# look at what it's confirming rather than trust a cache blindly.
RERERE = ("-c", "rerere.enabled=true", "-c", "rerere.autoUpdate=false")


def _untranslated_env() -> dict[str, str]:
    """The environment for the one git call whose *output* we parse.

    rerere's replay notice ("Resolved '<path>' using previous resolution.")
    goes through gettext, so a translated locale would silently break the
    match in `_replayed_files` below. This forces it back to the one string we
    match. Built fresh at call time, not once at import: a copy taken at
    import would freeze out any environment change made afterwards (HOME,
    GIT_*, PATH — including what a test fixture sets up after this module is
    imported), and this is the only call in the module that would otherwise
    disagree with the live environment every other call sees.
    """
    return {**os.environ, "LC_ALL": "C", "LANGUAGE": "C"}


def git(repo: Path, *args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    """Every git invocation this module makes, with `rerere` riding along.

    The cache itself (`rr-cache`) lives under the repository's common git
    directory regardless of this flag, shared by every worktree; this is only
    what makes git read and write it on the pipeline's own invocations rather
    than nowhere.
    """
    return shell.git(repo, *RERERE, *args, **kwargs)


class RestackConflict(RuntimeError):
    """The move could not be done mechanically: it conflicts with what it is
    moving onto beyond what the resolver could safely reconcile."""


class Moved(Frozen):
    """Where a branch ended up, and whether getting there took a resolver.

    `resolved` names the files a resolver rewrote. Empty means the rebase
    applied cleanly and the unit's own change is exactly what it was; anything
    else means code no review has seen, and — since the predecessor changed
    underneath it — tests that may no longer fit what they now sit on.
    """

    sha: str
    resolved: tuple[str, ...] = ()


class ConflictContext(Frozen):
    """What each side of the conflict was trying to do.

    This is the advantage a pipeline has over a person resolving by hand: both
    sides are planned work, so their intent is written down rather than
    inferred from the diff.
    """

    moving_unit: str
    moving_intent: str
    onto_unit: str
    onto_intent: str


RESOLVE_PROMPT = """\
A rebase conflict needs resolving. Both sides are deliberate work, so the
resolution should keep both unless they genuinely cannot coexist.

**Being moved:** `{moving_unit}` — {moving_intent}
**Moving onto:** `{onto_unit}` — {onto_intent}

Conflicted files:
{files}
{replayed}
{diff}

Edit the conflicted files so that both intents survive, and remove every
conflict marker. Change **only the conflict**: a rebase is not the place for
improvements, and anything beyond the conflict is unreviewed work smuggled
into someone else's diff. If the two intents truly contradict each other,
leave the markers in place — stopping is better than guessing.
"""

REPLAYED_NOTE = """
These paths arrived with a resolution replayed from an earlier run of this
same conflict — filled in, but still unstaged for you to judge:
{files}
Leave one unchanged to accept it — the pipeline stages it for you. Edit it to
correct it, and your fix replaces what's cached for the next replay. If it is
wrong and cannot be reconciled with what you are resolving, put a `<<<<<<<`
line in the file instead: that is read as a rejection, aborts the move for a
human, and clears this cached entry so the next sibling sees the conflict
fresh rather than the same bad resolution.
"""


class StaleRemote(RuntimeError):
    """The remote branch moved since we last pushed — somebody else's commit."""


# Long enough to be distinctive rather than incidental: `x`, `if` or a brace
# says nothing about whether the unit's change survived.
MIN_MARKER_LENGTH = 5

# Each marker is another way for a legitimate resolution to be refused, so a
# handful is plenty.
MAX_MARKERS = 3

# Identifiers and quoted strings. Deliberately *tokens*, not whole lines: a
# good resolution usually rewrites the conflicting line to hold both sides
# (`["integration", "local_stack"]`), so requiring the original line verbatim
# would refuse exactly the resolutions we want.
TOKEN = re.compile(rf"[A-Za-z_][A-Za-z0-9_]{{{MIN_MARKER_LENGTH - 1},}}")


def derive_must_keep(repo: Path, branch: str, *, old_base: str, files: list[str]) -> list[str]:
    """Tokens the moving branch introduced that the base doesn't have.

    Used to check that a conflict resolution didn't quietly delete the unit's
    own change. Deliberately conservative: a marker that turns out to be the
    base's would fail every resolution and stall the stack, which is worse
    than a weak guard — tier 1, tier 2 and the review pass all still run
    afterwards.
    """
    if not files:
        return []

    added = git(
        repo, "diff", f"{old_base}...{branch}", "--unified=0", "--", *files, check=False
    ).stdout

    # Anything the base already contains isn't distinctive of this unit.
    base_text = "\n".join(
        git(repo, "show", f"{old_base}:{name}", check=False).stdout for name in files
    )

    candidates: list[str] = []
    for line in added.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for token in TOKEN.findall(line[1:]):
            if token not in base_text and token not in candidates:
                candidates.append(token)

    # Longest first: a longer token is likelier to be unique to this change.
    candidates.sort(key=len, reverse=True)
    return candidates[:MAX_MARKERS]


def diff_id(repo: Path, base: str, branch: str) -> str:
    """One id for the whole of what `branch` changes over `base`.

    Stable across a clean rebase — `git patch-id` ignores line numbers and
    whitespace context — and different the moment the change itself does.
    """
    diff = git(repo, "diff", f"{base}...{branch}", check=False).stdout
    if not diff.strip():
        return ""
    out = git(repo, "patch-id", "--stable", input=diff, check=False).stdout.split()
    return out[0] if out else ""


def conflicted_files(repo: Path) -> list[str]:
    """The paths git lists as unmerged in `repo`, empty when none or when the listing fails."""
    out = git(repo, "diff", "--name-only", "--diff-filter=U", check=False).stdout
    return [line for line in out.splitlines() if line]


REPLAYED_NOTICE = re.compile(r"^Resolved '(.+)' using previous resolution\.$", re.MULTILINE)


def _replayed_files(output: str, files: list[str]) -> list[str]:
    """Which of `files` arrived with a rerere replay, from positive evidence
    in `output` — the text `git rebase` prints (via rerere, in the untranslated
    locale `_UNTRANSLATED_ENV` forces) when it fills a path from its cache.

    Not `git rerere remaining`: that command lists paths rerere did *not*
    resolve, and absence from it was read as "resolved by a replay" — but a
    conflict rerere never tracks at all, such as a binary conflict, is neither
    PUNTED nor added to MERGE_RR, so it is absent from `remaining` too, with
    an empty cache and nothing replayed. Absence proves nothing; only the
    replay notice itself does.
    """
    replayed = set(REPLAYED_NOTICE.findall(output))
    return [name for name in files if name in replayed]


def _abort(repo: Path, message: str) -> RestackConflict:
    # Leave nothing half-applied: a rebase in progress makes every later
    # command in this worktree fail in a confusing way.
    git(repo, "rebase", "--abort", check=False)
    return RestackConflict(message)


def move_branch_onto(
    repo: Path,
    branch: str,
    *,
    new_base: str,
    old_base: str,
    resolve: Resolver | None = None,
    context: ConflictContext | None = None,
    must_keep: list[str] | None = None,
) -> Moved:
    """Replay `branch`'s own commits onto `new_base`.

    `old_base` is what it used to sit on, so only the commits this branch added
    are replayed — without it, a merged parent's commits would be duplicated
    on top of the very base that now contains them.

    On a conflict: with no `resolve`, this aborts and raises, as before. With
    one, the resolver is given both sides' intent and asked to keep both. Its
    answer is then checked rather than trusted — markers gone, and the unit's
    own change still present — because the easiest way to end a conflict is to
    delete one side, and that would quietly empty the unit being moved.

    `must_keep` defaults to lines derived from the moving branch's own diff
    (`derive_must_keep`), so a caller doesn't have to hand-write the guard.
    """
    result = git(
        repo,
        "rebase",
        "--onto",
        new_base,
        old_base,
        branch,
        check=False,
        env=_untranslated_env(),
    )
    if result.returncode == 0:
        return Moved(sha=git(repo, "rev-parse", branch).stdout.strip())

    if resolve is None or context is None:
        raise _abort(
            repo,
            f"moving {branch} from {old_base} onto {new_base} conflicts:\n"
            f"{result.stdout}\n{result.stderr}\n"
            "Left unmoved for a human to resolve.",
        )

    files = conflicted_files(repo)
    if must_keep is None:
        must_keep = derive_must_keep(repo, branch, old_base=old_base, files=files)

    replayed = _replayed_files(result.stdout + result.stderr, files)
    replayed_content = {name: (repo / name).read_text(errors="replace") for name in replayed}
    prompt = RESOLVE_PROMPT.format(
        moving_unit=context.moving_unit,
        moving_intent=context.moving_intent,
        onto_unit=context.onto_unit,
        onto_intent=context.onto_intent,
        files="\n".join(f"- {name}" for name in files) or "- (none reported)",
        replayed=REPLAYED_NOTE.format(files="\n".join(f"- {name}" for name in replayed))
        if replayed
        else "",
        diff=git(repo, "diff", check=False).stdout[:8000],
    )

    try:
        # One attempt only. An unattended run that loops on a failing resolver
        # burns the usage window with nothing to show for it.
        resolve(prompt, cwd=repo)
    except (AgentRateLimited, AgentInterrupted):
        # Not a conflict nobody could resolve: the account is out of room, or
        # the run was killed. The branch goes back where it was, to be moved
        # again once the tick can run.
        git(repo, "rebase", "--abort", check=False)
        raise
    except Exception as error:
        raise _abort(repo, f"the conflict resolver failed on {branch}: {error}") from error

    marked = [
        name
        for name in files
        if any(marker in (repo / name).read_text(errors="replace") for marker in CONFLICT_MARKERS)
    ]
    if marked:
        for name in marked:
            if name in replayed:
                # A rejected replay: forget the cached entry before the abort
                # below clears the rebase, so the next sibling to hit this
                # conflict is offered the conflict itself, not the entry that
                # was just judged wrong. Done for every marked file, not just
                # the first — otherwise a second rejected replay, or one
                # listed after a plain unresolved file, keeps its stale entry
                # and gets replayed straight to the next sibling.
                git(repo, "rerere", "forget", name, check=False)
        raise _abort(
            repo,
            f"{', '.join(marked)} still has conflict markers after resolution — "
            "left for a human, since staging a conflict is worse than not moving.",
        )

    for needle in must_keep:
        if not any(needle in (repo / name).read_text(errors="replace") for name in files):
            raise _abort(
                repo,
                f"the resolution dropped {needle!r}, which is {context.moving_unit}'s own "
                "change — resolving a conflict by deleting one side empties the unit.",
            )

    for name in replayed:
        if (repo / name).read_text(errors="replace") != replayed_content[name]:
            # Once rerere has auto-applied a cached resolution, it stops
            # tracking that path for recording — `git add` and `--continue`
            # alone would leave the stale entry in place. Forgetting it here
            # is what makes an override replace what's cached instead of
            # being silently discarded.
            git(repo, "rerere", "forget", name, check=False)

    git(repo, "add", "-A")
    finished = git(repo, "-c", "core.editor=true", "rebase", "--continue", check=False)
    if finished.returncode != 0:
        raise _abort(
            repo,
            f"the rebase did not complete after resolution:\n{finished.stdout}\n{finished.stderr}",
        )

    return Moved(sha=git(repo, "rev-parse", branch).stdout.strip(), resolved=tuple(files))


# `git@host:owner/name.git`, or the ssh:// form of the same. Only these can be
# routed through an ssh alias; an https remote has no key to swap.
SSH_REMOTE = re.compile(r"^(?:ssh://)?git@[^:/]+[:/](?P<path>.+)$")


def push_target(repo: Path) -> str:
    """Where agent branches are pushed: `origin`, or the account's own alias.

    With `spec_push_host` set, origin's URL is rewritten to go through that
    ssh alias, so the push authenticates as the pipeline's account rather than
    as whoever owns the default key. Anything that isn't an ssh remote is left
    as `origin` — mangling it would produce a URL that fails at push time,
    after the unit has been built, reviewed and checked.
    """
    if not active().github.push_host:
        return "origin"

    result = git(repo, "remote", "get-url", "origin", check=False)
    match = SSH_REMOTE.match(result.stdout.strip())
    if result.returncode or not match:
        return "origin"

    return f"git@{active().github.push_host}:{match.group('path')}"


def resolved_move(
    repo: Path,
    branch: str,
    *,
    new_base: str,
    old_base: str,
    moving_unit: str,
    moving_intent: str,
    onto_unit: str,
    onto_intent: str,
    move: Callable[..., Moved] | None = None,
    resolve: Resolver | None = None,
) -> Moved:
    """`move_branch_onto` with the resolver wired up and both sides' intent.

    Two callers need exactly this and nothing else between them: `events`'
    restack after a parent merges, and the restack a held unit does when it
    resumes onto a parent that was reworked. Both were building the same
    `ConflictContext` and passing the same resolver, which is the part neither
    can afford to get wrong — a resolver given only the diff has to guess which
    side to keep, and the cheapest way to end a conflict is to delete one.

    What differs between them is which commits to replay and what to do
    afterwards, and that stays with each caller: `events` pushes, retargets the
    PR and comments; a resuming unit has a review loop and tier 1 still ahead of
    it and must not push yet.
    """
    move = move or move_branch_onto
    return move(
        repo,
        branch,
        new_base=new_base,
        old_base=old_base,
        resolve=resolve or claude_resolver,
        context=ConflictContext(
            moving_unit=moving_unit,
            moving_intent=moving_intent,
            onto_unit=onto_unit,
            onto_intent=onto_intent,
        ),
    )


def push_with_lease(repo: Path, branch: str, *, last_pushed: str | None) -> str:
    """Push `branch`, refusing to overwrite anything we didn't put there.

    `last_pushed` is the SHA this runner last published for the branch. Passing
    it explicitly is the whole point: a bare `--force-with-lease` compares
    against the remote-tracking ref, which any fetch in the same run may have
    already advanced past somebody else's commit.

    A branch that has never been pushed needs no force at all — and using one
    there would hide a naming mistake rather than surface it.
    """
    target = push_target(repo)

    if last_pushed is None:
        # `-u` only for a real remote: setting an upstream to a bare URL is
        # noise, and nothing here reads tracking refs — the leases are
        # explicit precisely so they don't have to.
        upstream = ["-u"] if target == "origin" else []
        result = git(repo, "push", "-q", *upstream, target, branch, check=False)
    else:
        result = git(
            repo,
            "push",
            f"--force-with-lease={branch}:{last_pushed}",
            target,
            branch,
            check=False,
        )

    if result.returncode != 0:
        combined = f"{result.stdout}\n{result.stderr}"
        if "stale info" in combined or "rejected" in combined:
            raise StaleRemote(
                f"{branch} on the remote is not the commit we last pushed — "
                "someone else has pushed to it. Fetch, include their work, and "
                f"re-run the checks before pushing again.\n{combined}"
            )
        raise RuntimeError(f"pushing {branch} failed:\n{combined}")

    return git(repo, "rev-parse", branch).stdout.strip()


def blast_radius_note(*, branch: str, old_base: str, new_base: str, reason: str) -> str:
    """What to post on a PR whose branch was just rewritten.

    A reviewer who sees a force-push needs to know what moved underneath them,
    without diffing the branch against its former self.
    """
    return (
        f"**Restacked.** `{branch}` was moved from `{old_base}` onto `{new_base}` "
        f"({reason}). Its own commits are unchanged; what sits beneath them is not. "
        "The checks were re-run after the move, and the tier 2 snapshot above, if any, "
        "belongs to the new head commit."
    )


RESOLVER_TOOLS = "Read Edit Write Grep Glob"


def claude_resolver(prompt: str, *, cwd: Path, runtime: AgentRuntime | None = None) -> None:
    """Resolve the conflicted files in `cwd` with a scoped Claude run.

    Deliberately narrow: no commit, no push, no test run. It edits the
    conflicted files and stops, and `move_branch_onto` then checks the result.
    The runner re-runs tier 1 and tier 2 afterwards, so this produces a
    candidate rather than a verdict.
    """
    result = (runtime or runtimes.active()).run(
        AgentRequest(
            prompt=prompt,
            cwd=cwd,
            # It edits because its tool list says so, and is granted nothing more.
            allowed_tools=RESOLVER_TOOLS,
            permission_mode="allowed_tools_only",
        )
    )
    if not result.ok:
        raise RuntimeError(result.error)
