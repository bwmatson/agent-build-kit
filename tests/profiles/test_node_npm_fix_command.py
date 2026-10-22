"""node-npm formats and fixes the source files it is given, and nothing else
(spec: fixers-run-before-commits).

The command runs for real in a project whose `npx` records its arguments: what it names is
what the formatter and the linter would have been given.
"""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.profiles.base import AppliesFixers
from tests.node_npx_fake import Project, make_project

# The linter exits 1 for a finding it cannot fix, as the real one does.
LINT_FAILS = """\
#!/bin/sh
{ echo "--- call"; printf '%s\\n' "$@"; } >> "$CALLS"
[ "$1" = oxlint ] && exit 1
exit 0
"""


@pytest.fixture
def project(tmp_path: Path) -> Project:
    made = make_project(tmp_path)
    (tmp_path / "bin" / "npx").write_text(LINT_FAILS)
    return made


def fix_command(files: list[str]) -> list[str] | None:
    profile = profiles.get("node-npm")
    assert isinstance(profile, AppliesFixers)
    return profile.fix_command(files)


def test_the_formatter_then_the_fixer_run_over_the_source_files_only(project: Project) -> None:
    command = fix_command(["src/a.ts", "README.md", "src/b.tsx"])

    assert command is not None
    project.run(shlex.join(command))

    assert project.calls_made() == [
        ["oxfmt", "src/a.ts", "src/b.tsx"],
        ["oxlint", "--fix", "src/a.ts", "src/b.tsx"],
    ]


def test_a_failing_linter_does_not_undo_the_format_that_ran_first(project: Project) -> None:
    command = fix_command(["src/a.ts"])

    assert command is not None
    done = project.run(shlex.join(command))

    assert done.returncode == 1
    assert [call[0] for call in project.calls_made()] == ["oxfmt", "oxlint"]


def test_the_type_check_is_never_run(project: Project) -> None:
    command = fix_command(["src/a.ts", "src/b.mts"])

    assert command is not None
    project.run(shlex.join(command))

    assert "tsc" not in [word for call in project.calls_made() for word in call]


def test_files_that_are_not_source_files_give_no_command() -> None:
    assert fix_command(["README.md", "package.json"]) is None
