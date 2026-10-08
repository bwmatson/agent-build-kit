"""Where a shell redirect may land (spec: command-output-to-files).

An agent writes long command output to its run's scratch folder, `$ABK_OUT`,
and nowhere else in the worktree: a redirect or an append onto a tracked file,
or onto any other path in the worktree, is a shell write the file tools'
fences would never have allowed.
"""

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.hooks.policy import decide
from agent_build_kit.pipeline.command_policy import Verdict, check_command

BRANCH = "spec/change/1"


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", BRANCH], cwd=tmp_path, check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("MARKER = None\n")
    (tmp_path / ".abk" / "out" / "run-1").mkdir(parents=True)
    return tmp_path


def verdict(command: str, worktree: Path) -> Verdict:
    return check_command(command, branch=BRANCH, worktree=worktree)


ALLOWED = [
    pytest.param('uv run pytest > "$ABK_OUT/suite.log" 2>&1', id="the-env-variable"),
    pytest.param('uv run pytest > "${ABK_OUT}/suite.log" 2>&1', id="braced"),
    pytest.param(
        'uv run pytest > "$ABK_OUT/suite.log" 2>&1; echo $? > "$ABK_OUT/suite.exit"',
        id="output-and-exit-status",
    ),
    pytest.param('uv run ruff check >> "$ABK_OUT/lint.log" 2>&1', id="an-append-to-the-folder"),
    pytest.param("uv run pytest 2>&1 | tail -n 40", id="a-pipe"),
    pytest.param("git status > /dev/null 2>&1", id="the-null-device"),
    pytest.param('echo x >| "$ABK_OUT/a.log"', id="clobber-into-the-folder"),
]


@pytest.mark.parametrize("command", ALLOWED)
def test_a_redirect_into_the_scratch_folder_or_to_no_file_is_allowed(
    command: str, worktree: Path
) -> None:
    assert verdict(command, worktree).allowed, command


def test_a_redirect_by_the_folder_s_real_path_is_allowed(worktree: Path) -> None:
    command = f"uv run pytest > {worktree}/.abk/out/run-1/suite.log 2>&1"

    assert verdict(command, worktree).allowed


