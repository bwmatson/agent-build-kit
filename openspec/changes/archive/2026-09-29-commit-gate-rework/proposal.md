# Proposal

## Why

Every commit a unit makes goes through the target repo's own pre-commit gate.
When that gate rejects the commit, the build raises and the unit is `failed` —
the agent is never told, and a person has to read a service log to find out
that a lint rule ended an otherwise finished piece of work.

That is not a hypothetical cost. A unit wrote its thirteen tests, confirmed each
failed for the right reason, and was ended by `E501 Line too long (105 > 100)`.
The formatter, running later in the same hook chain, had already rewrapped that
line: the file on disk was clean, and the verdict that killed the unit was
already stale when it was reported. Recovering it by hand took a minute;
rebuilding it would have cost an Opus run.

The current behaviour is the second version of this code path, not the first.
`build_commit` used to report a rejected commit as "the model produced nothing",
which was worse, and the comment there says so. Raising was the right fix for
the misdiagnosis. It is not the right end state: the gate's output is the most
actionable feedback in the whole pipeline, and it is the one piece the agent
never sees.

Two rejections are also being treated as one. A gate that *modified* the files —
a formatter doing its job — is self-healing: committing again succeeds, because
the fix is already on disk. A gate that *found* something needs the author.
Retrying the first costs nothing; only the second is worth an agent call.

## What Changes

- **A rejected commit becomes a fix round, not the end of the unit.** The gate's
  own output goes back to the agent, which fixes what it names, and the commit is
  attempted again.
- **A gate that only rewrote files is retried directly**, without spending an
  agent call, because re-running the commit is the whole fix.
- **The rounds are bounded.** After a small number of attempts the unit fails as
  it does today, with the gate's last output in its history so the reason is on
  the record rather than in a log.
- **The gate is never bypassed.** No `--no-verify`, no skipping hooks, no
  committing "around" a rejection: the gate's verdict is the thing being
  satisfied, not an obstacle.

## Impact

- **agent-build-kit** only, in the commit step every build and rework shares.
- Units that fail today for one fixable nit will instead land. Units that are
  genuinely broken fail the same way, a few minutes later, with a better record
  of why.
