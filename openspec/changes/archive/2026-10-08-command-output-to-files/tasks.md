# Tasks

Acceptance: none — worktree setup, prompts and policy inside the pipeline; tier-1 tests
over the exclude file, the prompts and the policy prove it.

## 1. [agent-build-kit] [tier1] Long output goes to an ignored file

Done when each agent run has its own ignored scratch folder, the prompts tell agents to
write long output there, read from it and run their own commands, the policy allows exactly
that redirect, no agent's output reaches another agent or tier 1, and the folder is cleaned
up when the run ends.

- [x] 1.1 Test: creating a worktree creates the scratch folder, appends its exclude line
      to the worktree's local exclude file once (a second creation does not duplicate it),
      and `git status` shows nothing for files in it; `git add -A` and the leftover commit
      stage nothing from it.
- [x] 1.2 Test: the build, rework and resolver prompts each carry the convention text
      (redirect to `$ABK_OUT`, read with tail or grep, do not rerun to see more, the suite
      once per round and only failing tests after a fix), and `ABK_OUT` is in the agent's
      environment.
- [x] 1.3 Test: the command policy allows a redirect into the scratch folder and refuses a
      redirect or an append onto a tracked file or anywhere else in the worktree; the ACP
      deny list agrees.
- [x] 1.4 Test: a run's folder is removed when the run ends in each outcome; a folder left
      by a killed run is removed when its unit next starts a run or its change is archived;
      a file past the size cap is truncated to its tail with a marker.
- [x] 1.5 Test: a build, then a rework, then a review of one unit each get a different,
      initially empty folder; a file the builder wrote is not present for the reviewer; the
      reviewer's prompt tells it to run its own commands; and no prompt or check passes one
      agent's command output to another agent or substitutes it for tier 1's own run.
- [x] 1.6 Add the per-run folder, the exclude line, the environment variable, the packaged
      convention text in the three prompts, the policy allowance, and the cleanup.
- [x] 1.7 Document it in `docs/architecture.md` and `docs/agent-runtimes.md` and add a
      changelog entry.