def test_a_redirect_through_a_symlink_to_the_worktree_is_judged_by_where_it_lands(
    worktree: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    link = tmp_path_factory.mktemp("links") / "link"
    link.symlink_to(worktree)

    assert not verdict(f"echo x > {link}/src/app.py", worktree).allowed
    assert verdict(f"echo x > {link}/.abk/out/run-1/a.log", worktree).allowed


REFUSED = [
    pytest.param("echo x > src/app.py", id="overwrite-a-tracked-file"),
    pytest.param("echo x >> src/app.py", id="append-to-a-tracked-file"),
    pytest.param("echo x > notes.txt", id="a-new-file-in-the-worktree"),
    pytest.param("uv run pytest >src/app.py 2>&1", id="no-space-after-the-operator"),
    pytest.param("uv run pytest &> src/app.py", id="both-streams"),
    pytest.param("uv run pytest 2> src/app.py", id="the-error-stream"),
    pytest.param('echo x > "$ABK_OUT/../../src/app.py"', id="out-of-the-folder-by-dots"),
    pytest.param('echo x > "$ABK_OUT/../README.md"', id="up-from-the-folder"),
    pytest.param("echo x > .abk/other.log", id="beside-the-run-folders"),
    pytest.param("git status && echo x > src/app.py", id="behind-another-command"),
    pytest.param("echo x >| src/app.py", id="clobber-a-tracked-file"),
    pytest.param("uv run pytest 2>| src/app.py", id="clobber-by-the-error-stream"),
]


@pytest.mark.parametrize("command", REFUSED)
def test_a_redirect_onto_a_tracked_file_or_elsewhere_in_the_worktree_is_refused(
    command: str, worktree: Path
) -> None:
    answer = verdict(command, worktree)

    assert not answer.allowed, command
    assert answer.reason


def test_a_refusal_says_where_the_output_may_go(worktree: Path) -> None:
    assert "ABK_OUT" in verdict("echo x > src/app.py", worktree).reason


def payload(command: str, cwd: Path) -> dict:
    return {
        "session_id": "s1",
        "cwd": str(cwd),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def test_the_hook_allows_a_redirect_into_the_folder(worktree: Path) -> None:
    assert decide(payload('uv run pytest > "$ABK_OUT/suite.log" 2>&1', worktree)) is None


def test_the_hook_refuses_a_redirect_onto_a_tracked_file(worktree: Path) -> None:
    answer = decide(payload("echo x >> src/app.py", worktree))

    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "ABK_OUT" in answer["hookSpecificOutput"]["permissionDecisionReason"]


# --- what the rule reads as a redirect, and where the shell is ---------------------------


@pytest.mark.parametrize(
    "command",
    [
        pytest.param('grep ">" src/app.py', id="a-quoted-operator-in-double-quotes"),
        pytest.param("grep '>>' src/app.py", id="a-quoted-operator-in-single-quotes"),
        pytest.param('[ "$a" ">" "$b" ]', id="a-test-comparing-strings"),
        pytest.param('cd src && echo x > "$ABK_OUT/a.log"', id="the-folder-after-a-cd"),
    ],
)
def test_a_quoted_operator_is_no_redirect_and_the_folder_is_reachable_after_a_cd(
    command: str, worktree: Path
) -> None:
    assert verdict(command, worktree).allowed, command


@pytest.mark.parametrize(
    "command",
    [
        pytest.param('echo x > "notes.txt"', id="a-quoted-target"),
        pytest.param("echo x > 'src/app.py'", id="a-single-quoted-target"),
        pytest.param("cd src && echo x > ../README.md", id="up-from-a-cd"),
        pytest.param("cd src && echo x > app.py", id="a-file-in-the-directory-cd-ed-to"),
        pytest.param("cd .abk/out/run-1 && echo x > ../../../src/app.py", id="out-of-the-folder"),
        pytest.param("cd $SOMEWHERE && echo x > notes.txt", id="a-cd-to-a-variable"),
        pytest.param("cd - && echo x > notes.txt", id="a-cd-back"),
        pytest.param("cd && echo x > notes.txt", id="a-cd-home"),
        pytest.param("cd src; cd .. ; echo x > notes.txt", id="back-up-to-the-root"),
        pytest.param("echo x > '$ABK_OUT/a.log'", id="a-single-quoted-variable-is-literal"),
    ],
)
def test_a_redirect_is_read_where_the_shell_has_moved_to(command: str, worktree: Path) -> None:
    assert not verdict(command, worktree).allowed, command


# --- a target is the whole shell word, quoted and unquoted pieces together --------------


@pytest.mark.parametrize(
    "command",
    [
        pytest.param('echo x >"$ABK_OUT"/y', id="only-the-variable-quoted"),
        pytest.param('echo x > "$ABK_OUT/a"b.log', id="a-quoted-piece-then-text"),
        pytest.param('echo x > $ABK_OUT/"my log"', id="text-then-a-quoted-piece"),
    ],
)
def test_a_target_of_adjacent_quoted_pieces_is_read_as_one_word(
    command: str, worktree: Path
) -> None:
    assert verdict(command, worktree).allowed, command


def test_a_target_whose_first_piece_is_quoted_is_judged_whole(worktree: Path) -> None:
    refused = [
        f'echo x > "{worktree}"/README.md',
        'echo x > "$ABK_OUT/x"/../../../../src/app.py',
        "echo x > '$ABK_OUT'/y",
    ]

    for command in refused:
        assert not verdict(command, worktree).allowed, command


@pytest.mark.parametrize("command", ["pushd src && echo x > ../a.py", "popd && echo x > a.py"])
def test_a_redirect_after_pushd_or_popd_is_read_where_the_shell_has_moved_to(
    command: str, worktree: Path
) -> None:
    assert not verdict(command, worktree).allowed, command


def test_the_folder_is_reachable_after_a_pushd(worktree: Path) -> None:
    assert verdict('pushd src && echo x > "$ABK_OUT/a.log"', worktree).allowed
