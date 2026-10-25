"""The one reader of the paths a task group names: `line_paths` keeps the token rules the e2e
scope reader had, and `named_paths` adds the `Paths:` line, glob prefixes, prose paths anchored
on a declared project and the exclusion of lines that are not changes (spec: project-resolution)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.group_paths import line_paths, named_paths
from agent_build_kit.pipeline.work_graph import validate_tasks
from tests.project_workspace import OPT_OUT, app_with_projects

PROJECTS = ("web", "services/api")


@pytest.mark.parametrize(
    ("line", "paths"),
    [
        ("- [ ] 1.1 Fix `src/client/retry.py`", ["src/client/retry.py"]),
        ("- [ ] 1.1 Edit `retry.py` and `docs/cli.md`", ["retry.py", "docs/cli.md"]),
        ("- [ ] 1.1 See `src/client/retry.py:42`", ["src/client/retry.py"]),
        (
            "- [ ] 1.1 Run `tests/e2e/test_route.py::test_stream`",
            ["tests/e2e/test_route.py"],
        ),
        ("- [ ] 1.1 Look in `src/client/`", ["src/client"]),
        ("- [ ] 1.1 A path with no ticks, src/client/retry.py", []),
    ],
)
def test_backticked_tokens_with_a_slash_or_an_extension_are_paths_cleaned_of_their_suffix(
    line: str, paths: list[str]
) -> None:
    assert line_paths(line) == paths


@pytest.mark.parametrize(
    "token",
    [
        "https://example.com/a/b.html",
        "--flag",
        "-x/y",
        "RETRY=3",
        "$HOME/x.py",
        "src/**/*.py",
        "src/*.py",
        "retry()",
        "make test",
        "a b/c.py",
        "<name>/x.py",
    ],
)
def test_urls_flags_assignments_globs_symbols_and_spaced_text_are_not_paths(token: str) -> None:
    assert line_paths(f"- [ ] 1.1 Use `{token}` here") == []


def named(tmp_path: Path, body: str) -> list[str]:
    """The paths `named_paths` reads from one `[app]` group whose lines are `body`."""
    app_with_projects(tmp_path / "planning", *PROJECTS)
    (tmp_path / "tasks.md").write_text(
        f"# Tasks\n\n{OPT_OUT}\n## 1. [app] [unit-test] Group\n\n{body}"
    )
    groups, errors = validate_tasks(tmp_path / "tasks.md")
    assert errors == []
    return named_paths(groups[0], PROJECTS)


def test_a_paths_line_is_authoritative_over_the_task_lines(tmp_path: Path) -> None:
    body = (
        "Paths: `web/**`\n\n"
        "- [ ] 1.1 Test: it. Edit `services/api/src/route.py`.\n"
        "- [ ] 1.2 Do it in `docs/cli.md`.\n"
    )

    assert named(tmp_path, body) == ["web/"]


def test_a_glob_counts_by_its_literal_prefix(tmp_path: Path) -> None:
    body = "- [ ] 1.1 Test: it.\n- [ ] 1.2 Change everything under `web/src/**`.\n"

    assert named(tmp_path, body) == ["web/src/"]


def test_an_unticked_word_anchored_on_a_declared_project_counts_and_other_words_do_not(
    tmp_path: Path,
) -> None:
    body = "- [ ] 1.1 Edit web/src/app.ts to add the filter, not src/other.py or README.md.\n"

    assert named(tmp_path, body) == ["web/src/app.ts"]


def test_a_path_relative_to_a_project_is_the_path_it_is_written_as(tmp_path: Path) -> None:
    body = "- [ ] 1.1 Edit `src/app.ts` in the web project.\n"

    assert named(tmp_path, body) == ["src/app.ts"]


@pytest.mark.parametrize(
    "line",
    [
        "Not changed: `services/api/src/route.py`, `docs/cli.md`.",
        "Planning note: this edits `services/api/src/route.py`.",
        "Reads: `services/api/src/route.py`",
    ],
)
def test_a_line_that_is_not_a_change_does_not_name_paths(tmp_path: Path, line: str) -> None:
    body = f"{line}\n\n- [ ] 1.1 Test: it. Edit `web/src/app.ts`.\n"

    assert named(tmp_path, body) == ["web/src/app.ts"]


def test_a_verify_segment_of_a_task_line_does_not_name_paths(tmp_path: Path) -> None:
    body = "- [ ] 1.1 Edit `web/src/app.ts`. Verify: red against `services/api/tests/test_x.py`.\n"

    assert named(tmp_path, body) == ["web/src/app.ts"]


@pytest.mark.parametrize(
    "sentence",
    [
        "Do not touch `services/api/src/route.py`.",
        "It must not edit `services/api/src/route.py`.",
        "Everything else is left unchanged, including `services/api/src/route.py`.",
    ],
)
def test_a_sentence_after_unchanged_must_not_or_do_not_does_not_name_paths(
    tmp_path: Path, sentence: str
) -> None:
    body = f"- [ ] 1.1 Edit `web/src/app.ts`. {sentence}\n"

    assert named(tmp_path, body) == ["web/src/app.ts"]


def test_a_path_the_group_names_twice_in_one_line_is_found_in_order(tmp_path: Path) -> None:
    body = "- [ ] 1.1 Edit `web/src/a.ts` and `web/src/b.ts`.\n"

    assert named(tmp_path, body) == ["web/src/a.ts", "web/src/b.ts"]
