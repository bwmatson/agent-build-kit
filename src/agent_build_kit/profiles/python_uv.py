"""The profile for a Python repo managed by uv, tested with pytest and gated
by pre-commit (ruff, a type checker).

A uv workspace is tested one member at a time in its own environment, the way
such a repo's CI runs: every member tends to own a top-level `src` package, so
one shared environment holding all of them makes one member's tests import
another's. `--package <member> --isolated` reproduces the one-member
environment, so the collision cannot happen.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

from agent_build_kit.config import (
    DraftedEnvironment,
    EnvironmentConfig,
    EnvironmentInputs,
    RepoConfig,
)
from agent_build_kit.pipeline.commit_order import stub_violations as _stub_violations
from agent_build_kit.pipeline.red_check import judge_red, split_report, wrap_report_command
from agent_build_kit.pipeline.tier2 import (
    TestFailure,
    TestTime,
    Tier2Selection,
    clip_failure_line,
    parse_pytest_summary,
)
from agent_build_kit.profiles.base import PromptWords, is_doc_path

# pytest's exit status when every test was deselected: "nothing to run here",
# not a failure — most members carry no tier-2 tests.
NO_TESTS_COLLECTED = 5

_TEST_FILE = re.compile(r"^(test_.*|.*_test|conftest)\.py$")
_DEP_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
XDIST = "pytest-xdist"
MANIFEST = "pyproject.toml"
LOCK = "uv.lock"
WORKERS = ["-n", "auto", "--maxprocesses=8"]
# A FAILED/ERROR line for each failed test, with a short traceback each. `-vv` as well:
# below it pytest cuts each summary message to the terminal width, and drops it when the
# test id fills the line.
SUMMARY_FLAGS = ["-vv", "-rfE", "--tb=short"]
# Every phase of every test that took a second or more, slowest first, in one section.
DURATION_FLAGS = ["--durations=0", "--durations-min=1.0"]
DURATIONS_RULE = re.compile(r"^=+ slowest (?:\d+ )?durations =+\s*$")
DURATION_ENTRY = re.compile(r"^(\d+(?:\.\d+)?)s +(setup|call|teardown) +(\S.*)$")
SUMMARY_MARK = "short test summary info"
SUMMARY_ENTRY = re.compile(r"^(?:FAILED|ERROR) (.+?)(?: - (.*))?$")
# The lock-freshness and environment-freshness commands a path-source draft's check starts with.
DRIFT_CHECKS = "uv lock --check && uv sync --check"
PATH_SOURCES_NOTE = (
    "The manifest names path sources, whose own manifest and lock are outside this\n"
    "repository and cannot be listed as inputs. `check` runs `uv lock --check` and\n"
    "`uv sync --check` first, so a change in a checkout it points at fails the check\n"
    "and the next tick syncs."
)


# The pre-commit hooks that are the type checker, by id.
TYPE_HOOKS = frozenset({"pyrefly-check", "pyrefly", "mypy", "pyright"})
_PYTEST = re.compile(r"\bpytest\b")
# pytest's short summary: `FAILED path::test - why` and `ERROR path::test - why`.
_FAILED_TEST = re.compile(r"^(?:FAILED|ERROR) (\S+::\S+)", re.MULTILINE)
# The `FAILURES` part of pytest's console output ends at the rule of the section that follows
# it, not at any `=== ... ===` line, which a failing test's captured output may print; each
# failed test's block in it starts at a `___ name ___` line, padded with as little as one
# underscore a side when the title is long.
_FAILURES_START = re.compile(r"^={3,} FAILURES ={3,}[ \t]*$", re.MULTILINE)
_AFTER_FAILURES = re.compile(
    r"^={3,} (?:warnings summary|short test summary info|slowest (?:\d+ )?durations"
    r"|.* in [\d.]+s(?: \([\d:]+\))?) ={3,}[ \t]*$",
    re.MULTILINE,
)
_BLOCK_HEADER = re.compile(r"^_+ (?P<name>.+?) _+[ \t]*$", re.MULTILINE)
# pre-commit prints `<hook name>....Passed|Failed|(no files to check)Skipped` for every
# hook; a failed one is followed by `- hook id: <id>`. The name is free text a repo can
# change, the id is what a hook is called in the config, so the id decides.
_HOOK_FAILED = re.compile(r"^\S.*?\.{3,}Failed[ \t]*\n- hook id: (?P<id>\S+)[ \t]*$", re.MULTILINE)


def _durations_section(lines: list[str]) -> tuple[int, int, list[str]]:
    """`(start, end, body)` of pytest's `slowest durations` section in `lines`: the last
    `=` rule whose title is the header (captured output may quote one earlier), through
    the line before the next `=` rule. An output with none gives `(len, len, [])`."""
    start = next(
        (i for i in range(len(lines) - 1, -1, -1) if DURATIONS_RULE.match(lines[i])), len(lines)
    )
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("=")), len(lines))
    return start, end, lines[start + 1 : end]


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pyproject(path: Path) -> dict:
    try:
        return tomllib.loads((path / "pyproject.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _path_sources(root: Path) -> list[Path]:
    """The checkouts the manifest names as path sources, that exist."""
    sources = _pyproject(root).get("tool", {}).get("uv", {}).get("sources", {})
    found = []
    for source in sources.values():
        path = source.get("path") if isinstance(source, dict) else None
        if isinstance(path, str) and (root / path).is_dir():
            found.append((root / path).resolve())
    return found


def _declared_dependencies(pyproject: dict) -> set[str]:
    """Every dependency name a pyproject declares: project, extras, groups."""
    project = pyproject.get("project", {})
    declared = list(project.get("dependencies", []))
    for extras in project.get("optional-dependencies", {}).values():
        declared += list(extras)
    for group in pyproject.get("dependency-groups", {}).values():
        declared += [dep for dep in group if isinstance(dep, str)]
    declared += list(pyproject.get("tool", {}).get("uv", {}).get("dev-dependencies", []))
    return {_normalize(m.group(1)) for dep in declared if (m := _DEP_NAME.match(str(dep)))}


def _declares_xdist(path: Path) -> bool:
    return XDIST in _declared_dependencies(_pyproject(path))


def _addopts_marker(repo: Path) -> str:
    """The `-m` expression the repo's own pytest addopts applies, if any."""
    options = _pyproject(repo).get("tool", {}).get("pytest", {}).get("ini_options", {})
    addopts = options.get("addopts", "")
    argv = shlex.split(addopts) if isinstance(addopts, str) else list(addopts)
    for i, arg in enumerate(argv):
        if arg == "-m" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("-m") and len(arg) > 2:
            return arg[2:]
    return ""


