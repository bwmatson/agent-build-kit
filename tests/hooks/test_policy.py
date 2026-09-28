"""The PreToolUse hook that enforces the command policy.

`command_policy` decides; this is what makes the decision reach Claude Code.
It reads the hook payload on stdin and answers on stdout, per the documented
contract.

Two properties matter more than the mapping itself:

- **It fails closed.** Claude Code treats a hook that errors, or prints
  something that isn't JSON, as "no objection" and lets the call through. For
  a policy hook that is the wrong default: a bug here would quietly re-enable
  `gh pr merge`. So every unexpected path denies.
- **Its stdout is JSON and nothing else.** Any stray output — a warning, a
  traceback, a print left behind — makes the whole thing plain text, and the
  decision is silently discarded.
"""

import json
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.hooks.policy import decide

# tests/ mirrors the source layout, so the repo root is two levels up.
REPO_ROOT = Path(__file__).resolve().parents[2]


def payload(command: str, *, tool: str = "Bash", cwd: str = "/tmp") -> dict:
    return {
        "session_id": "s1",
        "cwd": cwd,
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": {"command": command},
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "spec/change/1"], cwd=tmp_path, check=True)
    return tmp_path


def test_a_denied_command_is_refused_with_a_reason(repo: Path) -> None:
    answer = decide(payload("gh pr merge 4", cwd=str(repo)))

    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "merge" in answer["hookSpecificOutput"]["permissionDecisionReason"]


def test_the_reason_is_the_policy_reason_not_a_generic_refusal(repo: Path) -> None:
    """A refusal the agent can't act on becomes a retry loop, so the advice
    from command_policy has to survive the trip."""
    answer = decide(payload("git push --force origin spec/change/1", cwd=str(repo)))

    assert answer is not None
    reason = answer["hookSpecificOutput"]["permissionDecisionReason"]
    assert "--force-with-lease=" in reason


def test_an_allowed_command_produces_no_decision(repo: Path) -> None:
    """Staying silent leaves the normal permission flow in charge; answering
    "allow" would override the user's own deny rules."""
    assert decide(payload("git status", cwd=str(repo))) is None


def edit(target: Path | str, *, cwd: Path | str) -> dict:
    return {"tool_name": "Edit", "cwd": str(cwd), "tool_input": {"file_path": str(target)}}


def test_a_file_write_in_the_worktree_is_not_this_hook_s_business(repo: Path) -> None:
    assert decide(edit(repo / "src" / "x.py", cwd=repo)) is None


def test_a_file_write_from_a_subdirectory_of_the_worktree_is_allowed(repo: Path) -> None:
    (repo / "pkg").mkdir()
    assert decide(edit(repo / "README.md", cwd=repo / "pkg")) is None


def test_a_file_write_outside_the_worktree_is_refused(repo: Path, tmp_path_factory) -> None:
    """An agent can edit a file in the user's own checkout of another repo
    from its worktree. Nothing commits it, and it sits uncommitted until
    someone notices. A unit's changes belong in its own worktree, where
    review and the PR see them."""
    other_checkout = tmp_path_factory.mktemp("platform")
    subprocess.run(["git", "init", "-q"], cwd=other_checkout, check=True)

    answer = decide(edit(other_checkout / "NOTES.md", cwd=repo))

    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
    reason = answer["hookSpecificOutput"]["permissionDecisionReason"]
    assert str(repo) in reason
    assert "BLOCKED:" in reason


