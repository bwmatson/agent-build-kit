"""Which paths never land without a person (spec: review-policy, protected paths)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from agent_build_kit.pipeline.review_paths import is_protected, protected_settings
from agent_build_kit.pipeline.shell import changed_files, git
from tests.factories import commit_files, init_repo
from tests.review_config import workspace

MIGRATION = "db/migrations/0042_add_index.sql"


@pytest.mark.parametrize(
    "path",
    [
        MIGRATION,
        ".github/workflows/ci.yml",
        "Dockerfile",
        "services/api/Dockerfile",
        "docker-compose.yml",
        ".env",
        "config/.env.production",
        "secrets/prod.key",
        "deploy/server.pem",
        ".github/CODEOWNERS",
        "CODEOWNERS",
    ],
)
def test_the_framework_defaults_protect(path: str) -> None:
    assert is_protected(workspace(), "app", path)


@pytest.mark.parametrize("path", ["src/app.py", "README.md", "tests/test_app.py", "docs/guide.md"])
def test_the_framework_defaults_leave_an_ordinary_file_alone(path: str) -> None:
    assert not is_protected(workspace(), "app", path)


def test_the_workspace_list_and_the_repos_list_are_added() -> None:
    config = workspace(
        {"protected_paths": ["deploy/**"]}, app={"protected_paths": ["src/billing/**"]}
    )

    assert is_protected(config, "app", "deploy/up.sh")
    assert is_protected(config, "app", "src/billing/charge.py")
    assert is_protected(config, "app", MIGRATION), "the defaults are still there"


def test_a_repos_list_does_not_apply_to_another_repo() -> None:
    config = workspace(
        {"protected_paths": ["deploy/**"]}, app={"protected_paths": ["src/billing/**"]}
    )

    assert is_protected(config, "platform", "deploy/up.sh")
    assert not is_protected(config, "platform", "src/billing/charge.py")


def test_a_repos_list_never_narrows_the_workspaces() -> None:
    config = workspace({"protected_paths": ["deploy/**"]}, app={"protected_paths": []})

    assert is_protected(config, "app", "deploy/up.sh")


def test_without_the_defaults_only_the_lists_protect() -> None:
    config = workspace(
        {"protected_defaults": False, "protected_paths": ["deploy/**"]},
        platform={"protected_paths": ["infra/**"]},
    )

    assert is_protected(config, "app", "deploy/up.sh")
    assert is_protected(config, "platform", "infra/main.tf")
    assert not is_protected(config, "app", MIGRATION)
    assert not is_protected(config, "app", "Dockerfile")
    assert not is_protected(config, "app", "infra/main.tf")


def test_a_directory_pattern_protects_everything_under_it() -> None:
    config = workspace({"protected_defaults": False, "protected_paths": ["deploy"]})

    assert is_protected(config, "app", "deploy/nested/up.sh")
    assert not is_protected(config, "app", "deployment/up.sh")


@pytest.mark.parametrize(
    "path",
    [
        ".jscpd.json",
        "web/eslint.config.js",
        "ruff.toml",
        "svc/.pre-commit-config.yaml",
        "web/vitest.config.ts",
    ],
)
def test_a_whole_file_default_is_a_protected_path(path: str) -> None:
    assert is_protected(workspace(), "app", path)


WHOLE_FILE_DEFAULTS = (".jscpd.json", "web/eslint.config.js", "ruff.toml", "web/vitest.config.ts")


def test_a_file_protected_by_key_or_judged_by_content_is_not_a_protected_path() -> None:
    config = workspace()

    assert all(is_protected(config, "app", path) for path in WHOLE_FILE_DEFAULTS)
    assert not any(
        is_protected(config, "app", path)
        for path in ("pyproject.toml", "package.json", "setup.cfg", "quality_baseline.toml")
    )


def test_without_the_defaults_a_whole_file_default_does_not_protect() -> None:
    with_defaults = workspace()
    without = workspace({"protected_defaults": False})

    assert all(is_protected(with_defaults, "app", path) for path in WHOLE_FILE_DEFAULTS)
    assert not any(is_protected(without, "app", path) for path in WHOLE_FILE_DEFAULTS)


def test_a_repos_whole_file_entry_protects_its_file_in_that_repo_only() -> None:
    config = workspace(app={"protected_config": {"**/mypy.ini": []}})

    assert is_protected(config, "app", "svc/mypy.ini")
    assert not is_protected(config, "platform", "svc/mypy.ini")


def pyproject(
    *,
    select: str = '["E"]',
    deps: str = '["a"]',
    pytest_opts: str = '"-q"',
    pyrefly: bool = True,
    coverage: bool = False,
) -> str:
    tables = [
        f"[project]\nname = 'x'\ndependencies = {deps}\n",
        f"[tool.ruff.lint]\nselect = {select}\n",
        f"[tool.pytest.ini_options]\naddopts = {pytest_opts}\n",
    ]
    if pyrefly:
        tables.append("[tool.pyrefly]\nstrict = true\n")
    if coverage:
        tables.append("[tool.coverage.run]\nbranch = true\n")
    return "\n".join(tables)


PYPROJECT = pyproject()
PACKAGE = '{"scripts": {"test": "jest", "build": "tsc"}, "dependencies": {"a": "1"}}'
SETUP_CFG = "[tool:pytest]\naddopts = -q\n\n[metadata]\nname = x\n"
BASELINE = (
    '[[files]]\npath = "a.py"\nlines = 500\n\n'
    '[[functions]]\npath = "a.py"\nname = "f"\ncomplexity = 20\n\n'
    '[[functions]]\npath = "a.py"\nname = "g"\ncomplexity = 30\n'
)
BASELINE_GROWN = BASELINE + '\n[[functions]]\npath = "a.py"\nname = "h"\ncomplexity = 25\n'
BASELINE_SHRUNK = '[[files]]\npath = "a.py"\nlines = 400\n\n' + BASELINE.split("\n\n", 2)[1]
BASELINE_RAISED = BASELINE.replace("lines = 500", "lines = 600")
BASELINE_MEASURE = BASELINE.replace("lines = 500", "lines = 500\ncomplexity = 9")
REFORMATTED = (
    "[tool.pyrefly]\nstrict = true\n\n[tool.pytest.ini_options]\naddopts = '-q'\n\n"
    "[tool.ruff.lint]\nselect = ['E']\n\n[project]\ndependencies = ['a']\nname = 'x'\n"
)

CASES: dict[str, tuple[dict[str, str], dict[str, str | None], list[str]]] = {
    "a ruff setting changed": (
        {"pyproject.toml": PYPROJECT},
        {"pyproject.toml": pyproject(select='["E", "F"]')},
        ["pyproject.toml: tool.ruff"],
    ),
    "a dependency changed": (
        {"pyproject.toml": PYPROJECT},
        {"pyproject.toml": pyproject(deps='["a", "b"]')},
        [],
    ),
    "a project's pytest setting changed": (
        {"svc/pyproject.toml": PYPROJECT},
        {"svc/pyproject.toml": pyproject(pytest_opts='"-x"')},
        ["svc/pyproject.toml: tool.pytest"],
    ),
    "a coverage table added": (
        {"pyproject.toml": PYPROJECT},
        {"pyproject.toml": pyproject(coverage=True)},
        ["pyproject.toml: tool.coverage"],
    ),
    "a pyrefly table removed": (
        {"pyproject.toml": PYPROJECT},
        {"pyproject.toml": pyproject(pyrefly=False)},
        ["pyproject.toml: tool.pyrefly"],
    ),
    "the same values reformatted and reordered": (
        {"pyproject.toml": PYPROJECT},
        {"pyproject.toml": REFORMATTED},
        [],
    ),
    "the test script changed": (
        {"package.json": PACKAGE},
        {"package.json": PACKAGE.replace('"jest"', '"vitest"')},
        ["package.json: scripts.test"],
    ),
    "the build script changed": (
        {"package.json": PACKAGE},
        {"package.json": PACKAGE.replace('"tsc"', '"vite build"')},
        [],
    ),
    "a pytest section of setup.cfg changed": (
        {"setup.cfg": SETUP_CFG},
        {"setup.cfg": SETUP_CFG.replace("-q", "-x")},
        ["setup.cfg: tool:pytest"],
    ),
    "the metadata section of setup.cfg changed": (
        {"setup.cfg": SETUP_CFG},
        {"setup.cfg": SETUP_CFG.replace("name = x", "name = y")},
        [],
    ),
    "a pyproject that no longer parses": (
        {"pyproject.toml": PYPROJECT},
        {"pyproject.toml": "[tool.ruff\n"},
        ["pyproject.toml: does not parse"],
    ),
    "a pyproject deleted that held two protected keys": (
        {"pyproject.toml": pyproject(pyrefly=False)},
        {"pyproject.toml": None},
        ["pyproject.toml: tool.pytest", "pyproject.toml: tool.ruff"],
    ),
    "a baseline that only shrinks": (
        {"quality_baseline.toml": BASELINE},
        {"quality_baseline.toml": BASELINE_SHRUNK},
        [],
    ),
    "a baseline with an added function entry": (
        {"quality_baseline.toml": BASELINE},
        {"quality_baseline.toml": BASELINE_GROWN},
        ["quality_baseline.toml: grows"],
    ),
    "a baseline with a raised line count": (
        {"quality_baseline.toml": BASELINE},
        {"quality_baseline.toml": BASELINE_RAISED},
        ["quality_baseline.toml: grows"],
    ),
    "a baseline entry with a measure added": (
        {"quality_baseline.toml": BASELINE},
        {"quality_baseline.toml": BASELINE_MEASURE},
        ["quality_baseline.toml: grows"],
    ),
    "a baseline new on the branch": (
        {},
        {"quality_baseline.toml": BASELINE},
        ["quality_baseline.toml: grows"],
    ),
    "a baseline deleted": (
        {"quality_baseline.toml": BASELINE},
        {"quality_baseline.toml": None},
        ["quality_baseline.toml: deleted"],
    ),
    "a baseline that does not parse": (
        {"quality_baseline.toml": BASELINE},
        {"quality_baseline.toml": "[[files\n"},
        ["quality_baseline.toml: does not parse"],
    ),
}


def branch_changes(
    repo: Path, on_main: Mapping[str, str], on_branch: Mapping[str, str | None]
) -> tuple[str, ...]:
    """A `main` holding `on_main` and a unit branch that writes `on_branch` (None deletes),
    returning the branch's changed paths."""
    init_repo(repo)
    commit_files(repo, "base", {"README.md": "x", **on_main})
    git(repo, "checkout", "-q", "-b", "unit")
    for name, content in on_branch.items():
        if content is None:
            git(repo, "rm", "-q", name)
    written = {name: content for name, content in on_branch.items() if content is not None}
    commit_files(repo, "work", written)
    return tuple(changed_files(repo, "main"))


