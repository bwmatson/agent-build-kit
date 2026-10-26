# Proposal

## Why

The implement track runs an agent in a fresh worktree of a code repo and tells
it to do two kinds of git work: branches, commits and pull requests for the code
repo, and one bookkeeping commit — its run log and the issue tracker — "directly
to the planning repo's default branch (the branch it's checked out on)".

One run went like this:

- The agent ran `git checkout -b <its feature branch>` while its shell was in
  the planning repo. The planning repo was now on a feature branch named for
  another repo's work.
- It noticed the branch "didn't stick" in its worktree, pushed the code by
  refspec, and reported it as an environment quirk.
- Its bookkeeping commit, and the next two phases' commits, went onto the stray
  branch — which the prompt's "the branch it's checked out on" told them was
  correct.
- A later phase's agent repaired it by hand: a forced move of the default
  branch, a cherry-pick, and two `reset`s. One phase's run log was dropped by a
  reset and left uncommitted.
- The planning repo stayed on the stray branch until someone looked. The next
  track run would have switched it back; nothing in a tick checks.

Nothing was lost this time. But an agent was doing history surgery on the repo
that holds the pipeline's state, and the pipeline was reading and writing that
state on a branch nobody chose.

Two things made it possible. The agent is given git work in two repos and one
shell. And committing a run log is a fixed sequence that needs no judgement,
done by the one participant that can get it wrong.

## What Changes

- **The runner commits a phase's bookkeeping.** When a phase ends, the runner
  commits the run log and tracker changes to the planning repo's default branch
  and pushes. The agent writes the files and does not run git in the planning
  repo; the prompts say so.
- **The runner checks the planning repo after every phase.** If it is not on
  its default branch, or the default branch no longer contains the commit it was
  at when the phase began, the runner puts it back on the default branch,
  reports the phase as having moved it, and keeps the stray branch so nothing is
  discarded.
- **A tick checks too.** Before it reads or writes state, a tick confirms the
  planning repo is on its default branch, and restores it the same way if not.
- **The agent's git commands in the planning repo are refused** where the
  command policy can see them: creating or switching a branch, resetting, or
  moving a branch there.

## Impact

- **agent-build-kit** only: the track runner, the track prompts, the tick's
  start, and the command policy for track runs.
- A track's bookkeeping commit is made without an agent call.
