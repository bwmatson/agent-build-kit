"""Two fake toolchain profiles for a repo whose projects are written in different languages.

Each is the python-uv profile with its own commands, project check, failure kind and tools, so
the tests of per-project unit-test need no other ecosystem's tooling. They live here and not in
a test file, and name no method `test_*`, because the pipeline takes any such name for a test.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_build_kit.config import ProjectConfig, RepoConfig
from agent_build_kit.profiles.python_uv import PythonUvProfile


def _tests(word: str) -> Callable[..., list[list[str]]]:
    """A profile's test-command method that runs `word`. Not written as a method, which
    the pipeline would take for a test of this file."""

    def commands(
        self: PythonUvProfile,
        repo: Path,
        changed: list[str],
        *,
        root_extras: list[str],
        **_workers: object,
    ) -> list[list[str]]:
        return [[word]]

    return commands


class Web(PythonUvProfile):
    """Its failures are `types`."""

    name = "fake-web"
    allowed_tools = "Bash(webtool *)"

    def lint_command(self, base: str) -> list[str]:
        return ["web-lint"]

    test_commands = _tests("web-tests")

    def project_checks(self, repo: RepoConfig) -> list[list[str]]:
        return [["web-types"]]

    def failure_kind(self, output: str) -> str:
        return "types"


class Api(PythonUvProfile):
    """Its failures are `test`."""

    name = "fake-api"
    allowed_tools = "Bash(apitool *)"

    def lint_command(self, base: str) -> list[str]:
        return ["api-lint"]

    test_commands = _tests("api-tests")

    def project_checks(self, repo: RepoConfig) -> list[list[str]]:
        return [["api-extra"]]

    def failure_kind(self, output: str) -> str:
        return "test"


class Root(PythonUvProfile):
    """A repo's own profile, with a check that looks at the whole checkout."""

    name = "fake-root"
    allowed_tools = "Bash(roottool *)"

    def extra_checks(self, repo: RepoConfig) -> list[list[str]]:
        return [["root-extra"]]

    def failure_kind(self, output: str) -> str:
        return "types"


WEB = ProjectConfig(path="web", profile=Web.name)
API = ProjectConfig(path="api", profile=Api.name)
