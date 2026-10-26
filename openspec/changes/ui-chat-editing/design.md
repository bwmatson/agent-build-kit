# Design

## Two kinds of chat

A turn on the unit's own recorded session is the unit's builder, resumed. It carries the pipeline's
constraints and guidance: edits only inside the unit's worktree and only code, tests and docs, never the
planning repo's change files; commit and push denied; an instruction that tests and code change
together in one change (guidance only, not an enforced order); the unit's change as read-only context;
and the spec-conflict rule below.

Today the server decides whether a turn is policed from the working directory: a session whose directory is a unit's worktree is
policed, whoever started it. The unit's builder is instead identified by the session the unit's record names, so a turn is policed
and given the guidance only when its session is that one, and a free session started in the same worktree is not. The policy gains a
no-commit option beside the existing no-push, applied to the builder's turns; a free session's turn keeps only the refusal of commit
and push described below, since the server starts it.

Any other session is free: a session started in the UI for a unit, a repo or the planning repo, or one
started in an editor, a command line or another front end and continued here. It has none of that. It
may change code and specs in one session, in the unit's worktree and the planning checkout together,
under the user's own settings, with permission requests answered in the browser. The one rule that
applies is that nothing is committed until the user commits, because the commit is what feeds the
pipeline; turns the server runs deny commit and push, since the server starts those processes.

## Whose changes these are

The lease the session bridge already takes (one file per unit under the state directory, holding the holder, the process that took
it and when that process started) is the attachment. Nothing new is added beside it. The record is `{holder, pid, started}` today and a lease whose process has gone reads as no lease. It is extended with what the tick needs to tell
chat changes from a failure's leftovers: the checkouts the chat covers (the unit's worktree, the planning checkout, or both), a
flag that those checkouts hold uncommitted changes, the session, the runtime, the branch head when the lease was taken, and a
marker for a commit that is made and not yet delivered.

Today a lease whose process has gone holds nothing, which is right for a chat that changed nothing and wrong for one that left
uncommitted files. So a lease whose process has gone is read in two ways: a lease with no changes and no marker is released as it
is now; a lease marked as holding changes, or marked committed, stays as a stale attachment until it is resolved. The existing
holders, the taking and releasing by a tab, and the release of a page's leases when it closes are unchanged, except that closing a
page does not release a lease that is marked as holding changes.

The recorded start is the checkpoint's `running_node`, set when an editing node starts and cleared when it completes, not a step
count in the unit store. For a dirty worktree the tick decides from the lease and from that start of the node being run:

| lease | recorded node start | the tick |
|---|---|---|
| held by a live process | any | leaves the unit alone, as it does for any held lease; it is listed as attached with the number of changed files |
| process gone, marked as holding changes | any | never commits or continues it; parks it with the cause `attached` and says to start the server or run `abk attach release` |
| process gone, marked committed | any | finishes the delivery of that commit once, then removes the lease |
| none | names the node being re-run | failure leftovers: resume over them, committed by the node's own commit, flow continues |
| none | none | parks it as an unexplained dirty tree, as now |

A chat attaches only while the unit is in a stable state (in review, held, failed). A unit paused in the
middle of a node is shown read-only, because resuming it is the tick's job. If a killed node's recorded
start is still set when someone attaches, the files already present are that run's leftovers; the
commit adopts them with the rest and clears the start.

`abk attach release <unit>` resolves a lease without the server: with `--commit "<message>"` it
commits and adopts, with `--discard` it restores the tree, and without either it refuses if the tree is
dirty. The server reads stale leases when it starts and takes them over.

## Adopting a commit

Commit shows the changed files and a message, proposed by the agent or typed. It commits through the
existing commit helper, bound to the attached session: a plain retry for hooks that reformat files, then
the unit's agent is given the hook output, fixes it and the commit is tried again, the helper's existing
bounded number of times, with progress shown in the chat. If it is still rejected the changes stay
uncommitted and attached and the output is shown; the user can chat and try again. On success, in the same operation, the lease
is released and a new event, adopted (a new `EventKind` with its routing), is delivered (see "One call ends an attachment" below). It enters at the checks from a unit in review, held
or failed, clears the recorded node start, and runs unit-test with its own check-fix budget, then the
review loop and the push gate. The previous approval is never reused because the head changed. The
commit carries the unit trailer and an adopted-from trailer naming the session.

