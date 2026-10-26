# Tasks

Acceptance: none — this is the pipeline's own commit step, with no surface a
consumer drives; what proves it is a tier-1 test whose gate rejects on the first
call and accepts on the second, and one whose gate never accepts.

## 1. [agent-build-kit] [tier1] A rejected commit goes back to its author

Done when a gate that rewrote the files costs nothing, a gate that found
something reaches the agent that wrote the work, the attempts are bounded, and no
path commits without the gate.

- [x] 1.1 Test: a gate that rejects once and accepts on the next attempt results
      in one commit, no agent call, and no failure reported.
- [x] 1.2 Test: a gate that keeps rejecting until the work changes results in the
      agent being given the gate's own output — the file, line and rule as the
      gate printed them — and a commit afterwards.
- [x] 1.3 Test: a gate that never accepts fails the unit after the fixed number
      of attempts, and the gate's last output is on the unit's record.
- [x] 1.4 Test: no attempt passes a verification-skipping flag, and no attempt
      commits a narrowed set of paths; the commit count contract is unchanged —
      nothing staged is zero, a made commit is one.
- [x] 1.5 Implement it in the shared commit step: retry once, then a bounded fix
      round carrying the gate's output, in the same worktree and under the same
      tool policy as the build run.
- [x] 1.6 Record the gate's final output on the unit when it does fail, and say
      in `docs/architecture.md`, beside the push gate, that a rejected commit is
      a fix round before it is a failure.
