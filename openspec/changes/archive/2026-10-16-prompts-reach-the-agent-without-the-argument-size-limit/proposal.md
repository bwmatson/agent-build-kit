# Proposal

## Why

`abk replan <change>` failed with `OSError: [Errno 7] Argument list too long: 'claude'`. The Claude Code runtime builds its command as
`[*command(), "-p", request.prompt, ...]` (`runtimes/claude_code.py`, `build_argv`), so the whole prompt is one command-line argument. Linux
refuses a single argument over 131072 bytes (`MAX_ARG_STRLEN`) and a whole command line plus environment over `ARG_MAX`.

The planner's prompt is the first to reach that size, and it is growing:

- a fixed template of about 6 KB;
- the one change's `tasks.md` (38 KB for the largest open change);
- the repo relationships and a calibration section (at most 2,000 characters);
- the list of units already in flight: one line for every unit that is running, in review, failed, held, merged or satisfied, plus every planned
  unit of another change. Today that is about 520 lines and 86 KB (merged units alone are 360 lines and 51 KB; planned units of other changes are
  140 lines and 33 KB), and it grows with every unit that merges.

So the largest change's prompt is about 130 KB, just over the cap, and every change would reach it in time. Other prompts that carry a diff or a
log (reviews, restack resolvers, track phases) can reach it as well. All of them pass through the same `build_argv`, so the fix belongs there, once.

The failure is also badly reported: the raw `OSError` is recorded as the plan's reason, which says nothing about what was too large or by how much.

## What Changes

- **The prompt travels on the agent's standard input.** `claude -p` with no prompt argument reads the prompt from standard input (checked by
  running it). The Claude Code runtime stops putting the prompt in its argument list. An ACP agent already receives the prompt as a protocol
  message and is unchanged. The way a runtime carries a prompt is a declared fact of the runtime, one of `stdin`, `protocol` or `argument`, and the
  size check below reads it; nothing else in the kit decides how a prompt travels.
- **A stated safe size per transport.** An `argument` transport states 100,000 bytes (under the single-argument cap, leaving room for the other
  arguments); `stdin` and `protocol` state 2,000,000 bytes (a bound on the prompt, not on the pipe). A prompt over it fails before any process
  starts, with a message that names the call, the size, the limit and the transport, never the raw `OSError`.
- **The planner's in-flight list leaves out what cannot affect a plan.** A merged or satisfied unit of another change is in the trunk: the planner
  is told to place new work against what is in flight, a dependency on landed work needs no edge, and `Needs:` lines are applied by code. Those
  units collapse to one summary line with their count. Units of the change being planned, and every unit that is not merged or satisfied, stay as
  they are.
- **An oversize planner prompt names its parts.** When the prompt is over the safe size, the failure names the change and the size of the template,
  the change's `tasks.md`, the relationships and calibration text, and the in-flight list, so the part to cut is plain.
- The failure is a planning failure like any other (it counts an attempt, shows as `failing n/3: <reason>`, and the plan is made again by
  `abk replan` or when `tasks.md` changes); no retry logic is added.

## Impact

- agent-build-kit: `runtimes/claude_code.py` (`build_argv`, `spawn`, `stream_run` in `pipeline/claude_stream.py`), `runtimes/base.py` (the
  declared transport and the one check), `pipeline/planner.py` (`build_prompt`, `_ask`), `cli/pipeline.py` (the in-flight context in the planning
  round), `docs/agent-runtimes.md`, `docs/architecture.md`, `docs/cli.md`.
- Fixed one-line probes (`refresh_login`, the doctor's reply check) keep their short prompt as an argument; they are under 100 bytes.
- Priority 1: a pipeline fault that stops every change from being planned.
