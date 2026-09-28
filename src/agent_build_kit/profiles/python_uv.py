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


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pyproject(path: Path) -> dict:
    try:
        return tomllib.loads((path / "pyproject.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


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

    def _root_tests(self, root_extras: list[str]) -> list[str]:
        # The repo-root tests/, which belongs to no member, in the same
        # environment its CI job uses: pytest plus whatever it declares.
        withs = [arg for extra in ["pytest", *root_extras] for arg in ("--with", extra)]
        return ["uv", "run", "--no-project", "--isolated", *withs, "pytest", "tests", "-q"]

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
            return [["uv", "run", "pytest", "-q"]] if (repo / "tests").is_dir() else []

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
        root = []
        if (repo / "tests").is_dir() and (outside or any(p.startswith("tests/") for p in changed)):
            root = [self._root_tests(root_extras)]
        # `--package` names the package; the trailing path names the directory.
        # They differ more often than not.
        return [
            [
                "uv",
                "run",
                "--package",
                package_name(repo / member),
                "--isolated",
                "pytest",
                member,
                "-q",
            ]
            for member in chosen
        ] + root

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
