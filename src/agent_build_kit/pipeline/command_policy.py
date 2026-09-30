"""What the unattended agent may run.

The prompts ask for good behaviour; this decides it. Everything here is a
technical control, backing the guarantees in docs/architecture.md: the
agent opens PRs but never merges them, rewrites only its own
branches, and never touches `main` directly.

The force-push rules are the fiddly part, and a plain substring match gets
them wrong in both directions:

- Denying anything containing `--force` would block `--force-with-lease`,
  which restacking genuinely needs.
- Allowing anything containing `--force-with-lease` would permit the *bare*
  form, which is unsafe. Verified against git-branchless: it force-pushes
  with a bare lease after fetching in the same command, which advances the
  remote-tracking ref the lease compares against, and it overwrote a
  concurrent commit while reporting success.

So the rule is: a lease must be explicit — `--force-with-lease=<ref>:<sha>`,
or a bare lease paired with `--force-if-includes` — and only on a branch the
agent owns.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Collection
from pathlib import Path

from agent_build_kit import forges
from agent_build_kit.config import active
from agent_build_kit.model import Frozen

# Splitting on shell operators is what stops `git status && gh pr merge 4`
# from sneaking a denied command past a check on the first word.
SEGMENT_SPLIT = re.compile(r"&&|\|\||\||;|\n")

# Commands that run another command. Without stripping these, `xargs gh pr
# merge` or `env FOO=1 git push --force` would sail past a check that only
# looks at the first token.
WRAPPERS = {"xargs", "env", "sudo", "nohup", "time", "timeout", "command", "nice", "stdbuf"}

LEASE_ADVICE = (
    "restack pushes must carry an explicit lease: "
    "`git push --force-with-lease=<branch>:<sha you last pushed> origin <branch>`, "
    "or fetch first and add --force-if-includes"
)


class Verdict(Frozen):
    allowed: bool
    reason: str = ""


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        # Unbalanced quotes: we can't read it, so we don't vouch for it.
        return segment.split()


def _strip_wrappers(tokens: list[str]) -> list[str]:
    """Drop leading wrapper commands, their flags, and VAR=value assignments."""
    while tokens:
        head = tokens[0]
        if head in WRAPPERS or ("=" in head and not head.startswith("-")):
            tokens = tokens[1:]
            # A wrapper's own flags and arguments (xargs -n1, timeout 30s)
            # sit between it and the real command.
            while tokens and (tokens[0].startswith("-") or _looks_like_duration(tokens[0])):
                tokens = tokens[1:]
            continue
        return tokens
    return tokens


def _looks_like_duration(token: str) -> bool:
    return bool(re.fullmatch(r"\d+[smhd]?", token))


def _is_git(tokens: list[str], *subcommand: str) -> bool:
    return (
        len(tokens) > len(subcommand)
        and tokens[0] == "git"
        and tuple(tokens[1 : 1 + len(subcommand)]) == subcommand
    )


# Environment variables that switch a repo's commit gate off: pre-commit's
# SKIP, husky's HUSKY=0, lefthook's LEFTHOOK=0.
GATE_SWITCHES = {"SKIP", "HUSKY", "LEFTHOOK"}

# `git commit` short options that take a value, so an `n` after one of them in
# a cluster (`-mn`) is the value, not --no-verify.
COMMIT_VALUED = set("mFCcSt")

GATE_REASON = (
    "the repo's commit gate is the reason the pipeline may push unattended, so it is never "
    "skipped or reconfigured — fix what it reports and leave the commit to the pipeline"
)


def _switches_gate_off(tokens: list[str]) -> bool:
    """A leading `SKIP=… cmd`, `env HUSKY=0 cmd` or `export SKIP=…`."""
    for token in tokens:
        name = token.split("=", 1)[0]
        if "=" in token and not token.startswith("-"):
            if name in GATE_SWITCHES:
                return True
        elif token not in WRAPPERS and token != "export":
            return False
    return False


def _skips_commit_hooks(tokens: list[str]) -> bool:
    """A `git … commit` that would not run the pre-commit hook."""
    if not tokens or tokens[0] != "git":
        return False
    # Hooks can be pointed elsewhere on any git command: `-c core.hooksPath=`,
    # `git config core.hooksPath …`. Config keys are case-insensitive.
    if any("core.hookspath" in token.lower() for token in tokens):
        return True
    # Past git's own options (`-C dir`, `-c key=value`) to the subcommand.
    index = 1
    while index < len(tokens) and tokens[index].startswith("-"):
        index += 2 if tokens[index] in ("-C", "-c") else 1
    if index >= len(tokens) or tokens[index] != "commit":
        return False
    args = iter(tokens[index + 1 :])
    for arg in args:
        # git accepts any unambiguous prefix of a long option.
        if arg.startswith("--no-veri") and "--no-verify".startswith(arg):
            return True
        if arg in ("-m", "-F", "-C", "-c", "-t", "--message", "--file"):
            next(args, None)
        elif arg.startswith("-") and not arg.startswith("--"):
            for flag in arg[1:]:
                if flag == "n":
                    return True
                if flag in COMMIT_VALUED:
                    break
    return False


def _check_segment(segment: str, branch: str, protected: Collection[str] = ()) -> Verdict:
    raw = _tokens(segment)
    tokens = _strip_wrappers(raw)
    if _switches_gate_off(raw) or _skips_commit_hooks(tokens):
        return Verdict(allowed=False, reason=GATE_REASON)
    if not tokens:
        return Verdict(allowed=True)

    # Merging — the rule the entire review model rests on. Asked of every
    # registered forge, not the repo's own: a GitHub checkout has no business
    # completing an Azure pull request either, and a union cannot be weakened
    # by a wrong `forge:` field. Matched on tokens, so a commit message
    # mentioning one of these is unaffected.
    if denied := forges.denies(tokens):
        return Verdict(
            allowed=False, reason=f"the agent never merges: {denied} (a human merges every PR)"
        )

    if _is_git(tokens, "commit") and "--amend" in tokens:
        return Verdict(
            allowed=False,
            reason="amending would fold the implementation into the tests commit and erase "
            "the evidence that the tests failed first — add a new commit instead",
        )
    if _is_git(tokens, "amend"):
        return Verdict(
            allowed=False, reason="amending a unit branch is denied — add a new commit instead"
        )

    if _is_git(tokens, "reset") and "--hard" in tokens:
        return Verdict(
            allowed=False,
            reason="`git reset --hard` discards work that may not be pushed anywhere",
        )
    if _is_git(tokens, "clean"):
        return Verdict(allowed=False, reason="`git clean` discards untracked work")
    if _is_git(tokens, "branch") and "-D" in tokens:
        return Verdict(allowed=False, reason="force-deleting a branch can drop unmerged commits")
    if tokens[0] == "rm" and any(flag.startswith("-") and "r" in flag for flag in tokens[1:]):
        return Verdict(allowed=False, reason="recursive delete is denied")

    if _is_git(tokens, "push"):
        return _check_push(tokens, branch, protected)

    return Verdict(allowed=True)


def _landing(target: str) -> str:
    """The branch a push argument lands on: a refspec `src:dst` lands on `dst`,
    and `+` (force) and `refs/heads/` are spelling, not meaning."""
    return target.rsplit(":", 1)[-1].removeprefix("+").removeprefix("refs/heads/")


def _check_push(tokens: list[str], branch: str, protected: Collection[str] = ()) -> Verdict:
    owns_branch = branch.startswith(active().github.branch_prefix)
    targets = [token for token in tokens[2:] if not token.startswith("-")]

    # The branches units land on through a pull request, so a direct push to
    # one bypasses review. `main` and `master` are always among them; the rest
    # are whatever abk.yaml says a repo integrates on, because a repo on `dev`
    # is one `git push origin dev` from skipping review with nothing on the
    # server to notice. A refspec is judged by where it lands: `HEAD:dev` is a
    # push to dev, which an exact match on the argument let through.
    trunks = {"main", "master", *protected}
    landing = next((_landing(t) for t in targets if _landing(t) in trunks), None)
    if landing is not None:
        return Verdict(
            allowed=False,
            reason=f"pushing to {landing} directly would bypass review — units land through PRs",
        )

    bare_force = "--force" in tokens or "-f" in tokens
    explicit_lease = any(token.startswith("--force-with-lease=") for token in tokens)
    bare_lease = "--force-with-lease" in tokens
    includes = "--force-if-includes" in tokens

    if bare_force:
        return Verdict(
            allowed=False,
            reason=f"`--force` overwrites whatever is on the remote — {LEASE_ADVICE}",
        )

    if (explicit_lease or bare_lease) and not owns_branch:
        return Verdict(
            allowed=False,
            reason=f"force-pushing is only allowed on branches the agent owns "
            f"({active().github.branch_prefix}…), not {branch}",
        )

    if bare_lease and not (explicit_lease or includes):
        return Verdict(
            allowed=False,
            reason=f"a bare --force-with-lease can pass after a fetch has already moved the "
            f"remote-tracking ref, so it does not protect a commit you pushed — {LEASE_ADVICE}",
        )

    return Verdict(allowed=True)


PLANNING_REASON = (
    "the pipeline commits the planning repo itself and keeps it on its default branch — "
    "write the files and leave the branches, resets and cherry-picks to it"
)

BRANCH_LISTING = {"-l", "--list", "-a", "--all", "-r", "--remotes", "-v", "-vv", "--show-current"}


def _git_target(tokens: list[str], current: str | None) -> tuple[str | None, list[str]]:
    """The directory a git command acts on (its `-C`, else the directory last
    `cd`ed to) and its arguments from the subcommand on."""
    target = current
    index = 1
    while index < len(tokens) and tokens[index].startswith("-"):
        if tokens[index] == "-C" and index + 1 < len(tokens):
            target = tokens[index + 1]
        index += 2 if tokens[index] in ("-C", "-c") else 1
    return target, tokens[index:]


def _moves_branches(args: list[str]) -> bool:
    """A git subcommand that creates, switches or moves a branch, or rewrites history."""
    if not args:
        return False
    sub, rest = args[0], args[1:]
    if sub in ("switch", "reset", "cherry-pick"):
        return True
    if sub == "checkout":
        # Only a path restore (`checkout -- <paths>`) leaves the branch alone.
        return "--" not in rest or any(arg in ("-b", "-B", "--orphan") for arg in rest)
    if sub == "worktree":
        return rest[:1] == ["add"] and any(arg in ("-b", "-B") for arg in rest)
    if sub == "branch":
        return any(arg not in BRANCH_LISTING for arg in rest)
    return False


def _inside(path: str, root: Path) -> bool:
    return Path(os.path.normpath(path)).is_relative_to(os.path.normpath(root))


def _check_planning(segment: str, planning_repo: Path, current: str | None) -> Verdict:
    tokens = _strip_wrappers(_tokens(segment))
    if not tokens or tokens[0] != "git":
        return Verdict(allowed=True)
    target, args = _git_target(tokens, current)
    if target is not None and _inside(target, planning_repo) and _moves_branches(args):
        return Verdict(allowed=False, reason=PLANNING_REASON)
    return Verdict(allowed=True)


def _cd_target(segment: str) -> str | None:
    tokens = _tokens(segment)
    return tokens[1] if len(tokens) == 2 and tokens[0] == "cd" else None


def check_command(
    command: str,
    *,
    branch: str,
    planning_repo: Path | None = None,
    protected: Collection[str] = (),
) -> Verdict:
    """Decide whether `command` may run while working on `branch`.

    `protected` names the branches repos integrate on, beyond the `main` and
    `master` that are always refused a direct push.

    Every segment is checked, so a denied command behind `&&`, `;` or a pipe
    is still denied. With `planning_repo` set (a track run), commands that move
    that repo's branches are refused too: the pipeline commits there.
    """
    current: str | None = None
    for segment in SEGMENT_SPLIT.split(command):
        segment = segment.strip()
        verdict = _check_segment(segment, branch, protected)
        if verdict.allowed and planning_repo is not None:
            verdict = _check_planning(segment, planning_repo, current)
        if not verdict.allowed:
            return verdict
        current = _cd_target(segment) or current
    return Verdict(allowed=True)
