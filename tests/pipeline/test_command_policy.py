"""What the unattended agent is allowed to run.

These are technical controls, not documented intentions
(docs/architecture.md). The prompts can ask for good behaviour;
this is what makes the bad cases impossible.

Two of the rules are subtle enough to be worth stating here:

- **`--force` is denied but `--force-with-lease=<ref>:<sha>` is allowed.**
  Restacking rewrites history, so force-pushing is unavoidable. A substring
  match on "--force" would block the safe form too, and matching on
  "--force-with-lease" alone would allow the *bare* form, which is unsafe —
  verified: git-branchless's own submit fetches first, advancing the ref the
  bare lease compares against, and overwrote a concurrent commit.
- **Denials are scoped to `spec/` branches** for the force-push exception, so
  the agent can never rewrite a branch a human owns.
"""

import pytest

from agent_build_kit.pipeline.command_policy import Verdict, check_command

SPEC = "spec/add-marker/1-unit"


def allowed(command: str, branch: str = SPEC) -> bool:
    return check_command(command, branch=branch).allowed


def test_ordinary_work_is_allowed() -> None:
    for command in [
        "git status",
        "git add -A",
        'git commit -m "test: covers it"',
        "git move -s abc -d main",
        "git restack",
        "git sl",
        "uv run pytest",
        "gh pr create --base main --head spec/x/1",
        "gh pr comment 4 --body hi",
    ]:
        assert allowed(command), command


def test_the_agent_cannot_merge_its_own_pr() -> None:
    """The one rule the whole review model rests on."""
    assert not allowed("gh pr merge 4 --squash")
    assert not allowed("gh  pr   merge 4")


def test_bare_force_push_is_denied() -> None:
    assert not allowed("git push --force origin spec/x/1")
    assert not allowed("git push -f origin spec/x/1")


def test_leased_force_push_to_a_spec_branch_is_allowed() -> None:
    assert allowed("git push --force-with-lease=spec/x/1:abc123 origin spec/x/1")
    assert allowed("git fetch && git push --force-with-lease --force-if-includes origin spec/x/1")


def test_a_bare_lease_without_force_if_includes_is_denied() -> None:
    """The failure mode verified against git-branchless: a bare lease compares
    against a remote-tracking ref that a fetch in the same run may have just
    advanced, so it can overwrite a commit the user pushed."""
    verdict = check_command("git push --force-with-lease origin spec/x/1", branch=SPEC)

    assert not verdict.allowed
    assert "lease" in verdict.reason


def test_force_pushing_a_branch_the_agent_does_not_own_is_denied() -> None:
    verdict = check_command("git push --force-with-lease=main:abc origin main", branch="main")

    assert not verdict.allowed


@pytest.mark.parametrize("command", ["git push origin main", "git push --set-upstream origin main"])
def test_pushing_to_main_is_denied(command: str) -> None:
    """Units land through PRs. A direct push to main would bypass review
    entirely, which is the one thing the whole design guarantees against."""
    assert not allowed(command, branch="main")


def test_amending_a_unit_branch_is_denied() -> None:
    """An amend can fold the implementation into the tests commit, erasing the
    evidence that the tests ever failed (§2.2)."""
    assert not allowed("git commit --amend --no-edit")
    assert not allowed("git amend")


def test_the_commit_gate_cannot_be_skipped() -> None:
    """The repo's pre-commit hooks are why the pipeline may push unattended.
    Every way of committing without them is refused, however it is spelled."""
    for command in [
        "git commit --no-verify -m x",
        "git commit --no-veri -m x",
        "git commit -n -m x",
        "git commit -anm x",
        "git add -A && git commit -qn -m x",
        "SKIP=ruff git commit -m x",
        "env SKIP=ruff,pyrefly git commit -m x",
        "HUSKY=0 git commit -m x",
        "export SKIP=ruff",
        "git -c core.hooksPath=/dev/null commit -m x",
        "git -C . -c core.hooksPath=/tmp/none commit -m x",
        "git config core.hooksPath /dev/null",
        "git config core.hookspath /dev/null",
    ]:
        verdict = check_command(command, branch=SPEC)
        assert not verdict.allowed, command
        assert "gate" in verdict.reason


def test_a_commit_that_runs_the_gate_is_not_mistaken_for_one_that_skips_it() -> None:
    for command in [
        'git commit -m "-n is not a flag here"',
        "git commit -m -n",
        "git commit -mn",
        "git commit -q -m x",
        "git log -n 3",
        'git commit -m "SKIP=ruff is refused"',
        "echo SKIP=ruff",
    ]:
        assert allowed(command), command


def test_destructive_git_is_denied() -> None:
    for command in [
        "git reset --hard origin/main",
        "git clean -fdx",
        "git branch -D spec/x/1",
        "rm -rf src",
    ]:
        assert not allowed(command), command


def test_a_denial_says_what_to_do_instead() -> None:
    """A refusal the agent can't act on just becomes a retry loop."""
    verdict = check_command("git push --force origin spec/x/1", branch=SPEC)

    assert isinstance(verdict, Verdict)
    assert "--force-with-lease=" in verdict.reason


def test_commands_are_checked_per_segment() -> None:
    """A denied command hidden behind && or ; is still a denied command."""
    assert not allowed("git status && gh pr merge 4")
    assert not allowed("echo hi; git push --force origin spec/x/1")
    assert not allowed("git status | xargs gh pr merge")


def test_a_substring_match_does_not_deny_innocent_commands() -> None:
    """`gh pr merge` is denied; a branch or message mentioning it is not."""
    assert allowed('git commit -m "document how gh pr merge is denied"')
    assert allowed("gh pr view 4 --json mergeable")
