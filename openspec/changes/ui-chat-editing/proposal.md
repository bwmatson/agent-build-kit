# Proposal

## Why

`abk-web-ui` lets a person chat with the agent behind a unit. Chatting is only useful if the agent can
change things, and changing a unit's worktree live collides with how the pipeline works: it refuses a
dirty worktree, it recovers a failed run by committing what that run left and carrying on, and it
reviews only commits it knows about. A chat's uncommitted edits would be mistaken for a failure's
leftovers or parked as a stray hand edit; a commit made by hand would bypass checks and review; a
commit made by another session would arrive unannounced to the agent that built the unit; and the agent
that builds a unit cannot change the specs it was told to build, so correcting a spec means leaving the
tool.

## What Changes

- **Live edits stay uncommitted:** a turn on a unit's own session may change files in its worktree and
  cannot commit or push. The changes wait in the working tree until the user commits or discards them.
- **The tick tells chat changes from a failure's leftovers:** the lease a chat already takes, which the
  tick respects, is extended to say the worktree holds a chat's uncommitted changes, and such a lease
  outlives its process and its page. Failure leftovers (a killed node's recorded start, no lease) are
  resumed and committed with the node's own commit as before; chat changes are never committed or
  continued by the tick, even when the server has gone.
- **Commit adopts the changes:** the commit goes through the repo's hooks; when they reject it the unit's
  agent is given the output, fixes it and the commit is tried again, a bounded number of times. A
  successful commit sends the unit through its checks, the review loop and the push gate, and that
  review does not count against the review-round limit.
- **The build session is told the spec:** its chat carries the unit's change as read-only context and a
  tests-with-code instruction, and a request that contradicts the change is flagged and waits for
  confirmation before anything is edited. A review comment that contradicts it is answered in its thread
  in the same way.
- **Free sessions:** any other session, whether started in the UI or in an editor, a command line or
  another front end, has no such guidance or constraints. It may change code and specs together, and
  commits are made per checkout: code through the repo's hooks and adopted into the unit, specs through
  `abk check` and `abk tags` with the same fix-and-retry loop.
- **Outside commits are identified:** when a free session commits to a unit's branch, the unit's agent is
  told in its next rework, check-fix and review prompts, as a restack tells it its base changed.

## Impact

- agent-build-kit: the branch lock and worktree guard, a new event and causes in the unit graph, the
  commit path, the rework, check-fix and review prompts, the chat bridge, `abk status` and a new
  `abk attach release` command.
- Depends on `resume-over-leftovers` (the leftover handling it is told apart from) and `abk-web-ui`
  (the bridge, the lease and the recorded history).
