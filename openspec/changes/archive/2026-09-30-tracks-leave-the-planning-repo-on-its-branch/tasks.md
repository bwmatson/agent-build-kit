# Tasks

Acceptance: none — this is the pipeline's own bookkeeping, with no surface a
consumer drives; what proves it is tier-1 tests that run a phase with an agent
double against real git repos.

## 1. [agent-build-kit] [tier1] The runner commits a track's bookkeeping and keeps the planning repo on its branch

Done when a phase's planning-repo files are committed and pushed by the runner
with no agent call, a planning repo moved off its default branch by a phase is
put back with the stray branch kept and reported, a rewritten default branch
stops the run, a tick restores the default branch before it reads state, and a
track's agent is refused branch-changing git aimed at the planning repo.

- [x] 1.1 Test: a phase whose agent double writes a run log ends with one new
      commit on the planning repo's default branch containing it, and the agent
      double ran no git.
- [x] 1.2 Test: a push rejected because the remote moved is retried once after
      a fast-forward, and a second rejection is reported with the commit kept.
- [x] 1.3 Test: a phase whose agent double switches the planning repo to a new
      branch ends with the planning repo on its default branch, the phase's
      files committed there, the new branch still present, and the result
      naming it.
- [x] 1.4 Test: a phase whose agent double rewrites the default branch stops
      the run with a message saying so, and nothing is committed.
- [x] 1.5 Test: a tick started with the planning repo on another branch checks
      out the default branch and logs the branch it found before reading the
      store.
- [x] 1.6 Test: for a track run, the command policy refuses creating or
      switching a branch, a reset, a forced branch move and a cherry-pick that
      name the planning repo as target, and allows the same commands aimed at
      the code repo's worktree.
- [x] 1.7 Have the runner record the planning repo's branch and head before a
      phase, check them after, restore or stop as specified, then commit and
      push the phase's files.
- [x] 1.8 Add the default-branch check to the start of a tick.
- [x] 1.9 Give the command policy the planning repo's path for track runs and
      the refusals above.
- [x] 1.10 Remove the commit-and-push step from the track prompts and tell the
      agent the pipeline commits what it writes in the planning repo.
- [x] 1.11 Update `docs/tracks.md` and the track section of
      `docs/architecture.md`.