The review that follows is round zero: it takes no place in the round limit and cannot hold the unit
as having spent its rounds even if the budget was spent when the chat began. If it asks for changes, the
counted rounds start at one with the rework. Earlier findings are kept so the reviewer answers them.

## One call ends an attachment

Committing is one request. In it the server commits (hooks and the agent's fix loop included); on success it writes a marker into
the lease saying the commit is made and the delivery is pending, releases the lease, delivers the adopted event,
removes the lease, and answers with the commit, the unit's new state and that the delivery completed. The caller makes no second
call, and the page offers no separate release after a commit. The release has to come before the delivery, because an event for a
unit whose branch is held is refused, so the marker is what keeps the two steps from being separated by a failure.

A commit that the hooks still reject after the bounded loop answers with a conflict and the hook output, keeps the lease and
leaves the changes uncommitted. A commit that is made and not delivered, because the delivery failed or the server stopped between
the steps, leaves the lease marked committed with its hash. The next start of the server, the next `abk attach release` for the
unit and the tick's attachment check treat that as a delivery to finish, not as chat changes left behind: they deliver the adopted
event once for that hash and drop the lease, so a unit is never left with a new commit and no event. Repeating the same call with
the same hash does nothing and returns the result.

The other ways an attachment ends have the same shape. Discard restores the tree and releases the lease in one request. `abk attach
release <unit> --commit "<message>"` and `--discard` do the same in one command. Releasing a clean worktree is a call of its own. A
commit of the planning checkout, which is delivered to no unit, releases that checkout's part of the attachment in the same call,
and a call that commits both checkouts releases the lease once at the end.

## The spec and the build session

The unit's chat turns carry the proposal, design, spec deltas and the unit's task groups as read-only
context. The agent is told that when a request contradicts them it replies first with a structured flag
naming the requirement or task, makes no edit and waits. The bridge emits the flag as a custom event and
the UI shows a highlighted callout with Proceed anyway, Change the spec instead (which opens a free
session on the planning repo) and Cancel. Review comments and other non-chat interactions are resolved
by the unit's build session through the rework path, so the same instruction is in the rework prompt and
a conflicting comment is answered in its thread with the flag and left until the reviewer confirms. No
other context is added for them.

## Free sessions and the two checkouts

Commit is per checkout. The unit worktree's commit goes through the commit helper and is adopted. The
planning checkout's commit uses `abk check` and `abk tags <change>` as its gate, with the same
agent-fixes-then-retry loop, and is delivered to no unit. After it, the UI lists what it means for units
that have started: a line that only changed a `Needs:` is applied on the next tick; a change to the plan
is re-planned on the next tick and built units keep their state; a unit whose spec no longer matches its
branch is flagged for a rework or a requeue and never changed automatically.

## Outside commits

If the session that committed is the unit's build session nothing extra is said, since it already
knows. If a free session committed to the unit's branch, its commit carries the session in the
adopted-from trailer and the unit's next rework, check-fix and review prompts get a packaged part listing
the commits made outside this session: hash, subject, files and session; authoritative, not to be
reverted, files to be re-read. It is how a restack tells the agent that its base changed; for the tests such
a commit changed, the agent states keep, adapt or retire only if it changes them. It is found by comparing
the trailer's session with the unit's recorded build session, so no new state is kept. The history and
`abk status` show adopted commits.

## Decisions pending

- The exact marker the agent returns for a spec conflict, and whether the flag is a tool result or a
  fenced block in the reply.
- Whether a free session's commit to a unit's branch must also be refused while the unit has a step
  running, or only when it is attached (the lock already prevents the second).
