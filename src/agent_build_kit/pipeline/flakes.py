"""A flaky test: told from a failure by running it alone, recorded, and fixed once.

When tier 1 fails on tests, the failed tests are run again serially. A test that fails
again is a failure. One that passes both reruns is a flake: it is recorded, it gets one
change that makes it deterministic, and every unit that met it waits on that change.
"""

from __future__ import annotations

import ast
import hashlib
import re
from datetime import datetime
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.work_graph import GROUP_HEADING, group_needs

# The longest a change's name gets before it is cut and given a hash of the whole.
NAME_LIMIT = 70
# Where a module imported by a test may sit in the code repo, relative to its root.
SOURCE_ROOTS = ("", "src")
CAPABILITY = "test-determinism"


class Flake(Frozen):
    """One test that failed under load and passed alone."""

    test: str
    command: str
    output: str
    at: datetime
    # Set by whoever records it: tier 1 does not know which unit it ran for.
    unit: str = ""
    # The change that fixes the test, once there is one.
    change: str = ""
    # Where tier 1 ran it (a project below the repo root, or the root), which its
    # identifier is relative to; empty when unknown.
    directory: str = ""


def waiting_note(tests: list[str]) -> str:
    """What a unit parked for these flaky tests is waiting for, in a person's words."""
    return f"waiting for the fix of the flaky test {', '.join(tests)}"


class FlakeFound(Exception):
    """Raised by tier 1 when every failed test passed both serial reruns: the unit is not
    failed for them, it waits for their fix."""

    def __init__(self, flakes: tuple[Flake, ...]) -> None:
        super().__init__(", ".join(flake.test for flake in flakes))
        self.flakes = flakes


class FlakeCount(Frozen):
    """A flaky test, how many times it flaked and the change that fixes it."""

    test: str
    count: int
    change: str


class FlakeRecord:
    """The flakes found, appended to a file in the state directory."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, flake: Flake) -> None:
        with file_lock(self.path.with_suffix(".lock")):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(flake.model_dump_json() + "\n")

    def entries(self) -> list[Flake]:
        """Every flake recorded, oldest first."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        return [Flake.model_validate_json(line) for line in lines if line.strip()]

    def counts(self) -> list[FlakeCount]:
        """Each flaky test once, with how often it flaked and its latest fix change."""
        counted: dict[str, FlakeCount] = {}
        for flake in self.entries():
            before = counted.get(flake.test)
            counted[flake.test] = FlakeCount(
                test=flake.test,
                count=(before.count if before else 0) + 1,
                change=flake.change or (before.change if before else ""),
            )
        return list(counted.values())


def flake_record(inst: Installation) -> FlakeRecord:
    return FlakeRecord(inst.state_dir / "flakes.jsonl")


def flake_change_name(test: str) -> str:
    """The name of the change that fixes `test`, from its identifier: lower-case words
    joined by hyphens, the same for the same test."""
    slug = re.sub(r"[^a-z0-9]+", "-", test.lower()).strip("-")
    name = f"fix-flaky-{slug}"
    if len(name) > NAME_LIMIT:
        name = f"{name[: NAME_LIMIT - 9].rstrip('-')}-{hashlib.sha1(test.encode()).hexdigest()[:8]}"
    return name


def wait_on_fix(inst: Installation, flake: Flake, unit: StoredUnit) -> str | None:
    """Make sure the one open change that fixes `flake.test` exists, under the state
    directory's lock, and give each group of `unit` a `Needs:` line on it. Returns the
    change's name, or None for a unit of that change itself, which waits on nothing."""
    with file_lock(inst.state_dir / "flakes.lock"):
        name, earlier = _open_change(inst, flake.test)
        if name is None:
            name = _next_name(inst, flake.test)
            _write_change(inst, name, flake, unit, earlier=earlier)
        if unit.change == name:
            return None
        for member in unit.members():
            for group in member.groups:
                _add_needs(inst, member.change, group, name, flake.test)
        return name


# --- which change ----------------------------------------------------------------


def _candidates(test: str):
    base = flake_change_name(test)
    yield base
    attempt = 2
    while True:
        yield f"{base}-{attempt}"
        attempt += 1


def _archived(inst: Installation, name: str) -> bool:
    return any((inst.changes_dir / "archive").glob(f"*-{name}"))


def _open_change(inst: Installation, test: str) -> tuple[str | None, str]:
    """The open change for `test`, or None and the last archived attempt (or "")."""
    earlier = ""
    for name in _candidates(test):
        if (inst.changes_dir / name).is_dir():
            return name, earlier
        if not _archived(inst, name):
            return None, earlier
        earlier = name
    raise AssertionError("unreachable")


def _next_name(inst: Installation, test: str) -> str:
    for name in _candidates(test):
        if not (inst.changes_dir / name).exists() and not _archived(inst, name):
            return name
    raise AssertionError("unreachable")


# --- the Needs: line -------------------------------------------------------------


def _add_needs(inst: Installation, change: str, group: int, fix: str, test: str) -> None:
    tasks = inst.changes_dir / change / "tasks.md"
    if not tasks.is_file():
        return
    # The lock `task_progress.mark_groups` takes: units of one change share this file.
    with file_lock(tasks.with_name(f"{tasks.name}.lock")):
        if any(n.change == fix for n in group_needs(tasks).get(group, [])):
            return
        lines = tasks.read_text().splitlines()
        for index, line in enumerate(lines):
            heading = GROUP_HEADING.match(line)
            if heading and int(heading["number"]) == group:
                lines[index + 1 : index + 1] = [
                    "",
                    f"Needs: {fix} group 1 merged — flaky test {test}",
                ]
                tasks.write_text("\n".join(lines) + "\n")
                return


