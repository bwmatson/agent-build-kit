# Design

## Where

`<worktree>/.abk/out/<run>/`, one folder per agent run, created when the run starts (the
run id is the one its run log already carries). A worktree's git directory has its own
exclude file; the pipeline appends `.abk/` to it (idempotently, when the worktree is
created) so nothing under it is untracked-visible, and the commit path and the leftover
commit never see it. The path is told to the agent in the prompt and exported as `ABK_OUT`
in that agent's environment, so commands use `$ABK_OUT/<name>.log` without a path.

## Not shared

The folder is the run's alone. A rework or a review starts in a new folder, so it cannot
find or read the builder's files, and the prompts tell each agent to run the commands it
needs itself and to read only its own files. Nothing in the pipeline passes an agent's
command output to another agent: not the builder's suite result to the reviewer, not an
agent's run to tier 1. Tier 1 and every later agent run their own commands.

## The convention text

Packaged prompt text shared by the build, rework and resolver prompts (one source, like
the changelog convention):

- run long commands as `<command> > "$ABK_OUT/<name>.log" 2>&1; echo $? >
  "$ABK_OUT/<name>.exit"`, then read the file; use `tail -n`, `grep -n`, `sed -n` on it;
- never rerun a command to see more of its output; if the file is not enough, the command
  failed to produce what is needed and a rerun with a narrower scope is justified;
- run the full suite once after the round's last edit, read its result from the file, and
  after a fix run only the tests that failed;
- name files by what produced them (`suite`, `lint`, `types`), so a later read finds them.

## Policy and permissions

`hooks/policy.py` and the ACP deny list already restrict what a shell write may touch.
Redirecting into `$ABK_OUT` is allowed there and nowhere else. Reading uses the existing
read tools. The policy tests gain cases: a redirect into the folder is allowed; a redirect
anywhere else in the worktree, or `>>` onto a tracked file, is refused as before.

## Cleanup

A run's folder is removed when the run ends, whatever its outcome (and any left by a
killed run is removed when its unit next starts a run, or on archive). While a run goes,
a file beyond a size cap is truncated to its tail with a marker, so one runaway command
cannot fill the disk.

## Tier 1 is unchanged

The pipeline's own tier 1 still runs the suite before review. This change removes an
agent's repeats within its own run, not that run, and it deliberately does not let tier 1,
a reviewer or a later agent reuse another agent's output: each runs the command itself.

## Out of scope

Sharing command output between agents or with tier 1 (rejected: each agent runs its own
commands); the ACP runtime's own output handling.
