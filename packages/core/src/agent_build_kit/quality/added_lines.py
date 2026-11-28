"""A unit's added lines, read from git against the merge-base and closed to tampering."""

import re
import stat
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.own_tests import HUNK
from agent_build_kit.pipeline.shell import git

BINARY_PROBE_BYTES = 8192
ESCAPE = re.compile(rb"\\([0-7]{3}|.)", re.DOTALL)
SIMPLE_ESCAPES = {
    b"a": b"\a",
    b"b": b"\b",
    b"f": b"\f",
    b"n": b"\n",
    b"r": b"\r",
    b"t": b"\t",
    b"v": b"\v",
}
DIFF_OPTIONS = (
    "-c",
    "core.quotepath=off",
    "diff",
    "--text",
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--src-prefix=a/",
    "--dst-prefix=b/",
    "-M",
    "-U0",
)


class AddedLinesError(Exception):
    """The reading failed; it names the step and git's message and is never a pass."""


class AddedFile(Frozen):
    """One file's part of a unit's diff. A deleted file is listed with no added lines and its
    removed lines, so a line moved out of it is known to be moved; a judge skips it."""

    path: str
    added: frozenset[int]
    is_new: bool
    renamed_from: str | None = None
    removed: tuple[str, ...] = ()
    deleted: bool = False


class FileDraft:
    """A file of the diff while its lines are being read."""

    def __init__(self) -> None:
        self.path: str | None = None
        self.old_path: str | None = None
        self.is_new = False
        self.deleted = False
        self.renamed_from: str | None = None
        self.added: set[int] = set()
        self.removed: list[str] = []
        self.next_line = 0
        self.in_hunk = False

    def finish(self) -> AddedFile | None:
        path = self.old_path if self.deleted else self.path
        if path is None:
            return None
        return AddedFile(
            path=path,
            deleted=self.deleted,
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
    return ESCAPE.sub(unescaped, name[1:-1].encode("utf-8")).decode("utf-8", errors="replace")


def unescaped(found: re.Match[bytes]) -> bytes:
    """The byte one backslash escape of a quoted path stands for."""
    code = found.group(1)
    if len(code) == 3 and code.isdigit():
        return bytes([int(code, 8)])
    return SIMPLE_ESCAPES.get(code, code)


def git_lines(text: str) -> list[str]:
    """The lines of a text as git numbers them: split at `\\n` only, a final newline ending the
    last line and a `\\r` before a newline not part of it."""
    pieces = text.split("\n")
    if pieces and pieces[-1] == "":
        pieces.pop()
    return [piece.removesuffix("\r") for piece in pieces]


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
    elif line.startswith("--- "):
        draft.old_path = side_path(line[4:])
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
            drafts[-1].next_line = int(hunk.group(3))
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
    count = len(git_lines(data.decode("utf-8", errors="replace")))
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
