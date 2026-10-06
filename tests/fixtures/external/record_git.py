"""Re-record `tests/fixtures/external/git/*.txt` from the installed git.

    uv run python tests/fixtures/external/record_git.py

Each fixture is what a real `git` printed, run here against temporary bare
remotes (a pre-receive hook, a branch that moved under a lease, a path that is
not a repository) and a rerere replay. Only temporary paths and commit ids are
redacted; stdout and stderr are kept apart because git writes to each. The
header names the tool version, the command and the return code.
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().parent / "git"

ENV = {
    **os.environ,
    "LC_ALL": "C",
    "LANGUAGE": "C",
    "GIT_AUTHOR_NAME": "Example",
    "GIT_AUTHOR_EMAIL": "example@example.invalid",
    "GIT_COMMITTER_NAME": "Example",
    "GIT_COMMITTER_EMAIL": "example@example.invalid",
    "GIT_EDITOR": "true",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def run(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args], cwd=cwd, env=ENV, capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result


def commit(repo: Path, name: str, content: str, message: str) -> str:
    (repo / name).write_text(content)
    run(repo, "add", name)
    run(repo, "commit", "-qm", message)
    return run(repo, "rev-parse", "HEAD").stdout.strip()


def clone_with_branch(root: Path, label: str) -> tuple[Path, Path]:
    """A bare remote `label.git` and a clone of it holding branch `b` with one commit, pushed."""
    remote = root / f"{label}.git"
    run(root, "init", "-q", "--bare", "-b", "main", str(remote))
    work = root / label
    run(root, "clone", "-q", str(remote), str(work))
    run(work, "checkout", "-q", "-b", "b")
    commit(work, "a.txt", "one\n", "first")
    run(work, "push", "-q", "origin", "b")
    return remote, work


def redact(text: str, root: Path) -> str:
    text = text.replace(str(root), "/srv/git")
    return re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", text)


def write(name: str, command: str, result: subprocess.CompletedProcess[str], root: Path) -> None:
    version = subprocess.run(
        ["git", "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    body = (
        f"# tool: {version}\n# command: {command} (LC_ALL=C)\n# returncode: {result.returncode}\n"
        f"--- stdout\n{redact(result.stdout, root)}--- stderr\n{redact(result.stderr, root)}"
    )
    (OUT / f"{name}.txt").write_text(body)


def push_fixtures(root: Path) -> None:
    remote, work = clone_with_branch(root, "stale")
    last = run(work, "rev-parse", "b").stdout.strip()
    other = root / "stale-other"
    run(root, "clone", "-q", "-b", "b", str(remote), str(other))
    commit(other, "a.txt", "theirs\n", "theirs")
    run(other, "push", "-q", "origin", "b")
    run(work, "commit", "-q", "--amend", "-m", "first, reworded")
    result = run(
        work, "push", "--porcelain", f"--force-with-lease=b:{last}", "origin", "b", check=False
    )
    write(
        "push_stale_lease",
        "git push --porcelain --force-with-lease=b:<sha> origin b",
        result,
        root,
    )

    remote, work = clone_with_branch(root, "hook")
    hook = remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'commit message must reference a ticket' >&2\nexit 1\n")
    hook.chmod(0o755)
    commit(work, "a.txt", "two\n", "second")
    result = run(work, "push", "--porcelain", "origin", "b", check=False)
    write(
        "push_hook_declined",
        "git push --porcelain origin b, remote with a pre-receive hook that exits 1",
        result,
        root,
    )

    remote, work = clone_with_branch(root, "protected")
    hook = remote / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\n"
        "echo 'error: GH006: Protected branch update failed for refs/heads/b.' >&2\n"
        "echo 'error: Cannot force-push to this branch' >&2\n"
        "exit 1\n"
    )
    hook.chmod(0o755)
    run(work, "commit", "-q", "--amend", "-m", "first, reworded")
    result = run(work, "push", "--porcelain", "--force", "origin", "b", check=False)
    write(
        "push_protected_branch",
        "git push --porcelain --force origin b, remote hook that refuses it like branch protection",
        result,
        root,
    )

    remote, work = clone_with_branch(root, "nff")
    other = root / "nff-other"
    run(root, "clone", "-q", "-b", "b", str(remote), str(other))
    commit(other, "a.txt", "theirs\n", "theirs")
    run(other, "push", "-q", "origin", "b")
    commit(work, "a.txt", "mine\n", "mine")
    result = run(work, "push", "--porcelain", "origin", "b", check=False)
    write(
        "push_non_fast_forward",
        "git push --porcelain origin b, remote branch has a commit the local one lacks",
        result,
        root,
    )

    _, work = clone_with_branch(root, "gone")
    run(work, "remote", "set-url", "origin", str(root / "nowhere.git"))
    commit(work, "a.txt", "two\n", "second")
    result = run(work, "push", "--porcelain", "origin", "b", check=False)
    write(
        "push_unrelated_failure",
        "git push --porcelain origin b, remote that does not exist",
        result,
        root,
    )


def rebase_fixtures(root: Path) -> None:
    repo = root / "rerere"
    run(root, "init", "-q", "-b", "main", str(repo))
    run(repo, "config", "rerere.enabled", "true")
    old = commit(repo, "conflicted.py", "base\n", "base")
    run(repo, "checkout", "-q", "-b", "spec/c/2")
    original = commit(repo, "conflicted.py", "feature\n", "add feature")
    run(repo, "checkout", "-q", "main")
    commit(repo, "conflicted.py", "main\n", "main moves")
    command = (
        "git -c rerere.enabled=true -c rerere.autoUpdate=false rebase --onto main <old> spec/c/2"
    )
    args = (
        "-c",
        "rerere.enabled=true",
        "-c",
        "rerere.autoUpdate=false",
        "rebase",
        "--onto",
        "main",
        old,
        "spec/c/2",
    )

    first = run(repo, *args, check=False)
    write("rebase_rerere_no_replay", command, first, root)

    (repo / "conflicted.py").write_text("both\n")
    run(repo, "add", "conflicted.py")
    run(repo, "rebase", "--continue")
    run(repo, "checkout", "-q", "main")
    run(repo, "branch", "-f", "spec/c/2", original)

    second = run(repo, *args, check=False)
    write("rebase_rerere_replay", command, second, root)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        push_fixtures(root)
        rebase_fixtures(root)


if __name__ == "__main__":
    main()
