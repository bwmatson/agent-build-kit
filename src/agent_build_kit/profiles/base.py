"""What the pipeline needs to know about a repo's toolchain.

The pipeline lints, runs tests, reads their results, tells test files from
implementation and checks that a stub is only a stub. Every one of those is
language-specific, so each lives in a profile and the rest of the pipeline
asks the profile. A repo names its profile in abk.yaml (`profile:`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from agent_build_kit.model import Frozen


class PromptWords(Frozen):
    """The toolchain-specific phrases the build prompts use."""

    # What "the checks pass" means before an agent may stop.
    verify: str = "linting, formatting and type checks"
    # What a permitted stub looks like in a tests-first commit.
    stub: str = "a signature whose body is only a raise-not-implemented, or a data field"


class ToolchainProfile(Protocol):
    name: str
    # Files whose presence in a repo root suggests this profile (init's detection).
    detect_markers: tuple[str, ...]
    # Tool patterns to allow in addition to the base list, in Claude Code's
    # `--allowedTools` syntax; no effect under the acp runtime.
    allowed_tools: str
    prompt_words: PromptWords
    # The test runner's exit status when nothing was selected.
    no_tests_collected_exit: int

    def lint_command(self, base: str) -> list[str]: ...

    def lint_command_all_files(self) -> list[str]: ...

    def test_commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]: ...

    def test_commands_all(self, repo: Path, *, root_extras: list[str]) -> list[list[str]]: ...

    def tier2_commands(self, repo: Path, *, marker: str) -> list[list[str]]: ...

    def acceptance_commands(
        self,
        checkout: Path,
        paths: list[str],
        *,
        marker: str,
        exclude_marker: str,
        root_extras: list[str],
    ) -> list[list[str]]: ...

    def clean_command(self) -> str: ...

    def red_command(self, files: list[str]) -> str: ...

    def interpret_red(self, output: str, exit_code: int) -> tuple[bool, list[str]]: ...

    def parse_test_summary(self, output: str) -> tuple[int, int, int, float]: ...

    def is_test_path(self, path: str) -> bool: ...

    def stub_violations(self, path: str, content: str) -> list[str]: ...

    def members(self, repo: Path) -> list[str]: ...

    def member_of(self, repo: Path, path: str) -> str | None: ...

    def dependents(self, repo: Path, member: str) -> list[str]: ...


# Paths that are documentation. Never deploy anything, whatever the profile.
DOC_SUFFIXES = (".md", ".rst", ".txt")


def is_doc_path(path: str) -> bool:
    first = path.split("/", 1)[0]
    name = path.rsplit("/", 1)[-1]
    return path.endswith(DOC_SUFFIXES) or first == "docs" or name.upper().startswith("LICENSE")
