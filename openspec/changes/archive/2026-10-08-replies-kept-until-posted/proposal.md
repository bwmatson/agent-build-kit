# Proposal

## Why

After a unit is pushed, its replies to reviewers' comments are posted one by one. Each failure is
swallowed and logged, and then the list of pending replies is cleared, so a reply the host
refused for a moment is lost. A satisfied unit's pull request is closed by posting its reason and
then closing; on any failure it is left open with a note and nothing tries again.

## What Changes

- **Replies are kept.** A reply that still fails after the forge layer's attempts stays in the
  unit's pending replies; only a reply that was posted (or found already posted) is removed. The
  next pass posts what is left.
- **The close completes.** A satisfied unit's pull request is closed by repeating the pair (reason,
  then close) on each pass until done; the reason is checked for before posting again so it is not
  duplicated.
- **Visible.** A unit with unposted replies or an open satisfied pull request says so in `abk status`
  with the reason it is waiting.
