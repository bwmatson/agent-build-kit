"""The profile for a JavaScript/TypeScript repo managed by npm — lint, type check and
tests of a single package are implemented; the rest is declared.

`abk init` detects such repos and writes their specs (research and proposal
are language-agnostic); `abk tick` holds a unit that reaches a method that still
raises, with a log line saying so. Implemented, by method of
`profiles.base.ToolchainProfile`: `npx oxlint` and `npx oxfmt --check` as the lint,
`npx tsc --noEmit` as the project check, `npx vitest run` with a JUnit report for the
tests, the clean and red commands, and `.test`/`.spec` files and `__tests__/` as test paths.
Still to come: judging a red run, the tier 2 and acceptance commands, workspace members, and
`throw new Error("not implemented")` as the permitted stub body.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from xml.etree import ElementTree

from agent_build_kit.config import EnvironmentConfig, RepoConfig
from agent_build_kit.pipeline.red_check import parse_report, split_report, wrap_report_command
from agent_build_kit.pipeline.tier2 import TestFailure, TestTime, clip_failure_line
from agent_build_kit.profiles import node_environment
from agent_build_kit.profiles.base import ProfileUnsupported, PromptWords

_SOURCE = ("ts", "tsx", "js", "jsx", "mts")
# The names of the source files that differ from the base ref `$1`, relative to the project.
_DIFF = 'git diff --relative --diff-filter=d --name-only{z} "$1...HEAD" -- ' + " ".join(
    f"'*.{ext}'" for ext in _SOURCE
)
_DIFF_LINT = (
    # A base that does not resolve is a failure, not an empty diff.
    'git rev-parse --verify --quiet "$1^{commit}" >/dev/null || '
    '{ echo "lint: base $1 does not resolve" >&2; exit 2; }; '
    f'[ "$({_DIFF.format(z="")} | wc -l)" -gt 0 ] || exit 0; '
    f"{_DIFF.format(z=' -z')} | xargs -0 npx oxlint && "
    f"{_DIFF.format(z=' -z')} | xargs -0 npx oxfmt --check"
)
_TYPE_CHECK = "tsc"
_TEST_RUNNER = "vitest"
# No test files is a pass; the report is printed after the marker.
_TESTS = wrap_report_command(
    f"npx {_TEST_RUNNER} run --passWithNoTests --reporter=junit", "--outputFile"
)
_TEST_COMMAND = ["sh", "-c", _TESTS]
_LINT_ALL = "npx oxlint . && npx oxfmt --check ."
_TEST_FILE = re.compile(rf"\.(test|spec)\.({'|'.join(_SOURCE)})$")


def _report(output: str) -> ElementTree.Element | None:
    """The JUnit report a test command printed, or None when it printed none."""
    report, _ = split_report(output)
    if report is None:
        return None
    try:
        return parse_report(report)
    except ValueError:
        return None


class NodeNpmProfile:
    name: str = "node-npm"
    detect_markers: tuple[str, ...] = ("package-lock.json", "package.json")
    allowed_tools: str = "Bash(npm *) Bash(npx *)"
    prompt_words: PromptWords = PromptWords(
        verify="linting and type checks (oxlint, tsc --noEmit)",
        stub='a signature whose body is only `throw new Error("not implemented")`',
    )
    no_tests_collected_exit: int = 0

    def _todo(self, what: str):
        raise ProfileUnsupported(
            f"the {self.name} toolchain profile is not implemented in this release ({what})"
        )

    def created_files(self, repo: Path) -> list[str]:
        return []

    def scaffold_manifest(self, name: str) -> tuple[str, str]:
        return "package.json", json.dumps({"name": name, "version": "0.1.0"}, indent=2) + "\n"

    def lint_command(self, base: str) -> list[str]:
        """Lint and check the format of the source files that differ from `base`, in the
        project the command runs in (paths are relative to it); nothing when none do."""
        return ["sh", "-c", _DIFF_LINT, "sh", base]

    def lint_command_all_files(self) -> list[str]:
        return ["sh", "-c", _LINT_ALL]

    def test_commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        """The project's Vitest run, whatever changed: it reads its own configuration."""
        return [list(_TEST_COMMAND)]

    def test_commands_all(self, repo: Path, *, root_extras: list[str]) -> list[list[str]]:
        return [list(_TEST_COMMAND)]

    def tolerates_exit(self, command: list[str], returncode: int) -> bool:
        return returncode == 0

    def failure_kind(self, output: str) -> str:
        """`types` when the failed command, named in the `$` header, is the type checker,
        `test` when it is the test runner; the linter and the format check are `lint`."""
        header = output.lstrip().split("\n", 1)[0]
        if not header.startswith("$ "):
            return "lint"
        command, _, _ = header.removeprefix("$ ").rpartition(" (exit ")
        try:
            words = shlex.split(command or header.removeprefix("$ "))
        except ValueError:
            return "lint"
        if words[:2] == ["npx", _TYPE_CHECK]:
            return "types"
        return "test" if words == _TEST_COMMAND else "lint"

    def extra_checks(self, repo: RepoConfig) -> list[list[str]]:
        return []

    def project_checks(self, repo: RepoConfig) -> list[list[str]]:
        """The type check, over the whole project: `tsc` cannot be scoped to files."""
        return [["npx", _TYPE_CHECK, "--noEmit"]]

    def tier2_commands(self, repo: Path, *, marker: str) -> list[list[str]]:
        return self._todo("tier2_commands")

    def acceptance_commands(
        self,
        checkout: Path,
        paths: list[str],
        *,
        marker: str,
        exclude_marker: str,
        root_extras: list[str],
    ) -> list[list[str]]:
        return self._todo("acceptance_commands")

    def clean_command(self) -> str:
        """Lint and the format check over the project; no type check, since a test importing
        what does not exist yet is the expected state at the tests commit."""
        return _LINT_ALL

    def red_command(self, files: list[str]) -> str:
        """Vitest with `files` as its filters, its JUnit report printed after the marker so it
        outlives the worktree; the exit status is Vitest's own. Vitest takes each file as a
        filter that matches by substring (an absolute path is turned back into the relative
        one), so `src/index.test.ts` also selects `packages/ui/src/index.test.ts` and no
        argument selects one file exactly: the report names each test suite by its file, which
        is how a reader keeps only the files it was given."""
        run = f"npx {_TEST_RUNNER} run {shlex.join(files)} --reporter=junit"
        return wrap_report_command(run, "--outputFile")

    def interpret_red(self, output: str, exit_code: int) -> tuple[bool, list[str]]:
        return self._todo("interpret_red")

    def parse_test_summary(self, output: str) -> tuple[int, int, int, float]:
        """(passed, failed, skipped, seconds) from the JUnit report after the marker."""
        root = _report(output)
        if root is None:
            return 0, 0, 0, 0.0
        passed = failed = skipped = 0
        for case in root.iter("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                failed += 1
            elif case.find("skipped") is not None:
                skipped += 1
            else:
                passed += 1
        return passed, failed, skipped, float(root.get("time") or 0)

    def parse_test_failures(self, output: str) -> list[TestFailure]:
        """One entry per failing test of the report, named `file > test`, with the first
        line of its message."""
        root = _report(output)
        if root is None:
            return []
        failures = []
        for case in root.iter("testcase"):
            bad = case.find("failure")
            if bad is None:
                bad = case.find("error")
            if bad is None:
                continue
            name = " > ".join(p for p in (case.get("classname"), case.get("name")) if p)
            first = (bad.get("message") or "").strip().split("\n", 1)[0]
            failures.append(TestFailure(test=name, line=clip_failure_line(first)))
        return failures

    def parse_test_durations(self, output: str) -> list[TestTime]:
        return []

    def without_durations(self, output: str) -> str:
        return output

    def is_test_path(self, path: str) -> bool:
        parts = path.split("/")
        return "__tests__" in parts[:-1] or bool(_TEST_FILE.search(parts[-1]))

    def detect_environment(self, root: Path, *, framework: bool) -> EnvironmentConfig | None:
        return node_environment.detect_environment(root)

    def stub_violations(self, path: str, content: str) -> list[str]:
        return []

    def members(self, repo: Path) -> list[str]:
        return self._todo("members")

    def member_of(self, repo: Path, path: str) -> str | None:
        return self._todo("member_of")

    def dependents(self, repo: Path, member: str) -> list[str]:
        return self._todo("dependents")


PROFILE = NodeNpmProfile()
