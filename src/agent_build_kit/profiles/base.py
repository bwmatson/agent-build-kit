"""What the pipeline needs to know about a repo's toolchain.

The pipeline lints, runs tests, reads their results, tells test files from
implementation and checks that a stub is only a stub. Every one of those is
language-specific, so each lives in a profile and the rest of the pipeline
asks the profile. A repo names its profile in abk.yaml (`profile:`).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from agent_build_kit.config import AgentCommand, BuildersConfig, EnvironmentConfig, RepoConfig
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.e2e import E2eSelection, TestFailure, TestTime


class ProfileUnsupported(NotImplementedError):
    """The toolchain profile does not implement what a run needs; held for a person."""


class PromptWords(Frozen):
    """The toolchain-specific phrases the build prompts use."""

    # What "the checks pass" means before an agent may stop.
    verify: str = "linting, formatting and type checks"
    # What a permitted stub looks like in a tests-first commit.
    stub: str = "a signature whose body is only a raise-not-implemented, or a data field"


@runtime_checkable
class EnvironmentDrafting(Protocol):
    """The optional hook a profile has to draft `abk init`'s `environment` section.

    A profile without it counts as returning None, which means "cannot say": the
    next profile is asked. `framework` says the pipeline itself runs from this
    environment, so its check loads the framework."""

    def detect_environment(self, root: Path, *, framework: bool) -> EnvironmentConfig | None: ...


@runtime_checkable
class ProjectScaffold(Protocol):
    """The optional hook a profile adds to write the smallest manifest its own detection
    recognises, for `abk project init --scaffold`. A profile without it cannot scaffold."""

    def scaffold_manifest(self, name: str) -> tuple[str, str]:
        """The manifest's file name (relative to the project directory) and its text, for a
        project called `name`."""
        ...


@runtime_checkable
class ProjectChecks(Protocol):
    """The optional hook a profile adds for unit-test commands about one project, such as a
    type check, which cannot be scoped to files. A profile without it counts as returning
    an empty list."""

    def project_checks(self, repo: RepoConfig) -> list[list[str]]:
        """Run in the directory of each project the unit touched that uses this profile,
        whatever the repo's own profile; in the checkout root for a repo with no projects."""
        ...


@runtime_checkable
class AgentCommands(Protocol):
    """The optional attribute a profile adds to name the commands a build agent may run.
    A profile without it counts as naming none."""

    agent_commands: tuple[AgentCommand, ...]


@runtime_checkable
class CreatedFiles(Protocol):
    """The optional hook a profile adds to name the files its own commands create or
    rewrite in a worktree, such as a lock file the repository does not commit. A profile
    without it counts as returning an empty list."""

    def created_files(self, repo: Path) -> list[str]:
        """Paths or patterns relative to `repo`, `/` separated; `[]` for none. Not what a
        build produces (that is `environment.artifacts`). The pipeline owns them: it never
        holds a unit for them or commits an untracked one. A path that is absolute, has `..`
        or names `.git` is dropped."""
        ...


# The home shorthand, held apart so no line reads as a path under a home directory.
HOME = "~"


class SandboxPaths(Frozen):
    """What a profile's toolchain needs under the sandbox: folders to read, cache folders to
    write and package index hosts. Paths may start with `~`."""

    read: tuple[str, ...] = ()
    write: tuple[str, ...] = ()
    hosts: tuple[str, ...] = ()


@runtime_checkable
class AppliesFixers(Protocol):
    """The optional hook a profile adds to say how its formatters and auto-fixers are applied
    to files. A profile without it gets no fixer pass."""

    def fix_command(self, files: list[str]) -> list[str] | None:
        """The argv that applies the profile's fixers to `files`, relative to the project's
        directory, run with the files already in it; None when none of them is one the
        profile fixes."""
        ...


@runtime_checkable
class LocatesCheckConfig(Protocol):
    """The optional hook a profile adds to find a check's configuration file above the folder
    the check runs in. A profile without it has its commands run as they are."""

    def with_check_config(self, command: list[str], where: Path, root: Path) -> list[str]:
        """`command` (an argv, or a `sh -c` one holding the command as its last element)
        with the argument naming the configuration for a run in `where`: the file in `where`,
        else the nearest in a folder above it up to `root`, given relative to `where`.
        `command` itself when it is not one of the profile's checks or no file exists."""
        ...


