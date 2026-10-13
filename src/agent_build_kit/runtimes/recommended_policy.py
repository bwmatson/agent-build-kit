"""The recommended policy for a build agent, as one table.

Per forbidden class: the command globs that refuse it, the samples they must and
must not match, and what the recommendation does not cover. The commands are the
spellings table's (`pipeline.command_spellings`); only what a glob alone can show
is written here. `matches` is a reference matcher, an approximation of an agent's
own: the live policy check is the confirmation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from fnmatch import fnmatchcase

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.command_spellings import SPELLINGS, Reader

DIALECT = (
    "fnmatch globs: `*` matches any run of characters, spaces and slashes included, `?` one "
    "character, `[...]` a character class; case-insensitive; matched against the whole command "
    "and each segment of a compound command split at `&&`, `||`, `|`, `;` and a newline, with "
    "runs of whitespace collapsed; a pattern is anchored, so it must match the whole command or "
    "segment and a wrapper prefix is not matched."
)

MERGE = "merging a pull request"
RAW_MERGE = "merging a pull request through the host's raw API"
GRAPHQL_MERGE = "merging a pull request through the host's GraphQL API"
AMEND = "amending a commit"
PUSH = "pushing to the default branch"
FORCE_PUSH = "a force push to the default branch"

_BRANCHES = ("main", "master")
# A refspec's ending: the branch after a separator, with a trailing argument, or inside a quote;
# then the same behind `heads/`.
_ENDINGS = (
    "*[ +:\"']{b}",
    "*[ +:\"']{b} *",
    "*[ +:\"']{b}[\"']*",
    "*heads/{b}",
    "*heads/{b} *",
    "*heads/{b}[\"']*",
)


class ClassPolicy(Frozen):
    label: str
    globs: tuple[str, ...]
    refused_samples: tuple[str, ...]
    allowed_samples: tuple[str, ...]
    # Refused samples only a glob refuses: the command rules allow them.
    glob_only: tuple[str, ...] = ()


class Uncovered(Frozen):
    label: str
    reason: str


def _spaced(program: str, tail: str) -> tuple[str, str]:
    """`tail` as written directly after `program`, and after a global option."""
    return f"{program} {tail}", f"{program} * {tail}"


def _subcommand(program: str, subcommand: str) -> tuple[str, ...]:
    plain, optioned = _spaced(program, subcommand)
    return plain, f"{plain} *", optioned, f"{optioned} *"


def _pushes() -> tuple[str, ...]:
    return tuple(
        f"{prefix} {ending.format(b=branch)}"
        for prefix in _spaced("git", "push")
        for branch in _BRANCHES
        for ending in _ENDINGS
    )


def _rows(label: str) -> tuple[str, ...]:
    """The spellings table's rows the globs are expected to refuse."""
    return tuple(s.command for s in SPELLINGS[label] if Reader.GLOB in s.readers)


_GRAPHQL = "gh api graphql -f query='mutation { mergePullRequest(input: {pullRequestId: \"x\"}) }'"

RECOMMENDED: tuple[ClassPolicy, ...] = (
    ClassPolicy(
        label=MERGE,
        globs=_subcommand("gh", "pr merge"),
        refused_samples=_rows(MERGE),
        allowed_samples=("gh pr view 1", "gh pr create --fill", "gh pr checks 1", "gh pr list"),
    ),
    ClassPolicy(
        label=RAW_MERGE,
        globs=("gh api *pulls/*/merge*", "gh * api *pulls/*/merge*"),
        refused_samples=_rows(RAW_MERGE),
        allowed_samples=(
            "gh api repos/example/app/pulls/1",
            "gh api repos/example/app/pulls/1/comments",
        ),
    ),
    ClassPolicy(
        label=GRAPHQL_MERGE,
        globs=("gh api graphql *mergePullRequest*", "gh * api graphql *mergePullRequest*"),
        refused_samples=(_GRAPHQL, _GRAPHQL.replace("gh api", "gh -R example/app api")),
        allowed_samples=("gh api graphql -f query='query { viewer { login } }'",),
        glob_only=(_GRAPHQL, _GRAPHQL.replace("gh api", "gh -R example/app api")),
    ),
    ClassPolicy(
        label=AMEND,
        globs=(
            "git commit *--amend*",
            "git * commit *--amend*",
            "git amend",
            "git amend *",
        ),
        refused_samples=(*_rows(AMEND), "git amend"),
        allowed_samples=(
            "git -C /tmp/work log --oneline",
            "git -C /tmp/work status",
            "git --no-pager diff",
            "git commit -m 'add the marker'",
        ),
    ),
    ClassPolicy(
        label=PUSH,
        globs=_pushes(),
        refused_samples=(
            *_rows(PUSH),
            "git push origin refs/heads/main",
            "git push origin refs/heads/master",
            "git push origin 'HEAD:main'",
            'git push origin "HEAD:master"',
        ),
        allowed_samples=(
            "git push -u origin spec/master-plan/2",
            "git -C /tmp/work push origin spec/add-marker/1",
            "git push origin feature/domain",
        ),
    ),
    ClassPolicy(
        label=FORCE_PUSH,
        # Covered by the push class's globs.
        globs=(),
        refused_samples=_rows(FORCE_PUSH),
        allowed_samples=("git push --force-with-lease origin spec/main-menu/1",),
    ),
)

_NO_GLOB = "refusing it would also refuse it in interactive use, a choice for the person; {gate}"
_GATED = "the agent's own approval step may gate it, which varies per agent"
UNCOVERED: tuple[Uncovered, ...] = tuple(
    Uncovered(label=label, reason=_NO_GLOB.format(gate=_GATED))
    for label in (
        "skipping the commit gate",
        "a hard reset",
        "discarding untracked work",
        "force-deleting a branch",
        "a recursive delete",
        "a bare force push",
    )
)

# Commands a glob refuses though they are harmless: it cannot tell a message from a command.
KNOWN_FALSE_POSITIVES: tuple[str, ...] = (
    "git commit -m 'document the --amend flag'",
    "git commit -m fix push to main",
)
# Commands that do what a class forbids and no glob catches.
KNOWN_GAPS: tuple[str, ...] = (
    "git -c alias.p=push p origin main",
    "git push",
    "git push --all origin",
)

_SEGMENTS = re.compile(r"&&|\|\||\||;|\n")


def _squeeze(text: str) -> str:
    return " ".join(text.lower().split())


def matches(pattern: str, command: str) -> bool:
    """Whether `pattern` refuses `command` in the shipped dialect (`DIALECT`)."""
    glob = _squeeze(pattern)
    pieces = [command, *_SEGMENTS.split(command)]
    return any(fnmatchcase(_squeeze(piece), glob) for piece in pieces)


def patterns(extra: Iterable[str] = ()) -> list[str]:
    """Every recommended glob in table order, then the caller's extras, none repeated."""
    every = (g for policy in RECOMMENDED for g in policy.globs)
    return list(dict.fromkeys([*every, *extra]))
