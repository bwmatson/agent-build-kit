"""The dry-guidance scratch app, its seeded branches and its recording agent wrapper work.

Run with no agent, so a broken fixture fails here in seconds and not at the end of a billed
run: the app's own tests pass under the profile's unit-test commands and leave git nothing to
report, each seeded branch holds the two commits it should and passes the unit-test commands,
and the wrapper that records the client's lines changes nothing on the wire.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_build_kit import profiles
from tests.acp_recorder import wrapped
from tests.claude_recorder import wrapped as claude_wrapped
from tests.dry_checks import (
    claude_session_prompts,
    definitions,
    diff_definitions,
    is_copy,
    literal_count,
)
from tests.dry_scratch import SQUEEZE, dry_app, seed_branch
from tests.factories import git

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]


def unit_test(root: Path, base: str, files: list[str]) -> None:
    """The python-uv profile's own commands, as a unit's checks run them."""
    profile = profiles.get("python-uv")
    for command in [
        profile.lint_command(base),
        *profile.test_commands(root, files, root_extras=[]),
    ]:
        result = subprocess.run(command, cwd=root, capture_output=True, text=True)
        assert result.returncode == 0, f"{command}\n{result.stdout}\n{result.stderr}"


def test_the_dry_apps_own_tests_pass_under_the_profiles_unit_test_commands(tmp_path: Path) -> None:
    app = dry_app(tmp_path / "app")

    unit_test(app, "HEAD~1", ["tests/test_text.py"])


def test_the_dry_app_leaves_nothing_for_git_to_report_while_its_lock_exists(tmp_path: Path) -> None:
    app = dry_app(tmp_path / "app")

    unit_test(app, "HEAD~1", ["tests/test_text.py"])

    assert (app / "uv.lock").exists()
    status = git(app, "status", "--porcelain", "--untracked-files=all")
    assert status == ""


def test_the_dry_app_holds_the_helper_once_with_its_distinctive_body(tmp_path: Path) -> None:
    app = dry_app(tmp_path / "app")

    held = [d for d in definitions(app, "main") if d.name == "slugify"]

    assert [d.path for d in held] == ["src/app/text.py"]
    assert literal_count(app, "main", SQUEEZE) == 1


@pytest.mark.parametrize("duplicate", [True, False], ids=["duplicate", "clean"])
def test_a_seeded_branch_holds_a_tests_commit_then_an_implementation_commit_and_passes_unit_test(
    tmp_path: Path, duplicate: bool
) -> None:
    app = dry_app(tmp_path / "app")
    branch = seed_branch(app, "feature", duplicate=duplicate)

    assert branch == "spec/feature/1"
    commits = git(app, "log", "--reverse", "--format=%H", f"main..{branch}").split()
    assert len(commits) == 2
    tests_commit = git(app, "show", "--name-only", "--format=", commits[0]).split()
    code_commit = git(app, "show", "--name-only", "--format=", commits[1]).split()
    assert tests_commit and all(name.startswith("tests/") for name in tests_commit)
    assert any(name.startswith("src/") for name in code_commit)
    # Git is left on `main`, so a worktree can be prepared on the branch.
    assert git(app, "rev-parse", "--abbrev-ref", "HEAD") == "main"

    checkout = tmp_path / "checkout"
    git(app, "worktree", "add", "-q", str(checkout), branch)
    unit_test(checkout, "main", [name for name in tests_commit if name.endswith(".py")])


def test_the_seeded_duplicate_repeats_the_helper_and_the_clean_branch_calls_it(
    tmp_path: Path,
) -> None:
    app = dry_app(tmp_path / "app")
    seed_branch(app, "feature", duplicate=True)
    seed_branch(app, "clean", duplicate=False)
    original = next(d for d in definitions(app, "main") if d.name == "slugify")

    seeded = diff_definitions(app, "main", "spec/feature/1").added
    clean = diff_definitions(app, "main", "spec/clean/1").added

    assert [d.name for d in seeded if is_copy(original.source, d.source)]
    assert clean
    assert not [d for d in clean if is_copy(original.source, d.source)]
    assert literal_count(app, "spec/feature/1", SQUEEZE) == 2
    assert literal_count(app, "spec/clean/1", SQUEEZE) == 1


# What the real agent sends and answers is JSON-RPC, one message to a line.
CLIENT_LINES = [
    '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":1}}',
    '{"jsonrpc":"2.0","id":1,"method":"session/prompt","params":{"sessionId":"s","prompt":'
    '[{"type":"text","text":"héllo \\"quoted\\""}]}}',
]

# A stand-in agent: answers every line with a result naming it, and writes a line of its own
# first, as an agent that notifies before it answers.
AGENT = (
    "import sys\n"
    "for line in sys.stdin:\n"
    '    sys.stdout.write(\'{"jsonrpc":"2.0","method":"session/update"}\\n\')\n'
    '    sys.stdout.write(\'{"jsonrpc":"2.0","result":\' + repr(line.strip()) + \'}\\n\')\n'
    "    sys.stdout.flush()\n"
)


def test_the_recording_wrapper_passes_lines_both_ways_unchanged_and_records_only_the_clients(
    tmp_path: Path,
) -> None:
    record = tmp_path / "record.jsonl"
    command = wrapped(record, [sys.executable, "-c", AGENT])

    run = subprocess.run(
        command,
        input="".join(line + "\n" for line in CLIENT_LINES),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert run.returncode == 0, run.stderr
    expected = "".join(
        '{"jsonrpc":"2.0","method":"session/update"}\n'
        '{"jsonrpc":"2.0","result":' + repr(line) + "}\n"
        for line in CLIENT_LINES
    )
    assert run.stdout == expected
    assert record.read_text().splitlines() == CLIENT_LINES


DYING_AGENT = (
    'import sys\nsys.stdout.write(\'{"error":"auth"}\\n\')\nsys.stdout.flush()\nsys.exit(3)\n'
)


def test_the_recording_wrapper_ends_with_the_agents_code_when_the_agent_dies_first(
    tmp_path: Path,
) -> None:
    wrapper = subprocess.Popen(
        wrapped(tmp_path / "record.jsonl", [sys.executable, "-c", DYING_AGENT]),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert wrapper.stdin is not None and wrapper.stdout is not None
    try:
        # The client's stdin stays open, as a client waiting for a reply keeps it.
        assert wrapper.wait(timeout=10) == 3
        assert wrapper.stdout.read() == '{"error":"auth"}\n'
    finally:
        wrapper.kill()
        wrapper.stdin.close()
        wrapper.stdout.close()


# A stand-in for `claude`: says its own process id, its arguments and what it read on stdin.
STUB_CLAUDE = """\
#!/bin/sh
echo "pid $$"
echo "args $*"
cat
"""
STUB_CLAUDE_STATUS = """\
#!/bin/sh
echo "args $*"
"""


def stub_claude(tmp_path: Path, script: str) -> Path:
    stub = tmp_path / "claude"
    stub.write_text(script)
    stub.chmod(0o755)
    return stub


def run_the_claude_wrapper(tmp_path: Path, args: list[str], prompt: str) -> tuple[int, str, Path]:
    record = tmp_path / "claude-runs.txt"
    process = subprocess.Popen(
        [*claude_wrapped(record, [str(stub_claude(tmp_path, STUB_CLAUDE))]), *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    output, _ = process.communicate(prompt, timeout=60)
    return process.pid, output, record


def test_the_claude_wrapper_records_the_prompt_and_arguments_and_passes_both_on_unchanged(
    tmp_path: Path,
) -> None:
    args = ["-p", "--resume", "session-1", "--model", "haiku"]
    prompt = "Work ONLY the test tasks.\nSecond line, with 'quotes' and \"more\".\n"

    _, output, record = run_the_claude_wrapper(tmp_path, args, prompt)

    assert f"args {' '.join(args)}\n" in output
    assert output.endswith(prompt)
    [run] = claude_session_prompts(record)
    assert run.text == prompt
    assert run.resume == "session-1"


def test_the_claude_wrapper_leaves_no_process_of_its_own_once_claude_runs(tmp_path: Path) -> None:
    pid, output, _ = run_the_claude_wrapper(tmp_path, ["-p"], "a prompt\n")

    # It exec'd: the process the stub ran in is the one the wrapper was started as.
    assert output.splitlines()[0] == f"pid {pid}"


def test_the_claude_wrapper_leaves_the_input_of_a_run_that_is_not_a_prompt_alone(
    tmp_path: Path,
) -> None:
    record = tmp_path / "claude-runs.txt"

    # Standard input is never closed here: the wrapper must not wait on it.
    process = subprocess.Popen(
        [
            *claude_wrapped(record, [str(stub_claude(tmp_path, STUB_CLAUDE_STATUS))]),
            "auth",
            "status",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None and process.stdout is not None
    try:
        assert process.wait(timeout=10) == 0
        assert process.stdout.read() == "args auth status\n"
    finally:
        process.kill()
        process.stdin.close()
        process.stdout.close()
    assert claude_session_prompts(record) == []
