"""What an agent is told about the changelog: the built repo's own convention.

The convention is the body of the `## Changelog` section of the AGENTS.md in
the worktree being built, so each repository states its own and one without a
section is told nothing. The text is a value inserted into a prompt with
`format()`, never concatenated into the format string, so braces in it are safe.
"""

import re
from pathlib import Path

from agent_build_kit.config import RepoConfig

_INTRO = "\nThe changelog convention:\n\n"


def changelog_convention(worktree: Path, repo: RepoConfig | None = None) -> str:
    """The body of the worktree's AGENTS.md `## Changelog` section, or `""`."""
    try:
        text = (worktree / "AGENTS.md").read_text(errors="replace")
    except OSError:
        return ""
    for section in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        heading, _, body = section.partition("\n")
        if heading.strip().lower().startswith("changelog"):
            return body.strip()
    return ""


def changelog_note(worktree: Path, repo: RepoConfig | None = None) -> str:
    """The prompt's changelog paragraph for this worktree, or `""` when it has no convention."""
    convention = changelog_convention(worktree)
    return f"{_INTRO}{convention}\n" if convention else ""


def resolver_changelog_rule(
    worktree: Path, files: list[str], repo: RepoConfig | None = None
) -> str:
    """The resolver's keep-both-and-fold rule: only where a changelog is in play."""
    if "CHANGELOG.md" not in files and not changelog_convention(worktree):
        return ""
    return (
        "\nIn `CHANGELOG.md` the intents always coexist: keep both sides' bullets, every\n"
        "bullet, and where two bullets describe one change, fold them into one. The\n"
        "file merges with git's union driver, so a conflict here is rare and means both\n"
        "sides edited the same bullet: merge the edits into one bullet rather than\n"
        "keeping two versions.\n"
    )


def review_changelog_paragraph(worktree: Path, repo: RepoConfig | None = None) -> str:
    """What the reviewer is told of the changelog, only where the repo states a convention."""
    if not changelog_convention(worktree):
        return ""
    return (
        "\nThe changelog's form and wording follow the convention in this repo's AGENTS.md; "
        "do not raise them where the repo's own checks pass. A changelog entry that "
        "makes a claim the code does not support is still in scope: report it.\n"
    )
