# Design

## Where the work is today

`tracks/runner.py` runs each phase through the agent runtime with the code
repo as its working directory (and, for implement, a fresh worktree). At the
start of a run it brings the planning repo to its latest default branch. After
that, everything in the planning repo is the agent's: the prompts end with a
step that commits the run log and `tracked-issues.md` and pushes.

## The runner commits

The files a phase may change in the planning repo are known: its run log, the
tracker, and for recommend the recommendation files. When the phase's agent
returns, the runner stages the planning repo's changes under the state and
recommendation directories, commits with a message built from the phase, the
project and the run id, and pushes to the default branch. A push rejected
because the remote moved is retried once after a fast-forward pull; a second
failure is reported and leaves the commit local, as a failed push does today.

The prompts lose their commit step and gain one sentence: write the files, the
pipeline commits them. The implement prompt's tracker annotation that cites a
commit hash for the agent's own change is about the *code* repo's commit and
stays.

Nothing to commit is not an error — a phase that found nothing still writes a
run log, but a dry run does not.

## The check

Before a phase, the runner records the planning repo's branch and head. After:

- **on the default branch, head descends from the recorded one** — normal;
- **on another branch** — check the default branch out again. The stray branch
  is kept, not deleted: it may hold the only copy of something. The phase's
  result says the planning repo was moved, and names the branch;
- **default branch no longer contains the recorded head** — history was
  rewritten. The runner does not try to repair it; it stops the run and says
  so, because guessing at a repair is what the agent did.

Uncommitted changes carry across a checkout, so the bookkeeping files the agent
wrote are still there to commit once the branch is restored. If the checkout is
refused because a file would be overwritten, the run stops with that message.

A tick runs the first half of the same check at its start — the branch, not the
ancestry, since it has no earlier head to compare — and restores the default
branch before it reads the store.

## The policy

The command policy is given a branch for unit builds and refuses what would
damage it. For a track run it is additionally given the planning repo's path,
and refuses `git checkout -b`, `git switch -c`, `git branch -f`, `git reset`
and `git cherry-pick` when the command's target is that path — by `git -C`, or
by a `cd` into it earlier in the same command line.

This is the weaker half, and the design says so: the policy sees one command
line, not the shell's working directory, so a `cd` in one call followed by git
in the next is not caught. That is why the runner's check exists and is the
requirement; the policy only turns the common spelling into a refusal the agent
can read and correct at once.

## Testing

Through the runner's phase function with an agent double, against real git
repos from the suite's repo fixture:

- the double writes a run log and returns — the planning repo has one new
  commit on its default branch containing it;
- the double switches the planning repo to a new branch and writes a run log —
  afterwards the planning repo is on its default branch, the run log is
  committed there, the stray branch still exists and the result names it;
- the double rewrites the default branch — the run stops and nothing is
  committed.

And through the tick's entry point with the planning repo on another branch.
