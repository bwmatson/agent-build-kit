"""`git_running_in` finds a git process by its working directory, which decides whether a
restack may delete a lock. These start a real long-lived git process; no clock is waited on,
since one reply from it proves it is running."""

import subprocess
from pathlib import Path

from agent_build_kit.pipeline import shell
from tests.factories import commit, init_repo


def test_a_running_git_process_is_found_by_its_directory_and_only_there(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    commit(repo, "a.txt", "a\n")
    (repo / "sub").mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    with subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=repo / "sub",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as process:
        assert process.stdin is not None
        assert process.stdout is not None
        try:
            process.stdin.write("HEAD\n")
            process.stdin.flush()
            assert process.stdout.readline()

            assert shell.git_running_in(repo)
            assert not shell.git_running_in(elsewhere)
        finally:
            process.stdin.close()
            process.wait()

    assert not shell.git_running_in(repo)
