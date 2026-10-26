# Proposal

## Why

The tier-2 acceptance test of `local-forge` (`test_a_unit_is_reviewed_in_the_ui_reworked_approved_and_merged_by_a_person_with_git`,
run in the worktree of `spec/local-forge/3`) failed with `AgentPushed: spec/add-marker/1 on the remote
moved from be1689180 to b694104ac during an agent step, to a commit made in this worktree; the pipeline
is the only pusher, so the agent pushed it`. It is a false positive: the agent committed and ran ruff and
pytest, and its last words were that it was committing with no push.

`run_agent`'s wrapper in `pipeline/wiring.py` reads `remote_head` before the step and `_agent_pushed`
reads it after; it raises `AgentPushed` when the two differ and the later head is an ancestor of the
worktree's HEAD. `remote_head` in `pipeline/restack.py` returns, when the repo has no `origin`, the
local `refs/heads/<branch>` head (added by `local-forge` group 2). With no origin the "remote head" is
therefore the worktree's own branch: any commit the agent makes moves it, to a commit that is trivially
an ancestor of HEAD. The unit tests for the guard all use a bare remote with an origin; none covers no
origin.

## What Changes

- The agent-pushed guard does nothing when the repo has no `origin`.
- With an origin, nothing changes: a push to the branch during an agent step still fails the step.
- A test covers the no-origin case with a stand-in agent that commits and does not push.
