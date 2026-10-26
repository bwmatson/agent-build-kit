# Proposal

## Why

`converging-review` gave the review loop the outcomes it lacked. This change is
about the two things that decide how many rounds there are before an outcome is
reached: how the reviewer looks, and what it hands back.

- **A review approved work that the next review found four real defects in.**
  A unit was approved, then reworked for an unrelated comment, and the review of
  that rework found four behaviour problems in code the earlier review had
  passed. Two were visible only from a changed function's callers (a dependency
  check that three sibling functions made and a fourth did not). One was a
  removed behaviour: a count that returned 0 on a failed command, where 0 used
  to lead to a failure and now led to the unit being recorded as done and its
  pull request closed. The prompt asks for everything in one pass. It does not
  say to trace callers or to account for what a diff removes, and those are the
  two places a read of the diff alone does not reach.
- **A required change needs no stated consequence.** "Required" is whatever the
  reviewer puts under that heading. Nothing asks what goes wrong, for whom, on
  what input. A preference and a defect cost the same round.
- **The verdict is prose, and the next round sees part of it.** Feedback is one
  string. The next reviewer is shown the first 4000 characters of each earlier
  round; a thorough review runs well past that, so the later findings of a
  round are the ones the next reviewer cannot check. Nothing can be counted,
  ranked, addressed by name or posted against a line.
- **A later round re-reads the whole branch.** The round note tells the
  reviewer to look only at what the reworks changed, but does not say which
  commit the last round judged, so the scope of "what changed" is left for it
  to reconstruct.
- **Optional findings are unbounded.** One review listed eight. Each is written
  at the review model's price and read by a builder inclined to act on them,
  which grows the unit.

## What Changes

- **The review prompt names its angles.** Three, worked in the one pass: read
  each hunk and the function enclosing it; for every line removed or replaced,
  name what it enforced and find where that is re-established; for every
  function changed, find its callers and callees and check each against the
  change. The existing instructions (sweep the domain, shallow interfaces,
  tests against the real system) stay.
- **Each candidate is checked before it is reported.** The reviewer re-reads
  the code a candidate points at and drops one the code already guards
  against. In the same context — no subagent, no second run.
- **A required finding states its consequence.** The input or state that
  triggers it and the wrong result; for a convention, the rule broken; for a
  test, the wrong behaviour it would let through. A finding that cannot name
  one is optional.
- **The verdict carries findings as a list.** Each has a file, a line where
  there is one, a one-sentence summary, the consequence, what done looks like,
  and whether it is required. The text given to the builder, stored on the unit
  and put in a pull request is rendered from the list. A verdict with only
  `feedback` prose, as today, is still read.
- **Findings have ids, and a later round answers each one.** The loop numbers
  them by round. The next round's note lists every earlier required finding
  whole, with the builder's answer, and the verdict says of each whether it is
  fixed, still open, or declined for a reason that holds.
- **A later round is told which commit was judged last,** so its search for new
  problems is that commit to the head, plus anything it can show was not
  visible before.
- **Optional findings are ranked and capped at five.** Required findings are
  never cut.

## Impact

- **agent-build-kit** only: the review prompt, the round note, the verdict
  parser and the record of a round. No new agent call, no new tool for the
  reviewer, no configuration.
- Review cost per round should not rise: the angles are instructions within the
  existing pass, and later rounds are given a narrower scope than they have
  now.

## Non-goals

- Subagent fan-out or a separate verifier per finding. That is where a
  multi-angle review's cost is, and the loop already pays for a second look in
  the form of the next round.
- A minimum number of findings, or a bias towards surfacing. Every finding here
  can cost a round.
- Posting findings as inline pull request comments. The list makes it possible;
  it is a separate change to the forge.
- A lighter review for small diffs. It needs a threshold to configure, and the
  angles cost little on a diff with few functions in it.