def _marker_selection(repo: Path, selection: str) -> str:
    # A later -m replaces the one in addopts, so keep the repo's exclusions.
    existing = _addopts_marker(repo)
    return f"({existing}) and {selection}" if existing else selection


def _is_serial_split(expression: str, *, serial: bool | None = None) -> bool:
    """Whether a `-m` expression is tier 1's serial/parallel split: the serial half
    (`serial`), the parallel half (`not serial`), or either when `serial` is None."""
    halves = {
        True: (expression == "serial" or expression.endswith(" and serial")),
        False: (expression == "not serial" or expression.endswith(" and not serial")),
    }
    return any(halves.values()) if serial is None else halves[serial]


def _is_serial_pass(command: list[str]) -> bool:
    if "-m" not in command[:-1]:
        return False
    return _is_serial_split(command[command.index("-m") + 1], serial=True)


def package_name(member: Path) -> str:
    """What a workspace member calls itself, falling back to its directory.

    A member with no parseable name should not take tier 1 down with it — the
    directory name is right often enough to be worth trying.
    """
    return str(_pyproject(member).get("project", {}).get("name") or member.name)


# What a tier 2 run adds to report on itself, not wanted in a listing of what it selects.
# Verbosity is set absolutely for a listing, so these relative flags must not stack on it.
_VERBOSITY_FLAGS = frozenset(["-q", "-qq", "-v", "-vv"])
_REPORT_FLAGS = frozenset([*SUMMARY_FLAGS, *DURATION_FLAGS, *_VERBOSITY_FLAGS])
# A line of `pytest --markers`: `@pytest.mark.<name>(<args>): <description>`.
_MARKER_LINE = re.compile(r"@pytest\.mark\.(?P<name>\w+)")
# Pytest's exit status when the selection holds no test.
_NO_TESTS_SELECTED = 5

# The pytest options that take their value as the next word.
_OPTIONS_WITH_VALUE = frozenset(["-n", "-m", "-k", "-p", "-c", "--maxprocesses"])


