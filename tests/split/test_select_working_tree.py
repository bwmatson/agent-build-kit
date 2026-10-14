"""The source is read as it is on disk, and what git calls uncommitted is reported."""

from agent_build_kit.split.select import plan_split, uncommitted
from tests.factories import git, init_repo
from tests.split_sources import source_installation, write_change


def commit_everything(source):
    init_repo(source.root)
    git(source.root, "add", "-A")
    git(source.root, "commit", "-q", "-m", "start")


def test_an_untracked_change_is_classified(tmp_path):
    source = source_installation(tmp_path)
    write_change(source, "committed", ["lib"])
    commit_everything(source)
    write_change(source, "fresh", ["app"])

    plan = plan_split(source, "app")

    assert plan.changes_moved == ("fresh",)
    assert plan.changes_staying == ("committed",)


def test_a_file_deleted_in_the_tree_is_not_read(tmp_path):
    source = source_installation(tmp_path)
    gone = write_change(source, "gone", ["app"])
    kept = write_change(source, "partly", ["app"])
    commit_everything(source)
    for name in ("tasks.md", "proposal.md"):
        (gone / name).unlink()
    gone.rmdir()
    (kept / "proposal.md").unlink()

    plan = plan_split(source, "app")

    assert plan.changes_moved == ("partly",)
    assert "gone" not in (*plan.changes_staying, *(item.name for item in plan.changes_unreadable))


def test_modified_untracked_and_deleted_files_are_listed_with_a_count(tmp_path):
    source = source_installation(tmp_path)
    change = write_change(source, "feature", ["app"])
    (change / "design.md").write_text("# Design\n")
    commit_everything(source)
    (change / "proposal.md").write_text("# changed\n")
    (change / "notes.md").write_text("# new\n")
    (change / "design.md").unlink()
    relative = change.relative_to(source.root)

    lines = uncommitted(source)

    assert sorted(lines or ()) == sorted(
        [f"M {relative}/proposal.md", f"?? {relative}/notes.md", f"D {relative}/design.md"]
    )
    assert plan_split(source, "app").uncommitted == lines
    assert len(lines or ()) == 3


def test_a_source_outside_git_has_no_git_information(tmp_path):
    source = source_installation(tmp_path)
    write_change(source, "feature", ["app"])

    assert uncommitted(source) is None
    assert plan_split(source, "app").uncommitted is None
