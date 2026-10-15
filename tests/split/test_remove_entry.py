"""`--remove` takes the repo's entry out of the source `abk.yaml` only when nothing names it."""

from tests.planning_split_support import load, split
from tests.split_remove_support import declare_project, entry_lines, populate, trees
from tests.split_sources import write_change

ARGV = ("--repo", "app", "--apply", "--remove")


def kept_line(out):
    (line,) = [x for x in out.splitlines() if x.startswith("kept repo app: still named by")]
    return line


def test_the_entry_goes_when_nothing_names_it(tmp_path):
    source, destination = trees(tmp_path)
    populate(source)
    original = (source / "abk.yaml").read_text()

    code = split(source, *ARGV, "--to", str(destination))

    assert code == 0
    assert (source / "abk.yaml").read_text() == original.replace(entry_lines(original, "app"), "")
    assert (source / "abk.yaml.abk-backup").read_text() == original


def test_a_staying_mixed_change_keeps_the_entry(tmp_path, capsys):
    source, destination = trees(tmp_path)
    installation = populate(source)
    write_change(installation, "both", ["app", "lib"])
    original = (source / "abk.yaml").read_text()

    code = split(source, *ARGV, "--allow-mixed", "source", "--to", str(destination))

    assert code == 1
    assert (source / "abk.yaml").read_text() == original
    assert "both" in kept_line(capsys.readouterr().out)
    assert not (installation.changes_dir / "one").exists()


def test_an_unreadable_change_keeps_the_entry(tmp_path, capsys):
    source, destination = trees(tmp_path)
    installation = populate(source)
    broken = write_change(installation, "broken", ["app"])
    (broken / "tasks.md").write_text("# Tasks\n\n## 1. Group without a repo tag\n\n- [ ] 1.1 x\n")

    code = split(source, *ARGV, "--to", str(destination))

    assert code == 1
    assert "broken" in kept_line(capsys.readouterr().out)
    assert "  app:\n" in (source / "abk.yaml").read_text()


def test_a_repo_that_consumes_it_keeps_the_entry(tmp_path, capsys):
    source, destination = trees(tmp_path, source_repos=dict(app=(), lib=("app",)))
    populate(source)

    code = split(source, *ARGV, "--to", str(destination))

    assert code == 1
    assert "lib" in kept_line(capsys.readouterr().out)
    assert "  app:\n" in (source / "abk.yaml").read_text()


def test_a_project_split_leaves_the_entry(tmp_path):
    source, destination = trees(tmp_path)
    for root in (source, destination):
        declare_project(root, "app", "web")
    installation = load(source)
    write_change(installation, "site", ["app/web"])
    original = (source / "abk.yaml").read_text()

    argv = ("--repo", "app", "--project", "web", "--apply", "--remove", "--to", str(destination))
    code = split(source, *argv)

    assert code == 0
    assert not (installation.changes_dir / "site").exists()
    assert (source / "abk.yaml").read_text() == original
    assert not (source / "abk.yaml.abk-backup").exists()


def test_the_remove_dry_run_says_what_happens_to_the_entry(tmp_path, capsys):
    source, destination = trees(tmp_path)
    populate(source)
    split(source, "--repo", "app", "--to", str(destination), "--remove")
    assert "would remove repo app" in capsys.readouterr().out

    source, destination = trees(tmp_path / "kept", source_repos=dict(app=(), lib=("app",)))
    populate(source)
    split(source, "--repo", "app", "--to", str(destination), "--remove")
    (line,) = [x for x in capsys.readouterr().out.splitlines() if "would keep repo app" in x]
    assert "lib" in line
