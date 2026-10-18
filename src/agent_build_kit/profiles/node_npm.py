"""The profile for a JavaScript/TypeScript repo managed by npm.

`abk init` detects such repos and writes their specs (research and proposal
are language-agnostic); `abk tick` holds a unit that reaches a method that raises
`ProfileUnsupported`, which this profile does not. Implemented, by method of
`profiles.base.ToolchainProfile`: `npx oxlint` and `npx oxfmt --check` as the lint,
`npx tsc --noEmit` as the project check, `npx vitest run` with a JUnit report for the
tests, the clean and red commands, judging a red run, and `.test`/`.spec` files and
`__tests__/` as test paths.
The stub check (`throw new Error("not implemented")` as the permitted body) and the files the
commands create are implemented too.
npm workspace members (the `workspaces` field, globs expanded) are tested one command each
in their own directory, and an e2e test is a file named `<name>.<marker>.test.<ext>`.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from xml.etree import ElementTree

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from agent_build_kit.config import (
    AgentCommand,
    AgentPurpose,
    AgentScope,
    EnvironmentConfig,
    RepoConfig,
)
from agent_build_kit.pipeline.e2e import TestFailure, TestTime, clip_failure_line
from agent_build_kit.pipeline.red_check import (
    UNRECOGNISED_FAILURE,
    parse_report,
    passed_problem,
    split_report,
    wrap_report_command,
)
from agent_build_kit.profiles import node_environment
from agent_build_kit.profiles.base import PromptWords, is_doc_path

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
# The project's type check, which `project_checks` and the stubbed clean command both run.
_TYPE_CHECK_ARGV = ["npx", _TYPE_CHECK, "--noEmit"]
_TEST_RUNNER = "vitest"
# No test files is a pass; the report is printed after the marker.
_RUN = f"npx {_TEST_RUNNER} run --passWithNoTests --reporter=junit"
_TESTS = wrap_report_command(_RUN, "--outputFile")
_TEST_COMMAND = ["sh", "-c", _TESTS]
# The same in the directory `$1`, for a workspace member; the report path is absolute, so the
# change of directory does not hide it.
_MEMBER_TESTS = wrap_report_command(f'cd "$1" && {_RUN}', "--outputFile")
# E2e-test and acceptance: in `$1`, the rest are Vitest's filters, which match by substring of
# a file's path.
_FILTERED = wrap_report_command(f'cd "$1" && shift && {_RUN} "$@"', "--outputFile")
_TEST_SCRIPTS = (_TESTS, _MEMBER_TESTS, _FILTERED)
# The directory of a project that is not a workspace, or the root of one.
_HERE = "./"
_LINT_ALL = "npx oxlint . && npx oxfmt --check ."
# The red command lists the files it was given, one per line before the report, so the judge
# can tell their suites from any other the runner's substring filters selected.
_RED_FILE = "abk red file: "
_NOT_IMPLEMENTED = "not implemented"
# What the profile's own commands create in a project: type-check build info and the Vite and
# Vitest caches.
_CREATED = ["**/*.tsbuildinfo", "node_modules/.vite", "node_modules/.vitest", ".vite"]
_FUNCTIONS = frozenset(
    {
        "function_declaration",
        "generator_function_declaration",
        "function_expression",
        "generator_function",
        "function",
        "arrow_function",
        "method_definition",
    }
)
_TEST_FILE = re.compile(rf"\.(test|spec)\.({'|'.join(_SOURCE)})$")


_TYPESCRIPT = Language(tree_sitter_typescript.language_typescript())
_TSX = Language(tree_sitter_typescript.language_tsx())


def _parser(path: str) -> Parser:
    """A parser of the TSX grammar for the extensions that may hold JSX (`.tsx`, `.jsx`, and
    `.js`, which Vite projects sometimes keep JSX in), else of the TypeScript one."""
    return Parser(_TSX if path.endswith(("x", ".js")) else _TYPESCRIPT)


def _text(node: Node | None) -> str:
    return node.text.decode() if node is not None and node.text is not None else ""


def _is_sentinel(node: Node) -> bool:
    """`throw new Error("not implemented")`, in either quote style."""
    if node.type != "throw_statement" or not node.named_children:
        return False
    error = node.named_children[0]
    if error.type != "new_expression":
        return False
    arguments = error.child_by_field_name("arguments")
    values = arguments.named_children if arguments is not None else []
    return (
        _text(error.child_by_field_name("constructor")) == "Error"
        and len(values) == 1
        and values[0].type == "string"
        and _text(values[0])[1:-1] == _NOT_IMPLEMENTED
    )


def _is_stub_body(body: Node) -> bool:
    """A block of only the sentinel throw; nested function declarations and comments are
    judged on their own."""
    statements = [
        child
        for child in body.named_children
        if child.type != "comment" and not child.type.endswith("function_declaration")
    ]
    return len(statements) == 1 and _is_sentinel(statements[0])


def _function_name(node: Node) -> str:
    name = node.child_by_field_name("name")
    if name is None and node.parent is not None and node.parent.type == "variable_declarator":
        name = node.parent.child_by_field_name("name")
    return _text(name) or "anonymous function"


def _report(output: str) -> ElementTree.Element | None:
    """The JUnit report a test command printed, or None when it printed none."""
    report, _ = split_report(output)
    if report is None:
        return None
    try:
        return parse_report(report)
    except ValueError:
        return None


def _failure(case: ElementTree.Element) -> tuple[str, ElementTree.Element | None]:
    """The `file > test` name of a `testcase` and its `failure` (or else `error`) element,
    None when the test did not fail."""
    name = " > ".join(p for p in (case.get("classname"), case.get("name")) if p)
    bad = case.find("failure")
    return name, bad if bad is not None else case.find("error")


class NodeNpmProfile:
    name: str = "node-npm"
    detect_markers: tuple[str, ...] = ("package-lock.json", "package.json")
    supports_stubs = True
    allowed_tools: str = "Bash(npm *) Bash(npx *)"
    agent_commands: tuple[AgentCommand, ...] = (
        AgentCommand(purpose=AgentPurpose.TEST, command=["npx", "vitest", "run"]),
        AgentCommand(
            purpose=AgentPurpose.TEST,
            command=["npx", "vitest", "run", "{path}"],
            scope=AgentScope.FILE,
        ),
        AgentCommand(purpose=AgentPurpose.LINT, command=["npx", "oxlint", "."]),
        AgentCommand(purpose=AgentPurpose.FORMAT, command=["npx", "oxfmt", "--check", "."]),
        AgentCommand(purpose=AgentPurpose.CHECK, command=list(_TYPE_CHECK_ARGV)),
    )
    prompt_words: PromptWords = PromptWords(
        verify="linting and type checks (oxlint, tsc --noEmit)",
        stub='a signature whose body is only `throw new Error("not implemented")`',
    )
    no_tests_collected_exit: int = 0

    def created_files(self, repo: Path) -> list[str]:
        """The type-check build info and the Vite and Vitest caches."""
        return list(_CREATED)

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
        """The project's Vitest run, whatever changed: it reads its own configuration. In a
        workspace, one run in each member a changed path is under, and in every member when
        a path outside them all (the root manifest, a shared configuration) changed;
        documentation changes nothing."""
        members = self.members(repo)
        if not members:
            return [list(_TEST_COMMAND)]
        owners = {path: _deepest(members, path) for path in changed}
        outside = [path for path in changed if owners[path] is None and not is_doc_path(path)]
        touched = set(owners.values())
        commands = [_member_command(m) for m in members if outside or m in touched]
        # A test file outside every member (a workspace-level suite) belongs to the root.
        root_tests = [path for path in outside if self.is_test_path(path)]
        if root_tests:
            commands.append(["sh", "-c", _FILTERED, "sh", _HERE, *root_tests])
        return commands

    def test_commands_all(self, repo: Path, *, root_extras: list[str]) -> list[list[str]]:
        """Every member's tests; the workspace root's own, if it has any, are not run."""
        members = self.members(repo)
        return [_member_command(m) for m in members] if members else [list(_TEST_COMMAND)]

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
        is_tests = words[:2] == ["sh", "-c"] and words[2:3] and words[2] in _TEST_SCRIPTS
        return "test" if is_tests else "lint"

    def extra_checks(self, repo: RepoConfig) -> list[list[str]]:
        return []

    def project_checks(self, repo: RepoConfig) -> list[list[str]]:
        """The type check, over the whole project: `tsc` cannot be scoped to files."""
        return [list(_TYPE_CHECK_ARGV)]

    def e2e_commands(self, repo: Path, *, marker: str) -> list[list[str]]:
        """The files named for `marker`, in each member of a workspace or else the project."""
        return [
            ["sh", "-c", _FILTERED, "sh", member, f".{marker}.test."]
            for member in self.members(repo) or [_HERE]
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
        """The changed files named for `marker` that exist, and not for `exclude_marker`
        (the tests only the dev stack can run), a run per member."""
        members = self.members(checkout)
        by_member: dict[str | None, list[str]] = {}
        for path in paths:
            if _marked(path, marker, exclude_marker) and (checkout / path).exists():
                by_member.setdefault(_deepest(members, path), []).append(path)
        commands = []
        for member, files in sorted(by_member.items(), key=lambda item: item[0] or ""):
            relative = [f.removeprefix(f"{member}/") if member else f for f in sorted(files)]
            commands.append(["sh", "-c", _FILTERED, "sh", member or _HERE, *relative])
        return commands

    def clean_command(self, *, types: bool = False) -> str:
        """Lint and the format check over the project; with `types`, the project's type check
        too. Without it none runs, since in a build that is not stubbed a test importing what
        does not exist yet is the expected state at the tests commit."""
        return f"{_LINT_ALL} && {shlex.join(_TYPE_CHECK_ARGV)}" if types else _LINT_ALL

    def red_command(self, files: list[str]) -> str:
        """Vitest with `files` as its filters, its JUnit report printed after the marker so it
        outlives the worktree; the exit status is Vitest's own. Vitest takes each file as a
        filter that matches by substring (an absolute path is turned back into the relative
        one), so `src/index.test.ts` also selects `packages/ui/src/index.test.ts` and no
        argument selects one file exactly: the report names each test suite by its file, which
        is how a reader keeps only the files it was given."""
        run = f"npx {_TEST_RUNNER} run {shlex.join(files)} --reporter=junit"
        listed = "printf '%s\\n' " + shlex.join(_RED_FILE + file for file in files) + "; "
        return listed + wrap_report_command(run, "--outputFile")

    def interpret_red(
        self, output: str, exit_code: int, *, stubbed: bool = False
    ) -> tuple[bool, list[str]]:
        """Red for the right reason, judged on the suites of the files the red command was
        given (it lists them before the report): every test that ran failed by an assertion
        or by an error saying `not implemented`. A file that failed to load (an unresolved
        import, a syntax error), a passing test and a run with no suite of those files are
        rejected, each with its reason. This is also the stubbed reading (`stubbed`): a file
        that failed to load is rejected either way."""
        _, console = split_report(output)
        given = {
            line.removeprefix(_RED_FILE).removeprefix("./")
            for line in console.splitlines()
            if line.startswith(_RED_FILE)
        }
        root = _report(output)
        if root is None:
            return False, ["no test report was written, so the run cannot be judged"]
        suites = [s for s in root.iter("testsuite") if (s.get("name") or "") in given]
        problems: list[str] = []
        passed = 0
        failed_in: set[str] = set()
        for suite in suites:
            for case in suite.iter("testcase"):
                name, bad = _failure(case)
                if bad is None:
                    passed += case.find("skipped") is None
                    continue
                failed_in.add(suite.get("name") or "")
                message = (bad.get("message") or "").strip()
                if case.get("name") == case.get("classname"):
                    first = message.split("\n", 1)[0]
                    problems.append(
                        f"{name}: the test file could not be loaded, so no test failed for "
                        f"the missing behaviour ({first})"
                    )
                elif bad.get("type") != "AssertionError" and message != _NOT_IMPLEMENTED:
                    problems.append(f"{name}: {UNRECOGNISED_FAILURE}")
        if passed:
            problems.append(passed_problem(passed))
        problems += [
            f"{file}: nothing failed at the tests commit" for file in sorted(given - failed_in)
        ]
        return not problems, problems

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
            name, bad = _failure(case)
            if bad is None:
                continue
            first = (bad.get("message") or "").strip().split("\n", 1)[0]
            failures.append(TestFailure(test=name, line=clip_failure_line(first)))
        return failures

    def parse_test_durations(self, output: str) -> list[TestTime]:
        """One `call` entry per test of the report, with the time Vitest gave it."""
        root = _report(output)
        if root is None:
            return []
        return [
            TestTime(
                test=" > ".join(p for p in (c.get("classname"), c.get("name")) if p),
                phase="call",
                seconds=float(c.get("time") or 0),
            )
            for c in root.iter("testcase")
        ]

    def without_durations(self, output: str) -> str:
        return output

    def is_test_path(self, path: str) -> bool:
        parts = path.split("/")
        return "__tests__" in parts[:-1] or bool(_TEST_FILE.search(parts[-1]))

    def detect_environment(self, root: Path, *, framework: bool) -> EnvironmentConfig | None:
        return node_environment.detect_environment(root)

    def stub_violations(self, path: str, content: str) -> list[str]:
        """A violation for every function whose body is more than the sentinel throw, at any
        depth, and for a file that does not parse; none for a test file or a non-source file.
        A function without a body (a declaration, an overload) is accepted."""
        if self.is_test_path(path) or not path.endswith(tuple(f".{ext}" for ext in _SOURCE)):
            return []
        root = _parser(path).parse(content.encode()).root_node
        if root.has_error:
            return [f"{path}: the file could not be parsed"]
        problems: list[str] = []
        pending = [root]
        while pending:
            node = pending.pop()
            pending.extend(reversed(node.children))
            if node.type not in _FUNCTIONS:
                continue
            body = node.child_by_field_name("body")
            if body is None or (body.type == "statement_block" and _is_stub_body(body)):
                continue
            problems.append(
                f"{path}: {_function_name(node)}() has a body — a stub's body is only "
                f'`throw new Error("{_NOT_IMPLEMENTED}")`'
            )
        return problems

    def members(self, repo: Path) -> list[str]:
        """The directories the root manifest's `workspaces` patterns name that hold a
        manifest, sorted; none for a manifest without the field. A negated pattern is not
        supported."""
        found: set[str] = set()
        for pattern in node_environment.workspace_patterns(node_environment.read_manifest(repo)):
            if pattern.startswith("!"):
                continue
            for directory in repo.glob(pattern):
                relative = directory.relative_to(repo)
                if (
                    "node_modules" not in relative.parts
                    and (directory / node_environment.MANIFEST).is_file()
                ):
                    found.add(relative.as_posix())
        return sorted(found)

    def member_of(self, repo: Path, path: str) -> str | None:
        return _deepest(self.members(repo), path)

    def dependents(self, repo: Path, member: str) -> list[str]:
        """The members that name `member`'s package among their dependencies, development
        dependencies or peer dependencies."""
        name = node_environment.read_manifest(repo / member).get("name")
        found = []
        for other in self.members(repo):
            manifest = node_environment.read_manifest(repo / other)
            declared = {
                dependency
                for kind in ("dependencies", "devDependencies", "peerDependencies")
                if isinstance(manifest.get(kind), dict)
                for dependency in manifest[kind]
            }
            if other != member and name in declared:
                found.append(other)
        return found


def _deepest(members: list[str], path: str) -> str | None:
    """The longest of `members` that holds `path`."""
    inside = [m for m in members if path == m or path.startswith(f"{m}/")]
    return max(inside, key=len, default=None)


def _member_command(member: str) -> list[str]:
    return ["sh", "-c", _MEMBER_TESTS, "sh", member]


def _marked(path: str, marker: str, exclude_marker: str) -> bool:
    """Whether `path` is named `<name>.<marker>.test.<ext>`, and not also for
    `exclude_marker` in an earlier segment (the tests only the dev stack can run)."""
    parts = path.rsplit("/", 1)[-1].split(".")
    return (
        len(parts) > 3
        and parts[-2] == "test"
        and parts[-3] == marker
        and (not exclude_marker or exclude_marker not in parts[1:-3])
    )


PROFILE = NodeNpmProfile()
