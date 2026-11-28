"""The shape of a repository's tests: the five figures `abk tests report` prints.

Figures 1, 2 and 4 read the default branch's tree, and figures 2 and 3 its first-parent
commits in the window, so uncommitted work and a branch's own commits are never counted.
Each file is read by the profile of the project that holds it; a profile that refuses the
test-reading capability (`ProfileUnsupported`) has its files left out and named.
"""

from __future__ import annotations

import json
import statistics
import subprocess
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from pathlib import PurePosixPath

from agent_build_kit import profiles
from agent_build_kit.config import owning_project
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.run_log import TestRun, run_ledger_path
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import local_ref
from agent_build_kit.profiles.base import (
    ComparesTests,
    ProfileUnsupported,
    ReadsTestShape,
    ToolchainProfile,
)

# Folders whose test files are not unit tests.
WIDER_FOLDERS = frozenset({"integration", "e2e"})

_DEFINITIONS = (
    "Of the unit-test files (named as tests by the profile, not conftest, outside integration "
    "and e2e folders), those that are not the one test_<module> file of a source module.",
    "Of the test files added in the window (not renamed), those not for a source module "
    "added in the window.",
    "Tests added and existing tests whose body changed in the window's first-parent commits "
    "on the default branch, not a test moved to another file, nor one changed by an import "
    "rename; and their ratio.",
    "Tests that share setup and action with a sibling in their file and differ only in "
    "assertions, and the share of tests with exactly one assertion.",
    "The tests and unit-test files at the tip, and the median minutes of the repository's "
    "whole-suite runs in the window, from the run ledger.",
)


class ShapeReport(Frozen):
    """The five figures of one repository's tests.

    A figure whose files no supporting profile read is None, and `unsupported_profile` names
    the profile that refused. `left_out` names the projects whose files were not read, as
    `<path> (<profile>)`; `unreadable` counts the files that did not parse."""

    repo: str
    # 1. Unit-test files not named `test_<module>` for a source module, of all unit-test files.
    unplaced: int | None = None
    unit_test_files: int | None = None
    # 2. Test files added in the window that are not for a source module added in it, of all.
    new_files_not_for_new_module: int | None = None
    new_files: int | None = None
    # 3. Tests added, and existing tests modified, in the window's commits.
    added: int = 0
    modified: int = 0
    # 4. Tests sharing setup and action with a sibling, tests with one assertion, of all read.
    sharing: int | None = None
    single_assertion: int | None = None
    tests_read: int | None = None
    # 5. The suite at the tip, and the median minutes of the window's whole-suite runs.
    suite_tests: int | None = None
    suite_files: int | None = None
    median_minutes: float | None = None
    full_runs: int = 0
    unsupported_profile: str | None = None
    left_out: tuple[str, ...] = ()
    unreadable: int = 0


def definition(figure: int) -> str:
    """The sentence that defines figure 1 to 5, printed with it."""
    return _DEFINITIONS[figure - 1]


Run = Callable[..., subprocess.CompletedProcess[str]]


class _Files:
    """The files of a repository's tree, each read by the profile of its project."""

    def __init__(self, installation: Installation, name: str, run: Run) -> None:
        self.repo = installation.repo(name)
        self.name = name
        self.checkout = installation.checkouts[name]
        self.run = run
        self.refused: dict[str, str] = {}
        self.reads = 0

    def owner(self, path: str) -> tuple[str, str, str]:
        """(project label, profile name, path relative to the project) of a repo path."""
        project = owning_project(list(self.repo.projects), path)
        if project is None:
            return self.name, self.repo.profile, path
        return project.path, project.profile, path.removeprefix(project.prefix)

    def reader(self, path: str) -> tuple[ToolchainProfile, str] | None:
        """The profile that reads `path` and the path relative to its project; None, noted as
        left out, for a profile that refuses."""
        label, profile_name, rel = self.owner(path)
        profile = profiles.get(profile_name)
        try:
            if isinstance(profile, ReadsTestShape):
                profile.is_source_module(rel)
                self.reads += 1
                return profile, rel
        except ProfileUnsupported:
            pass
        self.refused[label] = profile_name
        return None

    def is_unit_test(self, profile: ToolchainProfile, rel: str) -> bool:
        directories = PurePosixPath(rel).parts[:-1]
        return (
            profile.is_test_path(rel)
            and isinstance(profile, ReadsTestShape)
            and profile.test_module_name(rel) is not None
            and not WIDER_FOLDERS.intersection(directories)
        )

    def show(self, rev: str, path: str) -> str | None:
        done = self.run(self.checkout, "show", f"{rev}:{path}", check=False)
        return done.stdout if done.returncode == 0 else None


def _tree(files: _Files, ref: str) -> list[str]:
    listed = files.run(files.checkout, "ls-tree", "-r", "-z", "--name-only", ref, check=False)
    return [p for p in listed.stdout.split("\0") if p]


def _changes(files: _Files, commit: str) -> list[tuple[str, list[str], str]]:
    """(status letter, paths, parent) of each file a first-parent commit changes."""
    parent = files.run(files.checkout, "rev-parse", "--verify", "-q", f"{commit}^1", check=False)
    base = (
        parent.stdout.strip()
        if parent.returncode == 0
        else files.run(files.checkout, "hash-object", "-t", "tree", "/dev/null").stdout.strip()
    )
    tokens = files.run(
        files.checkout, "diff", "--name-status", "-M", "-z", base, commit
    ).stdout.split("\0")
    found: list[tuple[str, list[str], str]] = []
    i = 0
    while i < len(tokens) and tokens[i]:
        count = 2 if tokens[i][0] in "RC" else 1
        found.append((tokens[i][0], tokens[i + 1 : i + 1 + count], base))
        i += 1 + count
    return found


