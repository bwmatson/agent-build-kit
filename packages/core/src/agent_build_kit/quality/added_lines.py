"""A unit's added lines, read from git against the merge-base and closed to tampering."""

import re
import stat
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git

BINARY_PROBE_BYTES = 8192
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
DIFF_OPTIONS = (
    "-c",
    "core.quotepath=off",
    "diff",
    "--text",
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "-M",
    "-U0",
)


class AddedLinesError(Exception):
    """The reading failed; it names the step and git's message and is never a pass."""


class AddedFile(Frozen):
    """One file's part of a unit's diff."""

    path: str
    added: frozenset[int]
    is_new: bool
    renamed_from: str | None = None
    removed: tuple[str, ...] = ()


class FileDraft:
    """A file of the diff while its lines are being read."""

    def __init__(self) -> None:
        self.path: str | None = None
        self.is_new = False
        self.deleted = False
        self.renamed_from: str | None = None
        self.added: set[int] = set()
        self.removed: list[str] = []
        self.next_line = 0
        self.in_hunk = False

    def finish(self) -> AddedFile | None:
        if self.path is None or self.deleted:
            return None
        return AddedFile(
            path=self.path,
            added=frozenset(self.added),
            is_new=self.is_new,
            renamed_from=self.renamed_from,
            removed=tuple(self.removed),
        )


def run_git(root: Path, step: str, *args: str) -> str:
    """Git's output, or the one error naming the step and git's message."""
    try:
        done = git(root, *args, check=False, encoding="utf-8", errors="replace")
    except OSError as error:
        raise AddedLinesError(f"{step}: git {' '.join(args)}: {error}") from error
    if done.returncode != 0 or (step == "merge-base" and not done.stdout.strip()):
        raise AddedLinesError(
            f"{step}: git {' '.join(args)} exited {done.returncode}: {done.stderr.strip()}"
        )
    return done.stdout


def unquote(name: str) -> str:
    """A path as git prints it: C-style quoted when it holds a special character."""
    if not name.startswith('"'):
        return name
    body = name[1:-1].encode("latin-1", errors="backslashreplace")
    return body.decode("unicode_escape").encode("latin-1").decode("utf-8", errors="replace")


def side_path(text: str) -> str | None:
    """The path of a `---` or `+++` line, with its `a/` or `b/` prefix off; None for /dev/null."""
    name = unquote(text.rstrip("\t"))
    return None if name == "/dev/null" else name[2:]


def apply_header(draft: FileDraft, line: str) -> None:
    """Take what a file-header line of the diff says."""
    if line.startswith("new file mode"):
        draft.is_new = True
    elif line.startswith("deleted file mode"):
        draft.deleted = True
    elif line.startswith("rename from "):
        draft.renamed_from = unquote(line[len("rename from ") :])
    elif line.startswith("rename to "):
        draft.path = unquote(line[len("rename to ") :])
    elif line.startswith("+++ "):
        draft.path = side_path(line[4:]) or draft.path


def apply_body(draft: FileDraft, line: str) -> None:
    """Take one line of a hunk: added, removed, or neither."""
    if line.startswith("+"):
        draft.added.add(draft.next_line)
        draft.next_line += 1
    elif line.startswith("-"):
        draft.removed.append(line[1:])


def parse_diff(text: str) -> dict[str, AddedFile]:
    """Each file of a `-U0` diff as its added line numbers, by path."""
    drafts: list[FileDraft] = []
    for line in text.split("\n"):
        hunk = HUNK.match(line)
        if line.startswith("diff --git "):
            drafts.append(FileDraft())
        elif not drafts:
            continue
        elif hunk:
            drafts[-1].in_hunk = True
            drafts[-1].next_line = int(hunk.group(1))
        elif drafts[-1].in_hunk:
            apply_body(drafts[-1], line)
        else:
            apply_header(drafts[-1], line)
    finished = (draft.finish() for draft in drafts)
    return {file.path: file for file in finished if file is not None}


def read_untracked(root: Path, name: str) -> AddedFile | None:
    """An untracked regular text file as all added lines; None for anything else."""
    path = root / name
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return None
        data = path.read_bytes()
    except OSError as error:
        raise AddedLinesError(f"read untracked file {name}: {error}") from error
    if b"\0" in data[:BINARY_PROBE_BYTES]:
        return None
    count = len(data.decode("utf-8", errors="replace").splitlines())
    return AddedFile(path=name, added=frozenset(range(1, count + 1)), is_new=True)


def read_added_lines(root: Path, base: str) -> dict[str, AddedFile]:
    """Each changed file's added line numbers against the merge-base of `base` and HEAD, by path."""
    merge_base = run_git(root, "merge-base", "merge-base", base, "HEAD").strip()
    reading = parse_diff(run_git(root, "diff", *DIFF_OPTIONS, merge_base))
    listing = run_git(
        root, "list untracked files", "ls-files", "--others", "--exclude-standard", "-z"
    )
    for name in filter(None, listing.split("\0")):
        untracked = read_untracked(root, name)
        if untracked is not None:
            reading[name] = untracked
    return reading