def _pytest_program(command: list[str]) -> int | None:
    """Where `pytest` is in `command`: the program, not the `--with pytest` that adds it to
    an environment."""
    return next(
        (i for i, word in enumerate(command) if word == "pytest" and command[i - 1] != "--with"),
        None,
    )


# The plugin that records, for each test, the source it executed, and selects by it.
TESTMON = "pytest-testmon"


class PythonUvProfile:
    name: str = "python-uv"
    detect_markers: tuple[str, ...] = ("uv.lock", "pyproject.toml")
    allowed_tools: str = (
        "Bash(uv run *) Bash(uv lock*) Bash(uv sync*) Bash(uv add *) Bash(uv remove *) "
        "Bash(pre-commit *)"
    )
    prompt_words: PromptWords = PromptWords(
        verify="linting, formatting and type checks (pre-commit)",
        stub="a signature whose body is only `raise NotImplementedError`, or a model field",
    )
    no_tests_collected_exit: int = NO_TESTS_COLLECTED

    # --- workspace shape -------------------------------------------------------

    def members(self, repo: Path) -> list[str]:
        """The uv workspace members declared in the root pyproject.toml; empty
        for a repo that is not a workspace, which is the signal to test it in
        place rather than member by member."""
        members = (
            _pyproject(repo).get("tool", {}).get("uv", {}).get("workspace", {}).get("members", [])
        )
        return [str(member) for member in members]

    def scaffold_manifest(self, name: str) -> tuple[str, str]:
        # A JSON string is a valid TOML basic string, and escapes quotes and backslashes.
        return "pyproject.toml", (
            f'[project]\nname = {json.dumps(name)}\nversion = "0.1.0"\nrequires-python = ">=3.12"\n'
        )

    def detect_environment(self, root: Path, *, framework: bool) -> EnvironmentConfig | None:
        """The section for the checkout at `root`, or None without a manifest.
        `framework` says the pipeline itself runs from this environment, so its
        check loads the framework."""
        root = root.expanduser().resolve()
        if not (root / MANIFEST).is_file():
            return None
        dependencies, lock = [MANIFEST], []
        if (root / LOCK).is_file():
            lock.append(LOCK)
        word = "import agent_build_kit" if framework else "pass"
        inputs = EnvironmentInputs(dependencies=dependencies, lock=lock)
        if not _path_sources(root):
            return EnvironmentConfig(
                sync=["uv", "sync"],
                check=["uv", "run", "--no-sync", "python", "-c", word],
                inputs=inputs,
            )
        # A path-source checkout's own manifest and lock are outside the inputs a pattern
        # can name, so the check is what notices them drift: the first failing command
        # makes the tick sync.
        quoted = f'"{word}"' if " " in word else word
        import_check = f"uv run --no-sync python -c {quoted}"
        return DraftedEnvironment(
            sync=["uv", "sync"],
            check=["sh", "-c", f"{DRIFT_CHECKS} && {import_check}"],
            inputs=inputs,
            note=PATH_SOURCES_NOTE,
        )

    def created_files(self, repo: Path) -> list[str]:
        """The lock file `uv run` creates where the repository has none."""
        return [LOCK]

    def member_of(self, repo: Path, path: str) -> str | None:
        for member in self.members(repo):
            if path == member or path.startswith(f"{member}/"):
                return member
        return None

    def dependents(self, repo: Path, member: str) -> list[str]:
        """The members that declare `member`'s package as a dependency, so a
        change in a library reaches everything built on it."""
        library = _normalize(package_name(repo / member))
        found = []
        for other in self.members(repo):
            if other == member:
                continue
            project = _pyproject(repo / other).get("project", {})
            declared = list(project.get("dependencies", []))
            for extras in project.get("optional-dependencies", {}).values():
                declared += list(extras)
            names = {
                _normalize(match.group(1))
                for dep in declared
                if (match := _DEP_NAME.match(str(dep)))
            }
            if library in names:
                found.append(other)
        return found

    # --- classifying paths -------------------------------------------------------

    def is_test_path(self, path: str) -> bool:
        parts = path.split("/")
        return "tests" in parts[:-1] or bool(_TEST_FILE.match(parts[-1]))

    def stub_violations(self, path: str, content: str) -> list[str]:
        return _stub_violations(path, content)

    # --- commands ------------------------------------------------------------------

    def lint_command(self, base: str) -> list[str]:
        # Scoped to the diff, not the repo: `--all-files` fails a unit for
        # problems in files it never touched.
        return ["uv", "run", "pre-commit", "run", "--from-ref", base, "--to-ref", "HEAD"]

    def lint_command_all_files(self) -> list[str]:
        # For a unit that produced no diff of its own to scope to: judging it
        # then means judging the whole repo at its tip, not an empty range.
        return ["uv", "run", "pre-commit", "run", "--all-files"]

    def clean_command(self) -> str:
        # Type checking is skipped at the tests commit: a test importing a
        # function that doesn't exist yet is the expected state there.
        return "SKIP=pyrefly-check uv run pre-commit run --all-files"

    def red_command(self, files: list[str]) -> str:
        # The report is printed after the console so it outlives the worktree
        # the command runs in; the exit status is pytest's own. It goes to a
        # fresh temp file, so a file already in the tree is never read as it.
        pytest = f"uv run pytest {' '.join(files)} -p no:cacheprovider --tb=line -q"
        return wrap_report_command(pytest, "--junitxml")

    def interpret_red(self, output: str, exit_code: int) -> tuple[bool, list[str]]:
        report, console = split_report(output)
        result = judge_red(report, console, exit_code)
        return result.verdict == "accepted", list(result.problems)

    def parse_test_summary(self, output: str) -> tuple[int, int, int, float]:
        return parse_pytest_summary(output)

    def parse_test_failures(self, output: str) -> list[TestFailure]:
        """One entry per `FAILED`/`ERROR` line of pytest's short summary, in the order
        printed; a long line is cut with an ellipsis."""
        _, found, summary = output.partition(SUMMARY_MARK)
        if not found:
            return []
        failures = []
        for line in summary.splitlines():
            matched = SUMMARY_ENTRY.match(line)
            # A message printed whole spans lines; one that begins with the word
            # `ERROR` is not an entry unless its id has the shape of a node id.
            if matched and ("::" in matched.group(1) or matched.group(1).endswith(".py")):
                first = clip_failure_line(matched.group(2) or "")
                failures.append(TestFailure(test=matched.group(1), line=first))
        return failures

    def parse_test_durations(self, output: str) -> list[TestTime]:
        """One entry per line of pytest's `slowest durations` section, in the order printed."""
        found: list[TestTime] = []
        for line in _durations_section(output.splitlines(keepends=True))[2]:
            if matched := DURATION_ENTRY.match(line):
                seconds, phase, test = matched.groups()
                found.append(TestTime(test=test.strip(), phase=phase, seconds=float(seconds)))
        return found

    def without_durations(self, output: str) -> str:
        """`output` without the `slowest durations` section: its header, its entries and the
        note of those hidden, up to the next `=` rule line."""
        lines = output.splitlines(keepends=True)
        start, end, _ = _durations_section(lines)
        return "".join(lines[:start] + lines[end:])

    def _root_tests(self, repo: Path, root_extras: list[str]) -> list[list[str]]:
        # The repo-root tests/, which belongs to no member, in the same
        # environment its CI job uses: pytest plus whatever it declares.
        withs = [arg for extra in ["pytest", *root_extras] for arg in ("--with", extra)]
        head = ["uv", "run", "--no-project", "--isolated", *withs]
        # The environment holds only what root_extras names, so workers need it there.
        workers = any(_normalize(extra.split("[")[0]) == XDIST for extra in root_extras)
        return self._passes(head, ["tests"], parallel=workers, repo=repo)

    def _passes(
        self, head: list[str], target: list[str], *, parallel: bool, repo: Path
    ) -> list[list[str]]:
        """One pytest command, or — where xdist is declared — what `poe test`
        runs: a parallel pass, then the tests marked `serial` on their own."""
        command = [*head, "pytest", *target]
        if not parallel:
            return [[*command, "-q"]]
        return [
            [*command, *WORKERS, "-m", _marker_selection(repo, "not serial"), "-q"],
            [*command, "-m", _marker_selection(repo, "serial"), "-q"],
        ]

    def tolerates_exit(self, command: list[str], returncode: int) -> bool:
        """Whether a tier 1 command's exit status is a pass. The serial pass
        collects nothing in a repo with no `serial` tests, which is not a failure."""
        if returncode == 0:
            return True
        return returncode == NO_TESTS_COLLECTED and _is_serial_pass(command)

    def failure_kind(self, output: str) -> str:
        """Which check failed, from the command in the failure's `$` header: a
        pytest command is `test`; the pre-commit run is `types` when a type
        checker's hook is among those that `Failed` (its passing hooks are
        listed too, so only the failed blocks count; each is matched by the `hook id`
        line under it). The output is the tail pre-commit printed, so a type
        checker's failed block followed by more than the kept tail of a later
        hook's output reads as `lint`; the usual hook order puts the type checker last."""
        header = output.lstrip().split("\n", 1)[0]
        if header.startswith("$ ") and "pre-commit" not in header and _PYTEST.search(header):
            return "test"
        failed = {m.group("id") for m in _HOOK_FAILED.finditer(output)}
        return "types" if failed & TYPE_HOOKS else "lint"

    def failed_tests(self, output: str) -> list[str]:
        """The identifiers of the tests that failed or errored, read from a failed tier 1
        command's output; empty when it was not a test run."""
        found = _FAILED_TEST.findall(output)
        return list(dict.fromkeys(found))

    def failure_sections(self, output: str) -> dict[str, str]:
        """Each failed test's own section of `output` (its `___ name ___` block), by the
        identifier `failed_tests` gives it. A test with no block is left out."""
        start = _FAILURES_START.search(output)
        if start is None:
            return {}
        part = output[start.end() :]
        end = _AFTER_FAILURES.search(part)
        if end is not None:
            part = part[: end.start()]
        headers = list(_BLOCK_HEADER.finditer(part))
        blocks = [
            (
                header["name"],
                part[header.end() : headers[i + 1].start() if i + 1 < len(headers) else None],
            )
            for i, header in enumerate(headers)
        ]
        sections: dict[str, str] = {}
        for test in self.failed_tests(output):
            # The header shows the class and test joined by dots, and any parametrisation.
            name = ".".join(test.split("::")[1:])
            for index, (shown, body) in enumerate(blocks):
                if shown == name:
                    sections[test] = body.strip()
                    del blocks[index]
                    break
        return sections

    def serial_rerun_command(self, command: list[str], tests: list[str]) -> list[str]:
        """`command`, a failed test run, as one that runs only `tests`, serially."""
        program = _pytest_program(command)
        if program is None:
            return [*command, *tests]
        # What follows is the run's selection and workers: dropped, a tier 2 marker expression
        # kept (tier 1's serial/parallel split is what the serial rerun replaces).
        words = command[program + 1 :]
        marker: list[str] = []
        if "-m" in words[:-1]:
            expression = words[words.index("-m") + 1]
            marker = [] if _is_serial_split(expression) else ["-m", expression]
        return [*command[: program + 1], *marker, *tests, "-q"]

    selector_kinds: tuple[str, ...] = ("marker",)

    def expression(self, marker: str, selection: Tier2Selection) -> str:
        """The `-m` text of `selection` over `marker`; a ValueError for an empty selection,
        which would otherwise read as every tier 2 test."""
        if selection.empty:
            held = ", ".join(selection.left_out)
            raise ValueError(f"every split is held ({held}): nothing to run")
        parts = [marker, *(f"not {tag}" for tag in selection.none_of)]
        if len(selection.any_of) == 1:
            parts.append(selection.any_of[0])
        elif selection.any_of:
            parts.append(f"({' or '.join(selection.any_of)})")
        return " and ".join(parts)

    def list_tests(
        self,
        command: list[str],
        selection: Tier2Selection,
        *,
        run: Callable[..., subprocess.CompletedProcess],
        among: list[str] | None = None,
    ) -> list[str] | None:
        """The identifiers `command` runs under `selection`, listed with pytest's collection,
        as paths from the repository root."""
        expression = self.expression(selection.marker, selection)
        program = _pytest_program(command)
        if program is None:
            return None
        narrowed = command if among is None else self.repeat_command(command, among)
        if narrowed is None:
            return []
        words = [w for w in narrowed[program + 1 :] if w not in _REPORT_FLAGS]
        if "-m" in words:
            words[words.index("-m") + 1] = expression
        else:
            words = ["-m", expression, *words]
        argv = [*narrowed[: program + 1], *words, "--collect-only", "--verbosity=-1"]
        result = run(argv, capture_output=True, text=True, check=False)
        if result.returncode not in (0, _NO_TESTS_SELECTED):
            return None
        where = ""
        if "--directory" in narrowed[:program]:
            where = narrowed[narrowed.index("--directory") + 1].strip("/") + "/"
        return [
            f"{where}{line.strip()}"
            for line in result.stdout.splitlines()
            if "::" in line and not line.startswith((" ", "ERROR"))
        ]

    def registered_selectors(
        self,
        command: list[str],
        *,
        run: Callable[..., subprocess.CompletedProcess],
    ) -> list[str] | None:
        """The marker names pytest lists for `command`'s environment with `--markers`."""
        program = _pytest_program(command)
        if program is None:
            return None
        result = run([*command[: program + 1], "--markers"], capture_output=True, text=True)
        if result.returncode != 0:
            return None
        return [
            match["name"]
            for line in result.stdout.splitlines()
            if (match := _MARKER_LINE.match(line))
        ]

    def repeat_command(self, command: list[str], tests: list[str]) -> list[str] | None:
        """`command`, a test run, as one of exactly those node ids of `tests` that fall under
        the paths it was given to run (all of them when it was given none): its options
        (workers, markers) stay, the paths are replaced by the ids. None when none is in
        scope, since the command's environment is not the one those tests run in."""
        program = _pytest_program(command)
        if program is None:
            return [*command, *tests]
        # `--directory <d>` runs pytest from `d`: the ids of other directories are not its
        # tests, and the rest are given as it sees them.
        if "--directory" in command[:program]:
            where = command[command.index("--directory") + 1].strip("/")
            tests = [t.removeprefix(f"{where}/") for t in tests if t.startswith(f"{where}/")]
        options: list[str] = []
        paths: list[str] = []
        words = iter(command[program + 1 :])
        for word in words:
            if word.startswith("-"):
                options.append(word)
                if word in _OPTIONS_WITH_VALUE:
                    options.append(next(words, ""))
            else:
                paths.append(word.rstrip("/"))
        ids = [
            test
            for test in tests
            if not paths
            or any(test.split("::", 1)[0] == p or test.startswith(f"{p}/") for p in paths)
        ]
        return [*command[: program + 1], *options, *ids] if ids else None

    def affected_test_commands(
        self,
        repo: Path,
        changed_files: list[str],
        failed_ids: list[str],
        *,
        seed: Path,
        root_extras: list[str],
    ) -> list[list[str]] | None:
        """The test commands of the change, selecting by the source each test executed when
        the seed data of an earlier full run is there; otherwise the failed tests alone,
        and None when none is named, so that the full suite stands in."""
        commands = self.test_commands(repo, changed_files, root_extras=root_extras)
        if seed.is_file():
            if not all(self._places(path) for path in changed_files):
                return None
            return [self.seeding_command(command, seed, select=True) for command in commands]
        alone = [self.repeat_command(command, failed_ids) for command in commands]
        return [command for command in alone if command is not None] or None

    def _places(self, path: str) -> bool:
        """Whether the coverage data can say which tests a change to `path` affects: a
        document touches none; a source or test module is what the data records; a lock or
        configuration file, a conftest or a shared test helper reaches tests it cannot name."""
        if is_doc_path(path):
            return True
        if not path.endswith(".py"):
            return False
        name = path.rsplit("/", 1)[-1]
        if name == "conftest.py":
            return False
        return not self.is_test_path(path) or bool(_TEST_FILE.match(name))

    def is_seeded(self, command: list[str]) -> bool:
        return TESTMON in command

    def seeding_command(self, command: list[str], seed: Path, *, select: bool = False) -> list[str]:
        """`command`, a test run, as one run with the coverage plugin in its isolated
        environment, keeping its data at `seed`: it selects the tests the change affects
        when `select`, and otherwise runs them all and records what each executed."""
        program = _pytest_program(command)
        if program is None:
            return command
        flag = "--testmon" if select else "--testmon-noselect"
        return [
            "env",
            f"TESTMON_DATAFILE={seed}",
            *command[:program],
            *["--with", TESTMON],
            *command[program : program + 1],
            flag,
            *command[program + 1 :],
        ]

    def _whole_repo_tests(self, repo: Path) -> list[list[str]]:
        # A repo that is not a workspace: no members to run one at a time.
        # No tests/ at all is intentional too — the satisfied verdict then
        # rests on lint alone, since there is nothing here to run.
        if not (repo / "tests").is_dir():
            return []
        return self._passes(["uv", "run"], [], parallel=_declares_xdist(repo), repo=repo)

    def _member_commands(self, repo: Path, members: list[str]) -> list[list[str]]:
        # `--package` names the package; the trailing path names the directory.
        # They differ more often than not.
        return [
            command
            for member in members
            for command in self._passes(
                ["uv", "run", "--package", package_name(repo / member), "--isolated"],
                [member],
                parallel=_declares_xdist(repo / member),
                repo=repo / member,
            )
        ]

    def test_commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        """How to run this repo's tests, matching what its CI does.

        A change outside every member — the root pyproject.toml, say, which is
        exactly where a pytest marker gets registered — affects all of them, so
        it tests all of them. Documentation is the one root change that cannot
        affect a test run.
        """
        members = self.members(repo)
        if not members:
            return self._whole_repo_tests(repo)

        testable = [member for member in members if (repo / member / "tests").is_dir()]
        touched = {
            member
            for member in testable
            for path in changed
            if path == member or path.startswith(f"{member}/")
        }
        outside = any(
            not path.endswith(".md")
            and not any(path.startswith(f"{member}/") for member in members)
            for path in changed
        )
        chosen = testable if outside else [m for m in testable if m in touched]
        root: list[list[str]] = []
        if (repo / "tests").is_dir() and (outside or any(p.startswith("tests/") for p in changed)):
            root = self._root_tests(repo, root_extras)
        return self._member_commands(repo, chosen) + root

    def test_commands_all(self, repo: Path, *, root_extras: list[str]) -> list[list[str]]:
        """Every testable member plus the root tests/, unconditionally.

        The whole-repo counterpart to `test_commands`: for a unit that
        produced no diff of its own, there is no "touched" or "outside" to
        scope to, so this runs everything `test_commands` would run for a
        change that reached outside every member.
        """
        members = self.members(repo)
        if not members:
            return self._whole_repo_tests(repo)

        testable = [member for member in members if (repo / member / "tests").is_dir()]
        root = self._root_tests(repo, root_extras) if (repo / "tests").is_dir() else []
        return self._member_commands(repo, testable) + root

    def extra_checks(self, repo: RepoConfig) -> list[list[str]]:
        """The changelog's form, for a repo that keeps one. Run by the interpreter
        running the pipeline: the built repo need not have the framework installed."""
        if not repo.changelog:
            return []
        return [[sys.executable, "-m", "agent_build_kit", "changelog", "check", repo.changelog]]

    def tier2_commands(self, repo: Path, *, marker: str) -> list[list[str]]:
        """The live-stack tests, every member with tests, one at a time: a
        unit that needs the live stack is asserting how the stack behaves, and
        any member's live tests say so."""
        members = self.members(repo)
        if not members:
            return [["uv", "run", "pytest", "-m", marker, *SUMMARY_FLAGS, *DURATION_FLAGS]]
        return [
            [
                "uv",
                "run",
                "--directory",
                member,
                "--package",
                package_name(repo / member),
                "--isolated",
                "pytest",
                "-m",
                marker,
                *SUMMARY_FLAGS,
                *DURATION_FLAGS,
            ]
            for member in members
            if (repo / member / "tests").is_dir()
        ]

    def acceptance_commands(
        self,
        checkout: Path,
        paths: list[str],
        *,
        marker: str,
        exclude_marker: str,
        root_extras: list[str],
    ) -> list[list[str]]:
        """The live-stack tests among `paths` (under tests/integration/),
        grouped per member, each in its own environment; tests only the dev
        stack can run (`exclude_marker`) are left out."""
        by_member: dict[str | None, list[str]] = {}
        for path in paths:
            if "tests/integration/" not in path or not path.endswith(".py"):
                continue
            if not (checkout / path).exists():
                continue
            by_member.setdefault(self.member_of(checkout, path), []).append(path)

        selection = f"{marker} and not {exclude_marker}" if exclude_marker else marker
        commands = []
        for member, files in sorted(by_member.items(), key=lambda item: item[0] or ""):
            if member is None:
                withs = [arg for extra in ["pytest", *root_extras] for arg in ("--with", extra)]
                head = ["uv", "run", "--no-project", "--isolated", *withs]
            else:
                head = ["uv", "run", "--package", package_name(checkout / member), "--isolated"]
            commands.append([*head, "pytest", "-m", selection, *sorted(files)])
        return commands


PROFILE = PythonUvProfile()
