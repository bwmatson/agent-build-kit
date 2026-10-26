"""The sync of the pipeline worktree moves it to the tip and leaves the linked machine files alone,
and an installation loaded from the worktree reads them through the links."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import dump
from agent_build_kit.installation import Installation, env_file_for, load_config
from agent_build_kit.machine_files import carry
from agent_build_kit.pipeline.planning_sync import SyncOutcome, sync_planning
from tests.factories import commit_files, git
from tests.machine_files_support import ALL, CONTENT, GITIGNORE, give
from tests.planning_worktree_support import in_repo, installation_at, publish_elsewhere


def test_a_sync_after_a_carry_moves_to_the_new_tip_and_keeps_every_link(tmp_path: Path) -> None:
    setup = in_repo(tmp_path, files={".gitignore": GITIGNORE})
    give(setup.working_copy, *ALL)
    carry(setup.working_copy, setup.worktree, dry_run=False)
    tip = publish_elsewhere(setup, {"notes.md": "new\n"})

    result = sync_planning(installation_at(setup.worktree, setup.working_copy), lambda _line: None)

    assert result.outcome != SyncOutcome.STOPPED
    assert git(setup.worktree, "rev-parse", "HEAD") == tip
    for name in ALL:
        link = setup.worktree / name
        assert link.is_symlink()
        assert link.read_text() == CONTENT[name]


def test_an_installation_loaded_from_the_worktree_reads_the_linked_files(tmp_path: Path) -> None:
    units = tmp_path / "units"
    setup = in_repo(tmp_path, files={".gitignore": GITIGNORE})
    commit_files(
        setup.working_copy,
        "config",
        {"abk.yaml": dump(installation_at(setup.working_copy, setup.working_copy).config)},
    )
    git(setup.working_copy, "push", "-q", "origin", "main")
    git(setup.worktree, "merge", "-q", "--ff-only", "main")
    (setup.working_copy / "abk.local.yaml").write_text(f"planning:\n  worktree_root: {units}\n")
    (setup.working_copy / ".env").write_text("TOKEN=one\n")
    carry(setup.working_copy, setup.worktree, dry_run=False)

    loaded = Installation(load_config(setup.worktree / "abk.yaml"), setup.worktree)

    assert loaded.worktree_root == units.resolve()
    assert env_file_for(loaded.root) == loaded.root / ".env"
    again = tmp_path / "again"
    (setup.working_copy / "abk.local.yaml").write_text(f"planning:\n  worktree_root: {again}\n")

    reloaded = Installation(load_config(setup.worktree / "abk.yaml"), setup.worktree)

    assert reloaded.worktree_root == again.resolve()
