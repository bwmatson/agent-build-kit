# Design

## What exists

When a run begins with commits already on the branch, the runner calls
`restack_onto` before anything else: `git rebase --onto <base> <old base>`,
which replays only the unit's own commits, so a squash-merged parent does not
conflict. A clean move is logged and the run carries on; a move that needed
resolution leaves a note for the reviewer; one that cannot be resolved goes to
the adapt step.

Before each later step a checkpoint asks `base_moved`: has the unit's base in
the store changed, or been rewritten underneath it. If so the unit is put back
to `planned` with the step to resume at, and its next run restacks.

The trunk is built on as the remote has it (`local_ref`), and the remote is
fetched by `fetch_all` at the start of a tick.

## Fetching

`fetch_all` stays. Added: one repo's fetch, taken in that repo's turn as every
other write to its `.git` is, called by the runner

- before the restack at the start of a run with existing commits, and
- before the push.

A fetch that fails is logged and the run proceeds on what it has, as
`fetch_all` does today. A unit must not fail because the network blinked.

## The check before the push

After the last checkpoint and before `push`:

1. Fetch.
2. Work out the base afresh. If the unit's base is a parent's branch, ask the
   forge for that parent's pull request. If it has merged, record the merge
   through the same handler a poll uses — so the store, the parent's worktree
   cleanup and the unit's siblings are all treated as they would be — and take
   the new base from the graph.
3. If the branch already sits on the tip of that base, push.
4. Otherwise move it, with the same `restack_onto` the start of a run uses.
   - **Clean:** re-run tier 1 against the new base, then push. The approval
     recorded for the old commit carries to the moved one: the gate that checks
     "only an approved commit is pushed" accepts a commit whose patch is the
     approved one's replayed without resolution. This is what a resume already
     does today; it is stated here so the push step and the resume share it.
   - **Needed resolution, or could not be resolved:** do not push. Put the unit
     back to `planned`, resuming at its restack, with a note saying its base
     moved before its push. Its next run resolves, is reviewed and pushes — the
     existing path, under the usage gate.
   - **Tier 1 fails on the new base:** the same hold, with tier 1's output as
     the feedback. The trunk changed something the unit depends on, and that is
     a rework, not a failure.

Bounded: the check runs once per push. If the trunk moves again during the
tier 1 re-run, the push goes ahead and the pull request is at most one merge
behind, which the open-pull-request conflict check covers.

## A base that is gone at open

`open_pr` can still lose the race: the base is deleted between the check and
the call. The forge's error for a missing base is recognised by the forge
adapter — each one knows its own message — and surfaced as a distinct error
the runner turns into the same hold. Any other failure to open stays a failure.

## Testing

Through the runner with its usual doubles, and with real git for the moves:

- a run starting from existing commits fetches before it restacks;
- a push whose base has advanced on the remote, cleanly: the branch is moved,
  tier 1 runs again, the push happens, no agent is called and no review round
  is spent;
- a push whose base has advanced and conflicts: nothing is pushed, the unit is
  planned to resume at its restack, and the note says why;
- a push whose parent's pull request has merged, unknown to the store: the
  merge is recorded, the unit is moved onto the trunk and pushed against it;
- tier 1 failing after the move: not pushed, held with the output;
- opening a pull request against a base the forge says is missing: held, not
  failed; another error from the forge: failed, as now;
- a fetch that fails: logged, and the run continues.