def _commits(files: _Files, ref: str, since: date, now: datetime) -> list[str]:
    window = files.run(
        files.checkout,
        "log",
        "--first-parent",
        "--format=%H",
        f"--since={since.isoformat()}T00:00:00+00:00",
        f"--until={now.isoformat()}",
        ref,
        check=False,
    )
    return window.stdout.split()


def _ledger_minutes(
    installation: Installation, name: str, since: date, now: datetime
) -> list[float]:
    """The minutes of the whole-suite runs of the repository's units in the window."""
    try:
        owned = {
            u.id for u in UnitStore(installation.state_dir / "units.json").all() if u.repo == name
        }
    except (ValueError, OSError):
        return []
    ledger = run_ledger_path(installation.state_dir)
    start = datetime.combine(since, time.min, UTC)
    minutes: list[float] = []
    for path in (ledger.with_name(ledger.name + ".1"), ledger):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                run = TestRun.model_validate(json.loads(line))
                began = datetime.fromisoformat(run.started)
            except ValueError:
                continue
            began = began if began.tzinfo else began.replace(tzinfo=UTC)
            if (
                run.unit in owned
                and run.full is True
                and not run.reused
                and not run.timed_out
                and run.outcome in ("passed", "failed")
                and start <= began <= now
            ):
                minutes.append(run.seconds / 60)
    return minutes


def shape_report(
    installation: Installation,
    name: str,
    *,
    since: date,
    now: datetime,
    run: Run = git,
) -> ShapeReport:
    """The figures of the repository `name`: its default branch's tests, the commits from
    `since` to `now`, and the installation's run ledger and unit store."""
    files = _Files(installation, name, run)
    ref = local_ref(files.repo.default_branch, repo=name)

    tree = _tree(files, ref)
    sources: set[str] = set()
    unit_tests: list[tuple[ReadsTestShape, str, str]] = []
    for path in tree:
        found = files.reader(path)
        if found is None:
            continue
        profile, rel = found
        assert isinstance(profile, ReadsTestShape)
        if profile.is_source_module(rel):
            sources.add(PurePosixPath(rel).stem)
        elif files.is_unit_test(profile, rel):
            unit_tests.append((profile, rel, path))
    supported = files.reads > 0 or not files.refused

    unplaced = sum(1 for p, rel, _ in unit_tests if p.test_module_name(rel) not in sources)
    sharing = single = total = unreadable = 0
    for profile, rel, path in unit_tests:
        text = files.show(ref, path)
        read = profile.read_test_file(rel, text or "")
        if not read.readable:
            unreadable += 1
            continue
        keys = Counter(t.key for t in read.tests)
        total += len(read.tests)
        sharing += sum(1 for t in read.tests if keys[t.key] > 1)
        single += sum(1 for t in read.tests if t.assertions == 1)

    new_tests: list[str] = []
    new_sources: set[str] = set()
    added = modified = 0
    for commit in _commits(files, ref, since, now):
        gone: Counter[str] = Counter()
        arrived: list[str] = []
        changed = 0
        for code, paths, base in _changes(files, commit):
            found = files.reader(paths[-1])
            if found is None:
                continue
            profile, rel = found
            assert isinstance(profile, ReadsTestShape)
            if code == "A" and profile.is_source_module(rel):
                new_sources.add(PurePosixPath(rel).stem)
            if code == "A" and files.is_unit_test(profile, rel):
                module = profile.test_module_name(rel)
                new_tests.append(module or "")
            if not isinstance(profile, ComparesTests) or not profile.is_test_path(rel):
                continue
            before = "" if code == "A" else files.show(base, paths[0])
            after = "" if code == "D" else files.show(commit, paths[-1])
            if before is None or after is None:
                continue
            for change in profile.compare_test_sources(rel, before, after):
                if not change.is_test or not change.test:
                    continue
                if change.kind == "changed":
                    changed += 1
                elif change.kind == "absent":
                    gone[change.fingerprint] += 1
                else:
                    arrived.append(change.fingerprint)
        modified += changed
        for fingerprint in arrived:
            if gone[fingerprint] > 0:
                gone[fingerprint] -= 1
            else:
                added += 1

    minutes = _ledger_minutes(installation, name, since, now)
    left_out = tuple(f"{label} ({profile})" for label, profile in files.refused.items())
    figures = dict(
        unplaced=unplaced,
        unit_test_files=len(unit_tests),
        new_files_not_for_new_module=sum(1 for module in new_tests if module not in new_sources),
        new_files=len(new_tests),
        sharing=sharing,
        single_assertion=single,
        tests_read=total,
        suite_tests=total,
        suite_files=len(unit_tests),
    )
    return ShapeReport(
        repo=name,
        **(figures if supported else {}),
        added=added,
        modified=modified,
        median_minutes=statistics.median(minutes) if minutes else None,
        full_runs=len(minutes),
        unsupported_profile=None if supported else next(iter(files.refused.values())),
        left_out=left_out,
        unreadable=unreadable,
    )
