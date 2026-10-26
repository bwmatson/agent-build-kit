# Design

## What was verified

- `AgentPushed`, `_agent_pushed` and the `before`/`after` reads are in `pipeline/wiring.py`, in the
  wrapper `run_agent` builds around every agent call.
- `remote_head` has a no-origin branch returning the local branch head, and `""` when the branch does not exist.
- The pipeline's own push (`push_with_lease`) returns the local head and pushes nothing when there is no origin.
- `tests/pipeline/test_wiring_runtime.py` covers the guard only with a bare remote named `origin`.

## Who depends on `remote_head`'s no-origin fallback

Every caller of `remote_head`:

| Caller | Uses the fallback? |
|---|---|
| `wiring.py` `run_agent` / `_agent_pushed` (the guard) | No: it wants the true remote, and breaks on the fallback. |
| `wiring.py` `do_push` (via `remote_head_of`) | Yes: it compares the "remote" with the last recorded push and the local head, to tell a push whose record was lost from a host move; with no origin it must see the local branch. |
| `events.py` restack/move (via `remote_head_of`) | Yes: same comparison after a person's merge or the pipeline's own restack; the local branch is where a no-origin unit lives. |
| `tests/pipeline/test_no_remote.py`, `test_restack.py` | Pin the fallback and the with-origin read. |

Two of three production callers rely on the fallback, so it stays.

## Options

- (a) Skip the guard when `shell.has_origin` is false. One condition at the guard; `remote_head` untouched.
- (b) Make `remote_head` return None for the guard. Needs a new parameter or a second function, and a
  caller-visible mode on a function whose other callers need the opposite.
- (c) Read the post-step head from the actual remote only. Same new mode as (b), plus a second code path
  that duplicates `remote_head`'s `ls-remote`.

Chosen: (a). The guard exists to catch a push, and with no origin the pipeline has nowhere to push to,
so there is nothing to guard. It is the smallest change and leaves every other caller as it is.

## Mechanics

In the wrapper, the branch is treated as unguarded when `has_origin(cwd)` is false: `before` is not
read and `_agent_pushed` is not called. `has_origin` is true for a path that is not a directory and when
git cannot list remotes, so an unreadable repo still reaches the guard and fails where it is used, as before.

## What the guard still catches, and what it does not

With an origin, the guard is unchanged: a push of a commit made in this worktree to the unit's branch during
an agent step fails the step with `AgentPushed` and the same message. Pushes from elsewhere, and heads the
agent only fetched, are still not the agent's.

Possible remote configurations:

1. An `origin`: guarded.
2. No remotes at all: `has_origin` is false; nothing to push to; skipped.
3. Remotes, none named `origin`: `has_origin` is false too (it tests for the name `origin`), and the
   pipeline treats the repo as having no remote. `push_target` only ever names `origin` or an ssh alias of
   its URL, so the pipeline would not push to such a remote either.
   An agent that pushes to it is not detected. That is out of scope: the guard protects the pipeline's own
   push, which that remote does not take part in. No change to `has_origin`; the requirement states the
   behaviour so it is not mistaken for a gap.

An agent given a way to push elsewhere is also held back by the tool policy (`agent-tool-policy`), which
is the main control; the guard is a diagnostic.

## Not a push: the pipeline's own movement

The pipeline commits to the branch and restacks or adopts heads outside agent steps, and in a no-origin
repo its push returns the local head. None of that is inside the window the guard watches; with the guard
skipped for no origin it cannot be read as a push there, and with an origin it is the remote's head that is
compared, which only a push moves.

## Tests

A no-origin test with a stand-in agent that commits and does not push goes first and fails today with
`AgentPushed`. The existing with-origin tests pin the unchanged behaviour. The downstream check is the
acceptance test `test_local_forge_unit.py` (the `local-forge` group 3 test named above); `local-forge`
group 3 waits on this change.
