"""The before-and-after comparison of a reorganization's test files (standard T26).

A reorganization changes tests only mechanically. This module finds the test files a range of
commits changed, follows moves by git rename, and asks each file's toolchain profile how the
parent's version differs from the new one beyond a mechanical edit (`ComparesTests`). A profile
without that hook has its files left out.

A test or shared definition that leaves one file and arrives unchanged in another (a merge or a
split of files) is not reported. A characterization test committed first, before the code moves,
is the one allowed addition, and it must pass unchanged after the move.
"""

from collections.abc import Callable
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git
from agent_build_kit.profiles.base import ChangedTest, ComparesTests, ToolchainProfile

STANDARD = "T26"


class Finding(Frozen):
    """One way a changed test file differs from its parent's version beyond a mechanical edit."""

    standard: str
    path: str
    test: str
    reason: str


def _finding(path: str, change: ChangedTest) -> Finding:
    return Finding(standard=STANDARD, path=path, test=change.test, reason=change.reason)


def compare_sources(toolchain: ComparesTests, path: str, before: str, after: str) -> list[Finding]:
    """Findings for the test file at `path`: every difference between its two versions."""
    return [_finding(path, c) for c in toolchain.compare_test_sources(path, before, after)]


def _show(repo: Path, rev: str, path: str) -> str | None:
    done = git(repo, "show", f"{rev}:{path}", check=False)
    return done.stdout if done.returncode == 0 else None


def _name_status(repo: Path, base: str, head: str) -> list[tuple[str, list[str]]]:
    """(status letter, paths) for each file that differs, read NUL-separated so a path with
    unusual characters is not quoted."""
    tokens = git(repo, "diff", "--name-status", "-M", "-z", f"{base}..{head}").stdout.split("\0")
    entries: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(tokens) and tokens[i]:
        count = 2 if tokens[i][0] in "RC" else 1
        entries.append((tokens[i][0], tokens[i + 1 : i + 1 + count]))
        i += 1 + count
    return entries


def _characterization(
    repo: Path, base: str, head: str, path: str, change: ChangedTest, toolchain: ComparesTests
) -> list[Finding] | None:
    """None when the range's first commit did not introduce the test `change` in `path`;
    otherwise how the test differs between that commit and `head` (nothing, when unchanged)."""
    commits = git(repo, "rev-list", "--reverse", f"{base}..{head}").stdout.split()
    if not commits:
        return None
    first = commits[0]
    at_first = _show(repo, first, path)
    if at_first is None:
        return None
    parent = _show(repo, f"{first}^", path) or ""
    introduced = any(
        c.kind == "added" and c.test == change.test
        for c in toolchain.compare_test_sources(path, parent, at_first)
    )
    if not introduced:
        return None
    at_head = _show(repo, head, path)
    if at_head is None:
        return []
    return [
        _finding(path, c)
        for c in toolchain.compare_test_sources(path, at_first, at_head)
        if c.test == change.test and c.kind == "changed"
    ]


def compare_changes(
    repo: Path,
    base: str,
    head: str = "HEAD",
    *,
    toolchain_for: Callable[[str], ToolchainProfile],
) -> list[Finding]:
    """Findings for every test file changed between `base` and `head`, following git renames.

    `toolchain_for` gives the profile of a path, as the gate does. A test file whose profile
    cannot compare is left out. One added test, which the range's first commit introduced, is
    allowed if later commits leave it unchanged."""
    findings: list[Finding] = []
    gone: list[tuple[str, ChangedTest]] = []
    new: list[tuple[str, ChangedTest, ComparesTests]] = []

    for code, paths in _name_status(repo, base, head):
        old_path, new_path = paths[0], paths[-1]
        profile = toolchain_for(new_path)
        if not isinstance(profile, ComparesTests) or not profile.is_test_path(new_path):
            continue
        before = _show(repo, base, old_path) if code != "A" else ""
        after = _show(repo, head, new_path) if code != "D" else ""
        if before is None or after is None:
            continue
        for change in profile.compare_test_sources(new_path, before, after):
            if change.kind == "changed":
                findings.append(_finding(new_path, change))
            elif change.kind == "absent":
                gone.append((old_path, change))
            else:
                new.append((new_path, change, profile))

    for path, change in gone:
        twin = next(
            (n for n in new if n[1].test == change.test and n[1].is_test == change.is_test), None
        )
        if twin is None:
            findings.append(_finding(path, change))
        elif twin[1].fingerprint != change.fingerprint:
            new.remove(twin)
            moved = twin[1].model_copy(
                update={"reason": f"differs from its version in {path} before the move"}
            )
            findings.append(_finding(twin[0], moved))
        else:
            new.remove(twin)

    added_tests = [n for n in new if n[1].is_test]
    for entry in new:
        path, change, profile = entry
        if entry in added_tests and len(added_tests) == 1:
            allowed = _characterization(repo, base, head, path, change, profile)
            if allowed is not None:
                findings += allowed
                continue
        findings.append(_finding(path, change))
    return findings
