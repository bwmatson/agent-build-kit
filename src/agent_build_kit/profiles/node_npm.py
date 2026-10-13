"""The profile for a JavaScript/TypeScript repo managed by npm — lint, type check and
tests of a single package are implemented; the rest is declared.

`abk init` detects such repos and writes their specs (research and proposal
are language-agnostic); `abk tick` refuses to build a unit in one until this
profile exists, with a log line saying so. What it will need, by method of
`profiles.base.ToolchainProfile`: `npm test --workspace <member>` with a
summary parser for the chosen runner, `npx oxlint` and `npx tsc --noEmit` as
the lint and clean commands, `.test.ts`/`.spec.ts` and `__tests__/` as test
paths, and `throw new Error("not implemented")` as the permitted stub body.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from xml.etree import ElementTree

from agent_build_kit.config import EnvironmentConfig, RepoConfig
from agent_build_kit.pipeline.red_check import REPORT_MARK, split_report
from agent_build_kit.pipeline.tier2 import TestFailure, TestTime
from agent_build_kit.profiles import node_environment
from agent_build_kit.profiles.base import ProfileUnsupported, PromptWords
from agent_build_kit.profiles.python_uv import FAILURE_LINE_LIMIT

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
# The report goes to a fresh temporary file and is printed after the marker, so it outlives
# the worktree; the exit status is the runner's own. No test files is a pass.
_TESTS = (
    f"report=$(mktemp); npx {_TEST_RUNNER} run --passWithNoTests --reporter=junit "
    '--outputFile="$report"; status=$?; '
    f'echo \'{REPORT_MARK}\'; cat "$report" 2>/dev/null; rm -f "$report"; exit $status'
)
_TEST_FILE = re.compile(rf"\.(test|spec)\.({'|'.join(_SOURCE)})$")


def _report(output: str) -> ElementTree.Element | None:
    """The JUnit report a test command printed, or None when it printed none."""
    report, _ = split_report(output)
    if report is None:
        return None
    body = report.strip()
    if body.startswith("<!--"):
        body = body.partition("-->")[2].strip()
    try:
        return ElementTree.fromstring(body)
    except ElementTree.ParseError:
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
        return ["sh", "-c", "npx oxlint . && npx oxfmt --check ."]

    def test_commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        """The project's Vitest run, whatever changed: it reads its own configuration."""
        return [["sh", "-c", _TESTS]]

    def test_commands_all(self, repo: Path, *, root_extras: list[str]) -> list[list[str]]:
        return [["sh", "-c", _TESTS]]

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
        return "test" if any(_TEST_RUNNER in word for word in words) else "lint"

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
        return self._todo("clean_command")

    def red_command(self, files: list[str]) -> str:
        return self._todo("red_command")

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
            if len(first) > FAILURE_LINE_LIMIT:
                first = first[: FAILURE_LINE_LIMIT - 1] + "…"
            failures.append(TestFailure(test=name, line=first))
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
