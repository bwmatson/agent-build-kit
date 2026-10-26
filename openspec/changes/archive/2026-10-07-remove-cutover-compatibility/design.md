# Design

## What goes

- `graph/convert.py` and its two entry points (`convert_in_flight`, `convert_units_in_flight`);
  the call and the "moved onto a thread" log line in the tick; the import.
- `StoredUnit.resume_from` and its use in `unstarted`; `StoredUnit.classic_run`,
  `BEFORE_THE_SWITCH`, `_collect_classic_run`, their use when reading the store, the carry in
  upsert, and `clear_converted`.
- The comment in the graph's prepare step about "a thread converted from the engine before the
  switch". The empty-head handling beside it stays: an event-delivered rework also has no head.
- The "Moving the units in flight" section of `docs/unit-graph.md` and the conversion mentions
  in `docs/architecture.md`.
- Tests that exist only for the above, and the helper store that builds old-shaped records.

## The failure on an old store

The unit store's model forbids unknown fields. With the collector gone, a record carrying
`review_rounds`, `deferred`, `pending_replies`, `person_comments` or `resume_from` fails to
validate; the store's loader catches that and raises one error naming the unit and the field
and telling the operator to finish or requeue old work on the previous release. The changelog
gets a `Breaking:` entry in the style of the earlier removal of renamed settings.

## Before it builds

The conversion also seeded a thread for any unit in `in_review` or `held` that had none. So the
first task reads the live thread database and the unit store and checks that every unit in
`in_review`, `running` or `held` has a thread. If one does not, the group stops and says which,
and a person requeues it first.

## The cause bridge (second group)

Delete the tick-time log lines naming units with no recorded cause and the paragraph in the
architecture and CLI documents and the pipeline skill that describes handling them. Keep the
`cause is None` behaviour (not readmitted) and the forward-tolerant read of an unknown cause.
`abk status` keeps a line listing units with no cause: a diagnostic, not a bridge.

## Order

The second group waits for the first, and both wait for `status-not-wording` because they edit
the same files (`unit_store.py`, the tick and the status command).

## Out of scope

Anything listed as permanent in the proposal.
