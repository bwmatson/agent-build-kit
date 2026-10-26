# Proposal

## Why

The pipeline does not stop steps for usage, by design: `checkpoint()` asks whether it
may start the next step, and a step already running is left alone. Two ways a step can
end early are handled properly today:

- **A signal.** The unit stays `running`, and the next tick's `reclaim_stale` commits
  whatever the run left and requeues it at the step it was in.
- **A provider refusal the agent reports as an error.** It surfaces as a rate limit,
  the unit is recorded `planned` with a note beginning `paused before <step>`, the unit
  graph draws that as `paused: usage`, and the resume the pause schedules picks it up.

The gap is narrower and quieter: a refusal the agent reports by **finishing normally
having done nothing**. An agent told it is out of usage may exit cleanly, having said
so in prose, and the pipeline sees a run that succeeded and wrote nothing. Today every
empty step is failed, so the unit lands in the list a person is supposed to read, with
no record of why, and the evidence is in a service log that will have rotated by the
time anyone looks.

This has not been observed. It is worth closing anyway, because when it does happen the
cost is a rebuild and a false entry in the failed list, and the check that prevents it
is free: the pipeline already holds a recent usage reading.

## What Changes

- **An empty step is classified before it is failed.** If the account's usage window is
  exhausted when a step ends having written nothing, the unit is paused rather than
  failed: the same state, the same note wording and the same resume point as a stop
  between steps, so it renders as `paused: usage` and the existing resume picks it up.
- **Nothing else about usage changes.** Steps are still never interrupted, the gates
  stay where they are, no usage is read during a step, and a step that ends normally
  with work to show is untouched.
- **An empty step for any other reason keeps today's behaviour**, except where the
  companion change about a unit with nothing left to do applies.

## Impact

- **agent-build-kit**: one classification where a step's empty result is judged.
- No new state, no new configuration, no interruption of running work.
- The failed list keeps meaning "a person should look".
