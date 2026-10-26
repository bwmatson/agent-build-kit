# Proposal

## Why

Agents run the whole test suite and the formatter with their output piped through `tail`
or `head`. When the part they needed was cut off, the only way to see more is to run the
command again. A suite run costs minutes, and two units run at once on one machine, so
runs compete. In one pass an agent waited about eleven minutes for the suite, found the
summary had been cut off, and started it again. The unit's own tier 1 then runs the suite
once more before review.

The cost is not the suite: it is repeating it to see output that was already produced.

## What Changes

- **A convention in the build, rework and resolver prompts.** A command whose output may be
  long or slow to produce (the test suite, a full lint, a build) is run with its output
  written to a file in the scratch folder, and the agent reads the file with `tail`,
  `grep` or `sed -n`. The agent never reruns a command only to see different lines of its
  output. The exit status is kept beside the output.
- **The scratch folder is ignored by git.** The pipeline creates it in each unit's worktree
  and excludes it through the worktree's local exclude file, so nothing in it can be added
  by an agent's `git add -A` or by the pipeline's own leftover commit, and no tracked
  ignore file changes.
- **Each agent run has its own folder, and its files are its own.** The scratch folder is
  per agent run (the build, a rework, a review, a resolver each get a fresh one). An agent
  runs every command itself and reads only its own files; the prompts say so, and the
  pipeline never hands one agent another's command output, including a reviewer the
  builder's test run and tier 1 the agent's.
- **It is cleaned up.** A run's folder is removed when the run ends, and old files are
  pruned while it runs, so a long unit does not fill the disk.
- **The tools allow it.** The command policy and the agent runtimes' permission lists allow
  writing to and reading from that folder by redirection, and still refuse writes elsewhere
  by shell.
- **The suite runs once per round, per agent.** The prompts say to run the full suite once after the
  last change of a round, to read the result from the file, and to run only the failing
  tests again after a fix.