@pytest.mark.parametrize("name", list(CASES))
def test_protected_settings_names_each_changed_bar_setting_of_a_real_branch(
    name: str, tmp_path: Path
) -> None:
    on_main, on_branch, expected = CASES[name]
    paths = branch_changes(tmp_path / "app", on_main, on_branch)

    found = protected_settings(workspace(), "app", tmp_path / "app", "main", paths)

    assert sorted(found) == sorted(expected)


def test_a_repos_entry_protects_its_key_for_that_repo_only(tmp_path: Path) -> None:
    changed = {"pyproject.toml": PYPROJECT + "\n[tool.mypy]\nstrict = true\n"}
    checkout = tmp_path / "app"
    paths = branch_changes(checkout, {"pyproject.toml": PYPROJECT}, changed)
    config = workspace(app={"protected_config": {"**/pyproject.toml": ["tool.mypy"]}})

    assert protected_settings(config, "app", checkout, "main", paths) == (
        "pyproject.toml: tool.mypy",
    )
    assert protected_settings(config, "platform", checkout, "main", paths) == ()


def test_without_the_defaults_and_without_an_entry_a_ruff_change_gives_nothing(
    tmp_path: Path,
) -> None:
    changed = {"pyproject.toml": pyproject(select='["F"]')}
    checkout = tmp_path / "app"
    paths = branch_changes(checkout, {"pyproject.toml": PYPROJECT}, changed)

    found = protected_settings(
        workspace({"protected_defaults": False}), "app", checkout, "main", paths
    )

    assert found == ()


def test_a_file_whose_bytes_do_not_decode_is_reported_as_unreadable(tmp_path: Path) -> None:
    checkout = tmp_path / "app"
    branch_changes(checkout, {"pyproject.toml": PYPROJECT}, {"other.txt": "x"})
    (checkout / "pyproject.toml").write_bytes(b"x = '\xff'\n")
    git(checkout, "add", "-A")
    git(checkout, "commit", "-qm", "bytes")

    found = protected_settings(workspace(), "app", checkout, "main", ("pyproject.toml",))

    assert found == ("pyproject.toml: could not be read",)


def test_a_base_that_does_not_resolve_protects_and_raises_nothing(tmp_path: Path) -> None:
    checkout = tmp_path / "app"
    paths = branch_changes(checkout, {"pyproject.toml": PYPROJECT}, {"pyproject.toml": "x = 1"})

    found = protected_settings(workspace(), "app", checkout, "no-such-base", paths)

    assert found == ("pyproject.toml: could not be read",)


def test_paths_no_keyed_pattern_matches_cost_nothing_even_outside_a_git_repository(
    tmp_path: Path,
) -> None:
    found = protected_settings(workspace(), "app", tmp_path, "main", ("src/app.py", "README.md"))

    assert found == ()