def supports_stubs(profile: object) -> bool:
    """Whether `profile` declares `supports_stubs` true; a profile without it, or one that
    says anything but true, does not support them."""
    return getattr(profile, "supports_stubs", False) is True


def stubbed_build(builders: BuildersConfig, profile: object) -> bool:
    """Whether a build is stubbed: `builders.stubbed_tdd_commits` is on and `profile`
    supports stubs."""
    return builders.stubbed_tdd_commits and supports_stubs(profile)


class ToolchainProfile(Protocol):
    name: str
    # Files whose presence in a repo root suggests this profile (init's detection).
    detect_markers: tuple[str, ...]
    # Tool patterns to allow in addition to the base list, in Claude Code's
    # `--allowedTools` syntax; no effect under the acp runtime.
    allowed_tools: str
    prompt_words: PromptWords
    # `supports_stubs: bool` is deliberately not declared here: a profile adds it
    # to opt in, and `supports_stubs()` reads it tolerantly.

    # The test runner's exit status when nothing was selected.
    no_tests_collected_exit: int

    def lint_command(self, base: str) -> list[str]: ...

    def lint_command_all_files(self) -> list[str]: ...

    def test_commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]: ...

    def test_commands_all(self, repo: Path, *, root_extras: list[str]) -> list[list[str]]: ...

    def tolerates_exit(self, command: list[str], returncode: int) -> bool: ...

    def failure_kind(self, output: str) -> str:
        """`lint`, `types` or `test`: which check a failed unit-test command was,
        from the `$ command (exit N)` header and output the pipeline keeps."""
        ...

    def extra_checks(self, repo: RepoConfig) -> list[list[str]]:
        """Further unit-test commands about the checkout as a whole (a changelog), beyond lint
        and tests. Unit-test runs the repo profile's once, in the checkout root. What is about
        one project is `ProjectChecks`."""
        ...

    def e2e_commands(self, repo: Path, *, marker: str) -> list[list[str]]: ...

    def acceptance_commands(
        self,
        checkout: Path,
        paths: list[str],
        *,
        marker: str,
        exclude_marker: str,
        root_extras: list[str],
    ) -> list[list[str]]: ...

    def clean_command(self, *, types: bool = False) -> str: ...

    def red_command(self, files: list[str]) -> str: ...

    def interpret_red(
        self, output: str, exit_code: int, *, stubbed: bool = False
    ) -> tuple[bool, list[str]]: ...

    def parse_test_summary(self, output: str) -> tuple[int, int, int, float]: ...

    def parse_test_failures(self, output: str) -> list[TestFailure]: ...

    def parse_test_durations(self, output: str) -> list[TestTime]:
        """One entry per phase of each test the runner timed, in the order printed; an
        output with no durations, or a toolchain that prints none, gives `[]`."""
        ...

    def without_durations(self, output: str) -> str:
        """`output` without the section `parse_test_durations` reads, for the text a result
        keeps: the listing carries it, and it would push the failures out of a cut output.
        A toolchain that prints none returns it unchanged."""
        ...

    def is_test_path(self, path: str) -> bool: ...

    def collects_path(self, path: str) -> bool: ...

    def stub_violations(self, path: str, content: str) -> list[str]: ...

    def members(self, repo: Path) -> list[str]: ...

    def member_of(self, repo: Path, path: str) -> str | None: ...

    def dependents(self, repo: Path, member: str) -> list[str]: ...


@runtime_checkable
class RepeatsTests(Protocol):
    """The optional hook a profile adds to run chosen tests again under the load of a
    test run. A profile without it has no repeat check."""

    def repeat_command(self, command: list[str], tests: list[str]) -> list[str] | None:
        """`command`, one of the profile's test runs, as a run of exactly those of `tests`
        that it runs, under the same workers and markers. Each is an identifier the runner
        selects by, given relative to the directory the command runs in. None when none of
        them is one this command runs (a test of another project belongs to that project's
        command, in its environment)."""
        ...


