"""What an agent is told about the changelog: the built repo's own convention.

The convention is the body of the `## Changelog` section of the AGENTS.md, else
the CLAUDE.md, in the worktree being built, so each repository states its own;
one without a section is told the framework's packaged text, and one whose
`changelog` setting is off is told nothing. The text is a value inserted into a
prompt with `format()`, never concatenated into the format string, so braces in
it are safe.
"""

import re
from importlib import resources
from pathlib import Path

from agent_build_kit.config import RepoConfig

_DEFAULT_FILE = "CHANGELOG.md"
_BLOCK_CLOSE = "<!-- /abk:changelog -->"
_INTRO = "\nThe changelog convention:\n\n"


def _section(path: Path) -> str:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    for section in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        heading, _, body = section.partition("\n")
        if heading.strip().lower().startswith("changelog"):
            return body.split(_BLOCK_CLOSE, 1)[0].strip()
    return ""


def _enabled(repo: RepoConfig | None) -> bool:
    """Whether the repo's setting is on; a caller with no repo config says nothing of it."""
    return repo is None or repo.changelog is not None


def packaged_convention(changelog: str = _DEFAULT_FILE) -> str:
    """The framework's own convention text, for a repo keeping its changelog at `changelog`."""
    packaged = (
        resources.files("agent_build_kit")
        .joinpath("templates", "changelog-convention.md")
        .read_text()
        .strip()
    )
    return packaged.replace(f"`{_DEFAULT_FILE}`", f"`{changelog}`")


def changelog_convention(worktree: Path, repo: RepoConfig | None = None) -> str:
    """The convention for this worktree: its AGENTS.md section, else its CLAUDE.md
    section, else the packaged text; `""` when the repo's setting is off. With no repo
    config, only a section of the worktree's own counts."""
    if not _enabled(repo):
        return ""
    for name in ("AGENTS.md", "CLAUDE.md"):
        if section := _section(worktree / name):
            return section
    if repo is None:
        return ""
    return packaged_convention(repo.changelog or _DEFAULT_FILE)


def changelog_note(worktree: Path, repo: RepoConfig | None = None) -> str:
    """The prompt's changelog paragraph for this worktree, or `""` when it has no convention."""
    convention = changelog_convention(worktree, repo)
    return f"{_INTRO}{convention}\n" if convention else ""


def resolver_changelog_rule(
    worktree: Path, files: list[str], repo: RepoConfig | None = None
) -> str:
    """The resolver's keep-both-and-fold rule: only where a changelog is in play."""
    if not _enabled(repo):
        return ""
    name = (repo.changelog if repo else None) or _DEFAULT_FILE
    if name not in files and not changelog_convention(worktree, repo):
        return ""
    return (
        f"\nIn `{name}` the intents always coexist: keep both sides' bullets, every\n"
        "bullet, and where two bullets describe one change, fold them into one. The\n"
        "file merges with git's union driver, so a conflict here is rare and means both\n"
        "sides edited the same bullet: merge the edits into one bullet rather than\n"
        "keeping two versions.\n"
    )


def review_changelog_paragraph(worktree: Path, repo: RepoConfig | None = None) -> str:
    """What the reviewer is told of the changelog, only where the repo states a convention."""
    if not changelog_convention(worktree, repo):
        return ""
    return (
        "\nThe changelog's form and wording follow the repo's changelog convention, given "
        "below; do not raise them where the repo's own checks pass. A changelog entry that "
        "makes a claim the code does not support is still in scope: report it.\n"
        + changelog_note(worktree, repo)
    )
