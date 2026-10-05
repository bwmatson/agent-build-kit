"""The profile for a Python repo managed by uv, tested with pytest and gated
by pre-commit (ruff, a type checker).

A uv workspace is tested one member at a time in its own environment, the way
such a repo's CI runs: every member tends to own a top-level `src` package, so
one shared environment holding all of them makes one member's tests import
another's. `--package <member> --isolated` reproduces the one-member
environment, so the collision cannot happen.
"""

from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path

from agent_build_kit.pipeline.commit_order import stub_violations as _stub_violations
from agent_build_kit.pipeline.red_check import interpret_pytest
from agent_build_kit.pipeline.tier2 import parse_pytest_summary
from agent_build_kit.profiles.base import PromptWords

# pytest's exit status when every test was deselected: "nothing to run here",
# not a failure — most members carry no tier-2 tests.
NO_TESTS_COLLECTED = 5

_TEST_FILE = re.compile(r"^(test_.*|.*_test|conftest)\.py$")
_DEP_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
XDIST = "pytest-xdist"
WORKERS = ["-n", "auto", "--maxprocesses=8"]


# The pre-commit hooks that are the type checker, by id.
TYPE_HOOKS = frozenset({"pyrefly-check", "pyrefly", "mypy", "pyright"})
_PYTEST = re.compile(r"\bpytest\b")
# pre-commit prints `<hook id>....(no files to check)Skipped` or `...Passed` or `...Failed`
# for every hook; the id may itself hold dots and dashes.
_HOOK_FAILED = re.compile(r"^(?P<hook>\S.*?)\.{3,}Failed\s*$", re.MULTILINE)


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pyproject(path: Path) -> dict:
    try:
        return tomllib.loads((path / "pyproject.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


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


def _is_serial_pass(command: list[str]) -> bool:
    if "-m" not in command[:-1]:
        return False
    expression = command[command.index("-m") + 1]
    return expression == "serial" or expression.endswith(" and serial")


def package_name(member: Path) -> str:
    """What a workspace member calls itself, falling back to its directory.

    A member with no parseable name should not take tier 1 down with it — the
    directory name is right often enough to be worth trying.
    """
    return str(_pyproject(member).get("project", {}).get("name") or member.name)


class PythonUvProfile:
    name: str = "python-uv"
    detect_markers: tuple[str, ...] = ("uv.lock", "pyproject.toml")
    allowed_tools: str = "Bash(uv run *) Bash(pre-commit *)"
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
        return f"uv run pytest {' '.join(files)} -p no:cacheprovider --tb=line -q"

    def interpret_red(self, output: str, exit_code: int) -> tuple[bool, list[str]]:
        return interpret_pytest(output, exit_code=exit_code)

    def parse_test_summary(self, output: str) -> tuple[int, int, int, float]:
        return parse_pytest_summary(output)

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
        listed too, so only the failed lines count), and `lint` otherwise."""
        header = output.lstrip().split("\n", 1)[0]
        if header.startswith("$ ") and "pre-commit" not in header and _PYTEST.search(header):
            return "test"
        failed = {m.group("hook").strip() for m in _HOOK_FAILED.finditer(output)}
        return "types" if failed & TYPE_HOOKS else "lint"

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

    def tier2_commands(self, repo: Path, *, marker: str) -> list[list[str]]:
        """The live-stack tests, every member with tests, one at a time: a
        unit that needs the live stack is asserting how the stack behaves, and
        any member's live tests say so."""
        members = self.members(repo)
        if not members:
            return [["uv", "run", "pytest", "-m", marker, "-v"]]
        return [
            [
                "uv",
                "run",
                "--package",
                package_name(repo / member),
                "--isolated",
                "pytest",
                member,
                "-m",
                marker,
                "-v",
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
