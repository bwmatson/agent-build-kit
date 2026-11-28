"""Suppressions a unit adds: each marker needs a reason on its line, and moved lines are not new."""

from pathlib import Path

import pytest

from agent_build_kit.quality.added_lines import AddedFile, read_added_lines
from agent_build_kit.quality.suppressions import find_suppressions
from tests.support.git_checkout import commit_files, fork_unit_branch, repo_with_main, write_files

# (file name, the added line, whether a finding is expected)
MARKER_ROWS = [
    ("a.py", "x = 1  # noqa", True),
    ("a.py", "x = 1  # noqa: F811 — the fixture is requested by name", False),
    ("a.py", "x = 1  # noqa: E501", True),
    ("a.py", "x = 1  # noqa: E501 the url cannot be split", False),
    ("a.py", "# ruff: noqa", True),
    ("a.py", "# ruff: noqa: F401 names re-exported for callers", False),
    ("a.py", "x = f(y)  # type: ignore[arg-type]", True),
    ("a.py", "x = f(y)  # type: ignore[arg-type] the stub is wrong", False),
    ("a.py", "x = f(y)  # pyrefly: ignore", True),
    ("a.py", "x = f(y)  # pyrefly: ignore the stub lacks it", False),
    ("a.py", "x = f(y)  # pyright: ignore", True),
    ("a.py", "x = f(y)  # pyright: ignore the stub lacks it", False),
    ("a.py", "x = f(y)  # pylint: disable=x", True),
    ("a.py", "x = f(y)  # pylint: disable=x because the name is fixed", False),
    ("a.py", "x = f(y)  # nosec", True),
    ("a.py", "x = f(y)  # nosec the input is a constant", False),
    ("a.py", "x = f(y)  # pragma: no cover", True),
    ("a.py", "x = f(y)  # pragma: no cover — never reached by tests", False),
    ("a.ts", "// eslint-disable-next-line no-console", True),
    ("a.ts", "// eslint-disable-next-line no-console -- logs the banner", False),
    ("a.ts", "// oxlint-disable-line", True),
    ("a.ts", "// oxlint-disable-line -- needed for the shim", False),
    ("a.ts", "// biome-ignore lint/x", True),
    ("a.ts", "// biome-ignore lint/x: the shim needs it", False),
    ("a.ts", "// @ts-ignore", True),
    ("a.ts", "// @ts-ignore the typings are wrong", False),
    ("a.ts", "// @ts-expect-error", True),
    ("a.ts", "// @ts-expect-error the library lacks types", False),
    ("a.ts", "/* istanbul ignore next */", True),
    ("a.ts", "/* istanbul ignore next -- guarded by the caller */", False),
    ("a.ts", 'const text = "@ts-ignore";', False),
    ("a.py", "x = 1", False),
]


@pytest.mark.parametrize(("name", "line", "flagged"), MARKER_ROWS)
def test_an_added_marker_is_a_finding_exactly_when_its_line_has_no_reason(
    tmp_path: Path, name: str, line: str, flagged: bool
) -> None:
    write_files(tmp_path, {name: f"{line}\n"})
    added = {name: AddedFile(path=name, added=frozenset({1}), is_new=True)}

    found = find_suppressions(tmp_path, added)

    assert [(finding.path, finding.line) for finding in found] == ([(name, 1)] if flagged else [])
    assert all(finding.marker and finding.marker in line for finding in found)


def suppression_diff(tmp_path: Path) -> Path:
    """A unit that moves a bare suppression, re-indents one, and adds two new bare ones."""
    repo = repo_with_main(
        tmp_path / "repo",
        {"one.py": "x = 1  # type: ignore\n", "mod.py": "if a:\n    z = 3  # noqa\n"},
    )
    fork_unit_branch(repo)
    commit_files(
        repo,
        {
            "one.py": "x = 1\n",
            "two.py": "import os\nx = 1  # type: ignore\n",
            "mod.py": "if a:\n    if b:\n        z = 3  # noqa\n",
            "fresh.py": 's = "# noqa"\nw = 1  # noqa\n',
        },
    )
    write_files(repo, {"loose.ts": "// @ts-ignore\n"})
    return repo


def test_a_diff_flags_only_the_new_bare_suppressions_in_code_and_in_untracked_files(
    tmp_path: Path,
) -> None:
    repo = suppression_diff(tmp_path)

    found = find_suppressions(repo, read_added_lines(repo, "main"))

    assert {(finding.path, finding.line) for finding in found} == {("fresh.py", 2), ("loose.ts", 1)}


def test_nothing_is_flagged_when_a_reason_is_not_required(tmp_path: Path) -> None:
    repo = suppression_diff(tmp_path)

    found = find_suppressions(repo, read_added_lines(repo, "main"), require_reason=False)

    assert found == []
