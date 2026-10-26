# Proposal

## Why

The `note` on a unit's history entry is both a message for people and the only record of
why the unit changed state. At least fifteen places write it and four read it back by
prefix or pattern. The two ends drift apart without anything failing.

It has already cost throughput. A pass rebuilds a unit it just built only when its last
note says "rework requested…" or `held_for_base(note)` is true, which accepts only notes
that start `held before` or `held after` and contain `: its base `. The graph engine's
hold paths write other leads (`base moved before its push`, `base gone before its pull
request`, `moving onto X needed resolution`), and `held after` is written nowhere. A unit
sent back for a moved base was never let back into the running pass, and waited for the
next one, which cannot start while the pass is running, with a free slot standing idle.

The same shape recurs: a requeue is told apart by the string `"restart"`, a rework is
told apart by `startswith(FAILING_CHECKS_REASON)`, saved feedback by
`startswith("tier 1 failed:")`, a depth hold's old base by a regex over the note, the
pass's outcome by bare strings.

## What Changes

- **A cause on every state change out of running.** History entries (and `set_state`)
  carry `cause`, a `StrEnum`: rework, base changed, upstream went back, usage pause,
  depth cap, toolchain, review escalation, needs a human, requeued, released, and so on.
  Every hold path records one. The note stays as prose.
- **The pass reads the cause.** `_sent_back` readmits a unit whose last cause is rework or
  base changed, whatever words its note uses, and logs why it skips any other. The
  diagram's "reworking", "paused" and "blocked" labels read the same field.
- **Resume events carry kinds.** `RequeueReason` (restart, released, resume, from
  failure, parent merged) and `ReworkKind` (failing checks, conflict, label, changes
  requested, comment) replace string comparison. The detail text rides beside the kind.
- **Feedback records its source** (tier 1, tier 2, review, person, CI poll, conflict
  poll) as a field beside `from_person`, and the prompts read it instead of a prefix.
- **A depth hold stores the base it is still on** as a field, instead of a regex over
  its note.
- **Outcomes are enums.** The unit outcomes the CLI and the tick record share one
  `StrEnum` built on `RunStatus`; a usage pause is its own record with a reason and a time,
  not the outcome's detail text. Escalation kinds and the unit states are enums too, and
  an unsupported toolchain raises its own exception instead of any `NotImplementedError`.
- **No code reads a note, not even once.** There is no migration. Entries written before
  causes existed load with no cause and are never readmitted by a running pass, which is
  how they behave today; the next pass takes them. The old matchers (`held_for_base`, the
  `held before` prefix checks, the reviewer-hold note comparison, the depth-hold regex)
  are deleted in the same change. Units still in flight when it lands are requeued or
  re-held once, which writes a real cause, `held_by` and depth base.
- **Tests assert on the fields,** not on prose, so rewording a note breaks nothing.