# --- the change that is written --------------------------------------------------


def _write_change(
    inst: Installation, name: str, flake: Flake, unit: StoredUnit, *, earlier: str
) -> None:
    root = inst.changes_dir / name
    (root / "specs" / CAPABILITY).mkdir(parents=True)
    (root / "proposal.md").write_text(_proposal(inst, flake, unit, earlier))
    (root / "design.md").write_text(_design(flake))
    (root / "tasks.md").write_text(_tasks(flake, unit))
    (root / "specs" / CAPABILITY / "spec.md").write_text(_spec(flake, successor=bool(earlier)))


def _proposal(inst: Installation, flake: Flake, unit: StoredUnit, earlier: str) -> str:
    history = [e for e in flake_record(inst).entries() if e.test == flake.test]
    seen = [f"- {e.at:%Y-%m-%d %H:%M} UTC, unit {e.unit}" for e in history]
    seen.append(f"- {flake.at:%Y-%m-%d %H:%M} UTC, unit {flake.unit or unit.id} (this one)")
    modules = _modules_of(inst, unit.repo, flake)
    exercised = (
        "It exercises " + ", ".join(f"`{m}`" for m in modules) + "."
        if modules
        else "The module it exercises could not be found from its imports."
    )
    again = (
        f"\nAn earlier change, `{earlier}`, fixed this test and was merged and archived; "
        "it has flaked again.\n"
        if earlier
        else ""
    )
    return (
        "## Why\n\n"
        f"`{flake.test}` failed under load and passed alone, twice, when run again by itself. "
        "A test like that fails units that did not touch it.\n"
        f"{again}\n"
        f"It ran as `{flake.command}` and failed with:\n\n```\n{flake.output.strip()}\n```\n\n"
        f"{exercised}\n\n"
        "Times it flaked:\n\n" + "\n".join(seen) + "\n\n"
        "## What Changes\n\n"
        f"- `{flake.test}` is made deterministic, whether the fault is in the test or in the "
        "code it exercises.\n\n"
        "## Impact\n\n"
        f"- {unit.repo}: the test and, if it is the racy one, the module it exercises.\n"
    )


def _design(flake: Flake) -> str:
    return (
        "## Context\n\n"
        f"`{flake.test}` passes alone and fails under load.\n\n"
        "## Decisions\n\n"
        "- Is the test racy, or is the code it exercises racy? Decide from the failure, "
        "then fix that one.\n"
        "- The fix leaves nothing to wait on by the clock: an injected clock, an event "
        "waited on, or a step the test calls directly.\n"
    )


def _tasks(flake: Flake, unit: StoredUnit) -> str:
    return (
        "# Tasks\n\n"
        "Acceptance: none — a flaky test is made deterministic; nothing a consumer sees "
        "changes.\n\n"
        f"## 1. [{unit.repo}] [tier1] Make `{flake.test}` deterministic\n\n"
        "Priority: 2\n\n"
        "Done when the test passes under load every time, and under the repeat check.\n\n"
        f"- [ ] 1.1 Test: reproduce the race in `{flake.test}` deterministically, without "
        "waiting on the clock, so it fails every time before the fix.\n"
        "- [ ] 1.2 Make the test pass: decide whether the test or the code it exercises is "
        "racy, fix that one, and run the test under the repeat check.\n"
    )


def _spec(flake: Flake, *, successor: bool) -> str:
    # The earlier attempt's archive added this requirement to the capability, and an
    # archive refuses to add one that exists: a successor restates it.
    verb = "MODIFIED" if successor else "ADDED"
    return (
        f"## {verb} Requirements\n\n"
        f"### Requirement: `{flake.test}` is deterministic\n\n"
        "The test SHALL give the same result however loaded the machine running it is.\n\n"
        "#### Scenario: Run repeatedly under load\n\n"
        "- **WHEN** the test is run repeatedly under parallel load\n"
        "- **THEN** it passes every time\n"
    )


def _modules_of(inst: Installation, repo: str, flake: Flake) -> list[str]:
    """The files of the code repo that the test file imports, found from its imports. The
    identifier is relative to the directory tier 1 ran in, else to the checkout's root."""
    checkout = inst.checkouts.get(repo)
    if checkout is None:
        return []
    file = flake.test.split("::", 1)[0]
    where = [Path(flake.directory)] if flake.directory else []
    for base in [*where, checkout]:
        try:
            tree = ast.parse((base / file).read_text())
        except (OSError, SyntaxError):
            continue
        break
    else:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.append(node.module)
    found: list[str] = []
    for name in names:
        relative = Path(*name.split("."))
        for root in SOURCE_ROOTS:
            for candidate in (relative.with_suffix(".py"), relative / "__init__.py"):
                if (base / root / candidate).is_file():
                    full = base / root / candidate
                    shown = (
                        full.relative_to(checkout) if full.is_relative_to(checkout) else full
                    ).as_posix()
                    if shown not in found:
                        found.append(shown)
                    break
            else:
                continue
            break
    return found
