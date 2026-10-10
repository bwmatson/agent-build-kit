"""The guard against framework code naming an ecosystem (spec: environment-is-language-independent).

Source outside `profiles/` and `init/` that names a package manager, manifest or lock file
fails the guard unless its file is on the allowlist (which only shrinks) or the framework's
own-tooling list; a listed file with no name left fails as stale.
"""

from __future__ import annotations

from pathlib import Path

from tests.ecosystem_names import (
    ALLOWLIST,
    OWN_TOOLING,
    SOURCE_ROOT,
    TOKENS,
    check_source,
)

NONE: frozenset[str] = frozenset()


def tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def test_a_listed_package_manager_in_framework_source_fails_naming_file_and_line(
    tmp_path: Path,
) -> None:
    root = tree(tmp_path, {"pipeline/step.py": "x = 1\nRUN = ['npm', 'install']\n"})

    problems = check_source(root, allowlist=NONE, own_tooling=NONE)

    assert len(problems) == 1
    assert "pipeline/step.py:2" in problems[0]


def test_a_listed_lock_file_name_fails_too(tmp_path: Path) -> None:
    root = tree(tmp_path, {"step.py": "LOCK = 'pnpm-lock.yaml'\n"})

    assert any("step.py:1" in p for p in check_source(root, allowlist=NONE, own_tooling=NONE))


def test_the_same_text_in_profiles_or_init_passes(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "profiles/node.py": "MANAGER = 'npm'\n",
            "init/environment.py": "LOCK = 'package-lock.json'\n",
        },
    )

    assert check_source(root, allowlist=NONE, own_tooling=NONE) == []


def test_a_name_in_a_string_or_a_comment_is_found(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "a.py": "# run it with yarn\n",
            "b.py": 'TEXT = "install with cargo"\n',
            "c.py": '"""Docstring about pyproject.toml."""\n',
        },
    )

    problems = check_source(root, allowlist=NONE, own_tooling=NONE)

    assert len(problems) == 3
    assert any("a.py:1" in p for p in problems)
    assert any("b.py:1" in p for p in problems)
    assert any("c.py:1" in p for p in problems)


def test_a_token_inside_a_longer_word_or_hyphenated_name_is_not_a_name(
    tmp_path: Path,
) -> None:
    root = tree(
        tmp_path,
        {"a.py": "# a pipeline of uvula, a pip-boy, an npm-like thing, a yarnball\n"},
    )

    assert check_source(root, allowlist=NONE, own_tooling=NONE) == []


def test_an_allowlisted_file_may_keep_its_names(tmp_path: Path) -> None:
    root = tree(tmp_path, {"cli/doctor.py": "CMD = 'uv run'\n"})

    assert check_source(root, allowlist=frozenset({"cli/doctor.py"}), own_tooling=NONE) == []


def test_an_allowlisted_file_with_no_names_left_fails_as_stale(tmp_path: Path) -> None:
    root = tree(tmp_path, {"cli/doctor.py": "CMD = 'run'\n"})

    problems = check_source(root, allowlist=frozenset({"cli/doctor.py"}), own_tooling=NONE)

    assert len(problems) == 1
    assert "cli/doctor.py" in problems[0]
    assert "allowlist" in problems[0].lower()


def test_an_own_tooling_file_may_keep_its_names(tmp_path: Path) -> None:
    root = tree(tmp_path, {"openspec.py": "CMD = 'npx'\n"})

    assert check_source(root, allowlist=NONE, own_tooling=frozenset({"openspec.py"})) == []


def test_an_own_tooling_entry_with_no_names_left_fails_as_stale(tmp_path: Path) -> None:
    root = tree(tmp_path, {"openspec.py": "CMD = 'run'\n"})

    problems = check_source(root, allowlist=NONE, own_tooling=frozenset({"openspec.py"}))

    assert len(problems) == 1
    assert "openspec.py" in problems[0]
    assert "own-tooling" in problems[0].lower()


def test_a_listed_file_that_no_longer_exists_is_stale(tmp_path: Path) -> None:
    problems = check_source(
        tmp_path, allowlist=frozenset({"gone.py"}), own_tooling=frozenset({"missing.py"})
    )

    assert len(problems) == 2
    assert any("gone.py" in p for p in problems)
    assert any("missing.py" in p for p in problems)


def test_a_new_token_is_one_line_in_the_token_list(tmp_path: Path) -> None:
    root = tree(tmp_path, {"a.py": "TOOL = 'bundler'\n"})

    assert check_source(root, allowlist=NONE, own_tooling=NONE) == []
    assert check_source(root, allowlist=NONE, own_tooling=NONE, tokens=(*TOKENS, "bundler"))


def test_the_framework_source_names_no_ecosystem_outside_the_lists() -> None:
    assert check_source(SOURCE_ROOT, allowlist=ALLOWLIST.keys(), own_tooling=OWN_TOOLING) == []


def test_the_lists_hold_the_files_the_design_names_each_with_a_reason() -> None:
    assert set(ALLOWLIST) == {"cli/doctor.py", "tracks/runner.py"}
    assert set(OWN_TOOLING) == {
        "openspec.py",
        "serve/server.py",
        "settings.py",
        "config.py",
        "timers.py",
    }
    assert all(reason.strip() for reason in [*ALLOWLIST.values(), *OWN_TOOLING.values()])