@runtime_checkable
class ReportsRunFacts(Protocol):
    """The optional hooks a profile adds to say what a test run's own command and a query of the
    runner tell of the conditions it ran under, for the evidence kept of a failing run. A runner
    prints no versions at the verbosity the profile runs it at, so they come from a query."""

    def version_probe(self, command: list[str]) -> list[str] | None:
        """A command that prints the versions of the runner and its plugins in the environment
        `command` (one of the profile's test runs) uses; None when there is none."""
        ...

    def run_facts(self, command: list[str], probe_output: str) -> dict[str, object]:
        """`{"workers_setting": what the command asked for, "workers": the count when the command
        fixes it, "max_workers": its cap, "versions": {name: version}}`, the workers read from
        `command` and the versions from what `version_probe` printed; a key it cannot fill is
        left out, and a setting the runner resolves itself is not guessed."""
        ...


@runtime_checkable
class AppliesE2eSelection(Protocol):
    """The optional hooks a profile adds to apply an e2e-test selection: the kinds of selector
    it can apply, the text its test runner takes for a selection, and a listing of the tests
    a selection holds. A profile without them cannot leave a split out."""

    selector_kinds: tuple[str, ...]

    def expression(self, marker: str, selection: E2eSelection) -> str:
        """What the test runner takes to select `selection` over the repo's `marker`. Raises
        ValueError for an empty selection, which selects nothing."""
        ...

    def list_tests(
        self,
        command: list[str],
        selection: E2eSelection,
        *,
        run: Callable[..., subprocess.CompletedProcess],
        among: list[str] | None = None,
    ) -> list[str] | None:
        """The identifiers `command` would run under `selection`, relative to the
        repository root, narrowed to `among` when given. The selection replaces the command's
        own marker expression and is not ANDed with it. An empty list when it selects none;
        None when the listing fails, since that says nothing about what is selected."""
        ...


@runtime_checkable
class ListsRegisteredSelectors(Protocol):
    """The optional hook a profile adds to say which selectors its test runner knows, for
    `abk e2e-test check`. A profile without it has no selector to check."""

    def registered_selectors(
        self,
        command: list[str],
        *,
        run: Callable[..., subprocess.CompletedProcess],
    ) -> list[str] | None:
        """The selectors (for a marker kind, the marker names) the runner of `command`
        registers, read from the runner itself. None when the listing fails."""
        ...


@runtime_checkable
class SelectsAffectedTests(Protocol):
    """The optional hook a profile adds to name the tests a change affects. A profile
    without it behaves as one that returns None."""

    def affected_test_commands(
        self,
        repo: Path,
        changed_files: list[str],
        failed_ids: list[str],
        *,
        seed: Path,
        root_extras: list[str],
    ) -> list[list[str]] | None:
        """The commands that run the tests the change affects: an empty list when none
        is affected, None when the profile cannot say. `failed_ids` are the tests the
        failed check named; `seed` is a path the profile may keep selection data in;
        `root_extras` are what the repo's root tests need, as for `test_commands`."""
        ...


@runtime_checkable
class RecordsSelectionData(Protocol):
    """The optional hook a profile adds to keep, in a full run, the data its selection
    reads. A profile without it records nothing."""

    def seeding_command(self, command: list[str], seed: Path, *, select: bool = False) -> list[str]:
        """`command`, a test run, as one that keeps its selection data at `seed`: running
        all its tests, or only the affected ones when `select`."""
        ...

    def is_seeded(self, command: list[str]) -> bool:
        """Whether `command` is one `seeding_command` made, whose failure with no test result
        means the selection's tooling could not run."""
        ...


# Paths that are documentation. Never deploy anything, whatever the profile.
DOC_SUFFIXES = (".md", ".rst", ".txt")


def is_doc_path(path: str) -> bool:
    first = path.split("/", 1)[0]
    name = path.rsplit("/", 1)[-1]
    return path.endswith(DOC_SUFFIXES) or first == "docs" or name.upper().startswith("LICENSE")


def located(toolchain: object, command: list[str], where: Path, root: Path) -> list[str]:
    """`command` with the check configuration `toolchain` finds for a run in `where`, looking
    up to `root` (the checkout); as it is for a profile that finds none."""
    if not isinstance(toolchain, LocatesCheckConfig):
        return command
    return toolchain.with_check_config(command, where, root)
