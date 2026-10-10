"""Environment inputs are path patterns, and artifacts are left out of them
(spec: pipeline-environment).

Two shapes of repository, both with neutral names: one manifest and one lock at the root
(the shape a single-package project has), and nested manifests with one lock at the root
beside a dependency folder the sync fills (the shape of a workspace).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent_build_kit.config import EnvironmentConfig, EnvironmentInputs
from agent_build_kit.pipeline.environment import inputs_hash, restore_unchanged_locks
from agent_build_kit.pipeline.workspaces import prepare_worktree
from tests.environment_fakes import FakeEnvironment, repo_config
from tests.factories import git, init_repo

BRANCH = "spec/add-marker/1"
LOCK = "deps.lock"


def environment(
    *, dependencies: list[str], lock: list[str] | None = None, artifacts: list[str] | None = None
) -> EnvironmentConfig:
    return EnvironmentConfig(
        sync=["env-sync"],
        check=["env-check"],
        inputs=EnvironmentInputs(dependencies=dependencies, lock=lock or []),
        artifacts=artifacts or [],
    )


def write(root: Path, name: str, text: str = "x\n") -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text)


def legacy_hash(entries: list[tuple[str, bytes | None]]) -> str:
    """What a list of literal names hashed to before patterns: each name, then its bytes or
    `<missing>`, each followed by a NUL."""
    digest = hashlib.sha256()
    for name, content in entries:
        digest.update(name.encode() + b"\0")
        digest.update(b"<missing>" if content is None else content)
        digest.update(b"\0")
    return digest.hexdigest()


# --- 2.1 patterns in the hash -------------------------------------------------------------

ROOT_SHAPE = ("python-shaped", ["manifest.toml"], "manifest.toml", "manifest.toml")
NESTED_SHAPE = ("node-shaped", ["**/manifest.json"], "manifest.json", "packages/web/manifest.json")


@pytest.mark.parametrize(
    ("patterns", "existing", "changed"),
    [ROOT_SHAPE[1:], NESTED_SHAPE[1:]],
    ids=[ROOT_SHAPE[0], NESTED_SHAPE[0]],
)
def test_a_change_to_a_file_a_pattern_names_changes_the_hash(
    tmp_path: Path, patterns: list[str], existing: str, changed: str
) -> None:
    write(tmp_path, existing, "one\n")
    write(tmp_path, LOCK)
    config = environment(dependencies=patterns, lock=[LOCK])
    before = inputs_hash(config, tmp_path)

    write(tmp_path, changed, "two\n")

    assert inputs_hash(config, tmp_path) != before


def test_a_new_nested_manifest_changes_the_hash_a_double_star_pattern_took(
    tmp_path: Path,
) -> None:
    write(tmp_path, "manifest.json")
    write(tmp_path, LOCK)
    config = environment(dependencies=["**/manifest.json"], lock=[LOCK])
    before = inputs_hash(config, tmp_path)

    write(tmp_path, "packages/api/manifest.json", '{"dependencies": {"a": "1"}}\n')

    assert inputs_hash(config, tmp_path) != before


def test_the_double_star_matches_no_directory_as_well_as_many(tmp_path: Path) -> None:
    config = environment(dependencies=["**/manifest.json"])
    write(tmp_path, "manifest.json", "root\n")
    at_root = inputs_hash(config, tmp_path)

    write(tmp_path, "a/b/c/manifest.json", "deep\n")

    assert inputs_hash(config, tmp_path) != at_root


def test_a_literal_path_hashes_as_it_always_did(tmp_path: Path) -> None:
    write(tmp_path, "manifest.toml", "one\n")
    write(tmp_path, LOCK, "locked\n")
    config = environment(dependencies=["manifest.toml"], lock=[LOCK])

    assert inputs_hash(config, tmp_path) == legacy_hash(
        [("manifest.toml", b"one\n"), (LOCK, b"locked\n")]
    )

    write(tmp_path, "packages/new/manifest.toml", "not matched by a literal\n")
    assert inputs_hash(config, tmp_path) == legacy_hash(
        [("manifest.toml", b"one\n"), (LOCK, b"locked\n")]
    ), "a literal path is a pattern that matches itself and nothing else"


def test_a_pattern_matching_nothing_is_recorded_as_missing_until_a_file_appears(
    tmp_path: Path,
) -> None:
    write(tmp_path, LOCK, "locked\n")
    config = environment(dependencies=["**/manifest.json"], lock=[LOCK])

    assert inputs_hash(config, tmp_path) == legacy_hash(
        [("**/manifest.json", None), (LOCK, b"locked\n")]
    )

    write(tmp_path, "packages/api/manifest.json")
    assert inputs_hash(config, tmp_path) != legacy_hash(
        [("**/manifest.json", None), (LOCK, b"locked\n")]
    )


def test_a_pattern_naming_a_directory_covers_every_file_under_it(tmp_path: Path) -> None:
    config = environment(dependencies=["settings"])
    write(tmp_path, "settings/a/one.cfg", "1\n")
    before = inputs_hash(config, tmp_path)

    write(tmp_path, "settings/a/b/two.cfg", "2\n")

    assert inputs_hash(config, tmp_path) != before


def test_a_single_star_stays_within_one_directory(tmp_path: Path) -> None:
    config = environment(dependencies=["packages/*/manifest.json"])
    write(tmp_path, "packages/api/manifest.json", "api\n")
    before = inputs_hash(config, tmp_path)

    write(tmp_path, "packages/api/nested/manifest.json", "too deep\n")

    assert inputs_hash(config, tmp_path) == before

    write(tmp_path, "packages/web/manifest.json", "one level down\n")
    assert inputs_hash(config, tmp_path) != before


def test_git_metadata_is_never_matched(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write(tmp_path, "manifest.json")
    config = environment(dependencies=["**/manifest.json"])
    before = inputs_hash(config, tmp_path)

    write(tmp_path, ".git/modules/sub/manifest.json", "inside git\n")
    assert inputs_hash(config, tmp_path) == before

    write(tmp_path, "sub/manifest.json", "outside git\n")
    assert inputs_hash(config, tmp_path) != before


# --- 2.2 artifacts are left out ------------------------------------------------------------


@pytest.mark.parametrize(
    ("patterns", "artifact"),
    [(["manifest.toml"], ".venv"), (["**/manifest.json"], "modules")],
    ids=["python-shaped", "node-shaped"],
)
def test_filling_an_artifact_directory_leaves_the_hash_unchanged(
    tmp_path: Path, patterns: list[str], artifact: str
) -> None:
    write(tmp_path, patterns[0].removeprefix("**/"))
    write(tmp_path, LOCK)
    config = environment(dependencies=patterns, lock=[LOCK], artifacts=[artifact])
    before = inputs_hash(config, tmp_path)

    write(tmp_path, f"{artifact}/pkg/manifest.json", '{"name": "pkg"}\n')
    write(tmp_path, f"{artifact}/pkg/manifest.toml", "name = 'pkg'\n")
    write(tmp_path, f"{artifact}/pkg/built.bin", "built\n")

    assert inputs_hash(config, tmp_path) == before


def test_a_manifest_inside_an_artifact_is_not_matched_by_an_input_pattern(
    tmp_path: Path,
) -> None:
    write(tmp_path, "manifest.json")
    excluding = environment(dependencies=["**/manifest.json"], artifacts=["modules"])
    unaware = environment(dependencies=["**/manifest.json"])
    before = inputs_hash(excluding, tmp_path)
    before_unaware = inputs_hash(unaware, tmp_path)

    write(tmp_path, "modules/pkg/manifest.json", "inside the artifact\n")

    assert inputs_hash(excluding, tmp_path) == before
    assert inputs_hash(unaware, tmp_path) != before_unaware, (
        "it is the artifact pattern that decides"
    )


def test_artifact_patterns_are_not_themselves_inputs(tmp_path: Path) -> None:
    write(tmp_path, "manifest.toml")
    config = environment(dependencies=["manifest.toml"], artifacts=[".venv"])

    assert inputs_hash(config, tmp_path) == legacy_hash([("manifest.toml", b"x\n")])


# --- 2.3 the comparison against the base ---------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    write(work, "README.md", "base\n")
    write(work, "packages/api/manifest.json", '{"a": "1"}\n')
    write(work, LOCK, "as committed\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    return work


def kept_lock(repo: Path, tmp_path: Path, *, artifacts: tuple[str, ...] = (), edits) -> bool:
    """Whether the commit step's lock rule kept the lock the sync rewrote (the unit changed a
    dependency input) rather than putting it back (it did not), after `edits` to the worktree
    of a repository whose dependency inputs are `**/manifest.json`."""
    env = FakeEnvironment(
        tmp_path / "control", inputs=("**/manifest.json",), locks=(LOCK,), artifacts=artifacts
    )
    tree = prepare_worktree(repo, BRANCH, base="main", root=tmp_path / "trees", locks=(LOCK,))
    edits(tree)
    write(tree, LOCK, "rewritten by the sync\n")

    restore_unchanged_locks(repo_config(tmp_path / "meta", env), tree, "main")

    return (tree / LOCK).read_text() == "rewritten by the sync\n"


def test_a_unit_that_added_a_matching_file_changed_the_inputs(repo: Path, tmp_path: Path) -> None:
    assert kept_lock(
        repo, tmp_path, edits=lambda tree: write(tree, "packages/web/manifest.json", "{}\n")
    )


def test_a_unit_that_changed_a_matching_file_changed_the_inputs(repo: Path, tmp_path: Path) -> None:
    assert kept_lock(
        repo,
        tmp_path,
        edits=lambda tree: write(tree, "packages/api/manifest.json", '{"a": "2"}\n'),
    )


def test_a_unit_that_removed_a_matching_file_changed_the_inputs(repo: Path, tmp_path: Path) -> None:
    assert kept_lock(
        repo, tmp_path, edits=lambda tree: (tree / "packages/api/manifest.json").unlink()
    )


def test_a_unit_that_touched_no_matching_file_did_not(repo: Path, tmp_path: Path) -> None:
    assert not kept_lock(repo, tmp_path, edits=lambda tree: write(tree, "marker.py", "M = 1\n"))


def test_a_manifest_an_artifact_holds_is_not_a_change_the_unit_made(
    repo: Path, tmp_path: Path
) -> None:
    assert not kept_lock(
        repo,
        tmp_path,
        artifacts=("modules",),
        edits=lambda tree: write(tree, "modules/pkg/manifest.json", "{}\n"),
    )
