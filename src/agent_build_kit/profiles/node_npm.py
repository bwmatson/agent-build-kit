"""The profile for a JavaScript/TypeScript repo managed by npm — declared, not
yet implemented.

`abk init` detects such repos and writes their specs (research and proposal
are language-agnostic); `abk tick` refuses to build a unit in one until this
profile exists, with a log line saying so. What it will need, by method of
`profiles.base.ToolchainProfile`: `npm test --workspace <member>` with a
summary parser for the chosen runner, `npx oxlint` and `npx tsc --noEmit` as
the lint and clean commands, `.test.ts`/`.spec.ts` and `__tests__/` as test
paths, and `throw new Error("not implemented")` as the permitted stub body.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import RepoConfig
from agent_build_kit.profiles.base import ProfileUnsupported, PromptWords


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

    def lint_command(self, base: str) -> list[str]:
        return self._todo("lint_command")

    def lint_command_all_files(self) -> list[str]:
        return self._todo("lint_command_all_files")

    def test_commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        return self._todo("test_commands")

    def test_commands_all(self, repo: Path, *, root_extras: list[str]) -> list[list[str]]:
        return self._todo("test_commands_all")

    def tolerates_exit(self, command: list[str], returncode: int) -> bool:
        return returncode == 0

    def failure_kind(self, output: str) -> str:
        return self._todo("failure_kind")

    def extra_checks(self, repo: RepoConfig) -> list[list[str]]:
        return []

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
        return self._todo("parse_test_summary")

    def is_test_path(self, path: str) -> bool:
        parts = path.split("/")
        return "__tests__" in parts[:-1] or parts[-1].endswith((".test.ts", ".spec.ts", ".test.js"))

    def stub_violations(self, path: str, content: str) -> list[str]:
        return []

    def members(self, repo: Path) -> list[str]:
        return self._todo("members")

    def member_of(self, repo: Path, path: str) -> str | None:
        return self._todo("member_of")

    def dependents(self, repo: Path, member: str) -> list[str]:
        return self._todo("dependents")


PROFILE = NodeNpmProfile()
