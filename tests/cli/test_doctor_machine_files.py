"""`abk doctor` reports a machine file the working copy has and the pipeline worktree lacks
(spec: pipeline-worktree-machine-files)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.machine_files import carry
from tests.cli.in_repo_doctor import checks_of, in_repo, named, separate, with_pipeline_worktree
from tests.machine_files_support import CONTENT

CHECK = "machine files"
OVERLAY = "abk.local.yaml"
# An overlay that loads: the doctor reads it from the working copy.
OVERLAY_TEXT = "{}\n"


def working_copy_with(tmp_path: Path, *names: str) -> tuple[Path, Path]:
    """The `abk.yaml` of an in-repo installation with a live worktree, and that worktree; the
    working copy holds these machine files."""
    config = in_repo(tmp_path / "app", publish="branch")
    worktree = with_pipeline_worktree(config)
    for name in names:
        (config.parent / name).write_text(OVERLAY_TEXT if name == OVERLAY else CONTENT[name])
    return config, worktree


def test_a_file_in_the_working_copy_with_no_link_fails_naming_it_and_install_timers(
    tmp_path: Path,
) -> None:
    config, _ = working_copy_with(tmp_path, OVERLAY)

    [found] = named(checks_of(config), CHECK)

    assert found.status == "FAIL"
    assert OVERLAY in found.detail
    assert "abk install-timers" in found.fix


def test_the_same_failure_shows_when_doctor_runs_from_the_worktree(tmp_path: Path) -> None:
    config, worktree = working_copy_with(tmp_path, OVERLAY)

    [found] = named(checks_of(worktree / "abk.yaml"), CHECK)

    assert found.status == "FAIL"
    assert OVERLAY in found.detail
    assert "abk install-timers" in found.fix
    assert config.parent != worktree


def test_a_carried_set_passes(tmp_path: Path) -> None:
    config, worktree = working_copy_with(tmp_path, OVERLAY, ".env", "scrub.local")
    carry(config.parent, worktree, dry_run=False)

    for path in (config, worktree / "abk.yaml"):
        [found] = named(checks_of(path), CHECK)
        assert found.status == "ok"


def test_a_regular_file_with_different_bytes_fails_naming_it(tmp_path: Path) -> None:
    config, worktree = working_copy_with(tmp_path, ".env")
    (worktree / ".env").write_text("TOKEN=other\n")

    [found] = named(checks_of(config), CHECK)

    assert found.status == "FAIL"
    assert ".env" in found.detail


def test_a_regular_file_with_the_same_bytes_passes(tmp_path: Path) -> None:
    config, worktree = working_copy_with(tmp_path, ".env")
    (worktree / ".env").write_text(CONTENT[".env"])

    [found] = named(checks_of(config), CHECK)

    assert found.status == "ok"


def test_a_dangling_link_fails(tmp_path: Path) -> None:
    config, worktree = working_copy_with(tmp_path, ".env")
    (worktree / ".env").symlink_to(tmp_path / "gone")

    [found] = named(checks_of(config), CHECK)

    assert found.status == "FAIL"
    assert ".env" in found.detail


def test_a_working_copy_with_none_of_the_files_warns_naming_all_three(tmp_path: Path) -> None:
    config, _ = working_copy_with(tmp_path)

    checks = checks_of(config)
    [found] = named(checks, CHECK)

    assert found.status == "warn"
    text = f"{found.detail} {found.fix}"
    for name in (OVERLAY, ".env", "scrub.local"):
        assert name in text
    assert [c for c in checks if c.status == "FAIL"] == []


def test_a_linked_env_alone_is_ok_and_says_nothing_of_the_others(tmp_path: Path) -> None:
    config, worktree = working_copy_with(tmp_path, ".env")
    carry(config.parent, worktree, dry_run=False)

    [found] = named(checks_of(config), CHECK)

    assert found.status == "ok"
    assert OVERLAY not in f"{found.detail} {found.fix}"
    assert "scrub.local" not in f"{found.detail} {found.fix}"


def test_a_separate_installation_has_no_machine_files_check(tmp_path: Path) -> None:
    code = tmp_path / "code"
    code.mkdir()
    config = separate(tmp_path / "plan", code)

    assert named(checks_of(config), CHECK) == []


def test_an_in_repo_installation_with_no_marker_has_no_machine_files_check(
    tmp_path: Path,
) -> None:
    config = in_repo(tmp_path / "app", publish="branch")
    (config.parent / ".env").write_text(CONTENT[".env"])

    assert named(checks_of(config), CHECK) == []
