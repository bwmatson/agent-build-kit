## From `checking-status/1`

- A person needs to settle whether an old-format snapshot (one with no `checks` key) is recorded afresh without sending anything back, as the spec scenario says, or read like a first sighting that reworks a red check, as design.md implies. The code follows the spec. Whichever is chosen, update the other document so the spec and design.md agree (earlier optional point 1.4).
- Map GitHub's STARTUP_FAILURE conclusion to `failed` in a follow-up, and add it to the design table. Right now it falls through to `pending`, so a workflow that cannot start never sends a unit back (earlier optional point 1.5).

## From `checking-status/2`

- recorded_checks: map any status that is not a known string to pending, including unhashable values such as a list. As written, `status in known` raises TypeError on them.
- design.md, section 'Where the inputs come from': replace 'the link, which the list carries, is kept in the snapshot too' with 'links are not kept in the snapshot'. The builder could not edit the planning repo; the spec does not need the link.
- src/agent_build_kit/pipeline/pr_poller.py:435 — `status if status in known else "pending"` raises TypeError when a recorded status is unhashable, such as a list or dict in a hand-edited or corrupted snapshot. So the 'unknown reads as pending' guard covers unknown strings and numbers, but not every malformed value.