def test_a_relative_path_is_read_against_the_run_s_directory(tmp_path: Path) -> None:
    worktree, neighbour = tmp_path / "worktree", tmp_path / "neighbour"
    for checkout in (worktree, neighbour):
        checkout.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)

    escaped = decide(edit("../neighbour/x.py", cwd=worktree))
    assert escaped is not None
    assert escaped["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert decide(edit("src/x.py", cwd=worktree)) is None


def test_a_scratch_file_in_the_temp_directory_is_allowed(repo: Path) -> None:
    import tempfile

    assert decide(edit(Path(tempfile.gettempdir()) / "scratch.py", cwd=repo)) is None


def test_the_temp_directory_is_no_way_into_another_checkout(repo: Path, tmp_path_factory) -> None:
    # Another repo's checkout that happens to live under the temp directory
    # (a worktree of its own, say) is still another checkout.
    elsewhere = tmp_path_factory.mktemp("other-worktree")
    subprocess.run(["git", "init", "-q"], cwd=elsewhere, check=True)

    answer = decide(edit(elsewhere / "new" / "file.py", cwd=repo))

    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_a_file_write_with_no_worktree_to_fence_it_in_is_refused(tmp_path: Path) -> None:
    # No cwd, or a cwd outside any git checkout: there is no worktree to hold
    # the write to, and guessing "allow" is how a guard gets bypassed.
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    for payload_ in (
        {"tool_name": "Write", "tool_input": {"file_path": str(not_a_repo / "x")}},
        edit(not_a_repo / "x", cwd=not_a_repo),
    ):
        answer = decide(payload_)
        assert answer is not None
        assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_the_specs_are_read_only_for_build_agents(tmp_path: Path) -> None:
    """A build agent once ticked its own tasks, marking a group done before
    review had seen it. The pipeline ticks them, once a unit has passed
    review; the hook is told where the specs are when it is registered."""
    specs = tmp_path / "openspec"
    tasks = specs / "changes" / "some-change" / "tasks.md"
    # from inside a checkout, so it's the specs rule refusing, not the fence
    answer = decide(edit(tasks, cwd=REPO_ROOT), specs=specs)

    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "specs" in answer["hookSpecificOutput"]["permissionDecisionReason"]


def test_a_file_write_it_cannot_read_is_refused() -> None:
    """Failing open is the danger for a policy hook."""
    answer = decide({"tool_name": "Write", "tool_input": {}})

    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_reads_are_not_this_hook_s_business(repo: Path) -> None:
    assert decide(payload("anything", tool="Read", cwd=str(repo))) is None


def test_the_branch_comes_from_the_working_directory(repo: Path) -> None:
    """The policy is branch-scoped: force-pushing is allowed on spec/ branches
    and nowhere else, so the hook has to know where it is."""
    subprocess.run(["git", "checkout", "-q", "-b", "main"], cwd=repo, check=True)

    answer = decide(payload("git push --force-with-lease=main:abc origin main", cwd=str(repo)))

    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_an_unknown_working_directory_denies_rather_than_allows(tmp_path: Path) -> None:
    """Not a git repo, or a path that vanished: without a branch the policy
    can't be applied, and guessing "allow" is how a guard gets bypassed."""
    answer = decide(payload("git push --force origin whatever", cwd=str(tmp_path / "gone")))

    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_a_malformed_payload_denies(repo: Path) -> None:
    """A changed payload shape must not silently disable the policy."""
    answer = decide({"tool_name": "Bash"})

    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_the_script_prints_only_json(repo: Path) -> None:
    """Claude Code parses stdout as a whole: one stray line of output and the
    decision is discarded as plain text."""
    result = subprocess.run(
        ["python", "-m", "agent_build_kit.hooks.policy"],
        input=json.dumps(payload("gh pr merge 4", cwd=str(repo))),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert parsed["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_the_script_says_nothing_when_it_has_no_objection(repo: Path) -> None:
    result = subprocess.run(
        ["python", "-m", "agent_build_kit.hooks.policy"],
        input=json.dumps(payload("git status", cwd=str(repo))),
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert result.stdout.strip() == ""
    assert result.returncode == 0


def test_garbage_on_stdin_denies_rather_than_crashing(repo: Path) -> None:
    """A crash prints a traceback, which Claude Code reads as plain text and
    ignores — so the call would go through."""
    result = subprocess.run(
        ["python", "-m", "agent_build_kit.hooks.policy"],
        input="not json at all",
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_the_settings_register_the_hook_for_bash_and_file_writes() -> None:
    """Every Bash call and every file write is policed. Not reads: a matcher
    that included them would run the hook on every file an agent opens."""
    from agent_build_kit.hooks.policy import hook_settings

    settings = hook_settings(Path("/repo"))
    entry = settings["hooks"]["PreToolUse"][0]

    assert entry["matcher"] == "Bash|Edit|Write|MultiEdit|NotebookEdit"
    assert "agent_build_kit.hooks.policy" in entry["hooks"][0]["command"]


def test_the_settings_are_passed_per_run_not_written_globally() -> None:
    """The policy belongs to the unattended pipeline. Writing it into
    ~/.claude/settings.json would also deny the user's own `gh pr merge`."""
    from agent_build_kit.hooks.policy import hook_settings

    assert "python" in hook_settings(Path("/repo"))["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
