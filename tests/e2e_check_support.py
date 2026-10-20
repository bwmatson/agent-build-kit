"""The pieces `abk e2e-test check` is tested through: two declared splits, a stand-in for the
process that lists a split's tests, and an installation of two repos."""

from __future__ import annotations

import subprocess
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

from agent_build_kit.installation import Installation
from tests.conftest import make_installation

__all__ = [
    "ACP",
    "BASE",
    "CLAUDE",
    "CLEAN",
    "MARKERS",
    "PLAIN",
    "SPLITS",
    "Pytest",
    "installation",
    "markers_output",
    "marker_matches",
]

SPLITS = {"acp": {"marker": "runtime_acp"}, "claude_code": {"marker": "runtime_claude_code"}}
ACP = "tests/integration/test_live.py::test_acp"
CLAUDE = "tests/integration/test_live.py::test_claude"
PLAIN = "tests/integration/test_live.py::test_plain"
BASE = "local_stack"
MARKERS = (
    "@pytest.mark.local_stack: live stack\n\n"
    "@pytest.mark.runtime_acp: acp\n\n"
    "@pytest.mark.runtime_claude_code: claude code\n"
)


class _Carries(dict[str, bool]):
    """The names a marker expression is read with: true for a marker the test carries."""

    def __init__(self, carried: Collection[str]) -> None:
        super().__init__()
        self.carried = set(carried)

    def __missing__(self, name: str) -> bool:
        return name in self.carried


def marker_matches(expression: str, carried: Collection[str]) -> bool:
    """Whether a test carrying the markers `carried` is selected by the `-m` expression."""
    return bool(eval(expression, {"__builtins__": {}}, _Carries(carried)))  # noqa: S307


def markers_output(names: Collection[str]) -> str:
    """What `pytest --markers` prints for the registered markers `names`."""
    return "".join(f"@pytest.mark.{name}: {name}\n\n" for name in names)


class Pytest:
    """Stands in for the process run: answers `--markers` and each `--collect-only` by the
    `-m` expression it was given: from a listing per expression, or from `carries`, the
    markers each test carries."""

    def __init__(
        self,
        listings: dict[str, list[str]] | None = None,
        *,
        markers: str = MARKERS,
        failing: str | None = None,
        carries: Mapping[str, Collection[str]] | None = None,
    ) -> None:
        self.listings = listings or {}
        self.carries = carries
        self.markers = markers
        self.failing = failing
        self.commands: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.commands.append(argv)
        self.kwargs.append(kwargs)
        captured = kwargs.get("capture_output") is True and kwargs.get("text") is True
        assert "--collect-only" in argv or "--markers" in argv, f"ran a test: {argv}"
        if "--markers" in argv:
            return self._result(argv, 0, self.markers, captured)
        expression = argv[argv.index("-m") + 1]
        if expression == self.failing:
            return self._result(argv, 4, "ERROR: usage\n", captured)
        if self.carries is not None:
            tests = [
                t for t, carried in self.carries.items() if marker_matches(expression, carried)
            ]
        else:
            tests = self.listings.get(expression, [])
        return self._result(argv, 0 if tests else 5, "\n".join(tests) + "\n", captured)

    @staticmethod
    def _result(
        argv: list[str], code: int, out: str, captured: bool
    ) -> subprocess.CompletedProcess:
        """Like `subprocess.run`: no output unless asked for as text."""
        return subprocess.CompletedProcess(
            argv, code, out if captured else None, "" if captured else None
        )


def installation(
    tmp_path: Path,
    splits: dict[str, Any] | None = SPLITS,
    profile: str = "python-uv",
    projects: list[dict[str, str]] | None = None,
    dimensions: dict[str, Any] | None = None,
) -> Installation:
    root = tmp_path / "planning"
    tests: dict[str, Any] = {} if splits is None else {"e2e_splits": splits}
    if dimensions is not None:
        tests["e2e_dimensions"] = dimensions
    found = make_installation(
        root,
        tests=tests,
        verify={"env": {"SVC_TOKEN": {"from": "literal", "value": "secret"}}},
        repos={
            "app": {
                "path": str(tmp_path / "app"),
                "slug": "example/app",
                "profile": profile,
                "projects": projects or [],
            },
            "platform": {"path": str(tmp_path / "platform"), "slug": "example/platform"},
        },
    )
    for name in ("app", "platform"):
        (tmp_path / name / "tests" / "integration").mkdir(parents=True)
        (tmp_path / name / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n')
        (tmp_path / name / "tests" / "integration" / "test_live.py").write_text("")
    for project in projects or []:
        (tmp_path / "app" / project["path"]).mkdir(parents=True, exist_ok=True)
        (tmp_path / "app" / project["path"] / "pyproject.toml").write_text("[project]\n")
    return found


CLEAN = {
    f"{BASE} and runtime_acp": [ACP],
    f"{BASE} and runtime_claude_code": [CLAUDE],
    f"{BASE} and not runtime_acp and not runtime_claude_code": [PLAIN],
}
