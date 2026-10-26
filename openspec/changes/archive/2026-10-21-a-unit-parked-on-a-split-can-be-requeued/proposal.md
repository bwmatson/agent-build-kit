## Why

A started unit can be parked on a held e2e-test split (`park_for_split` holds it `planned` with cause `split_held` and records `parked_splits`,
`parked_sha` and `parked_snapshot` through `set_parked`, `src/agent_build_kit/pipeline/unit_store.py:1186-1189`). On 2026-10-21
`planning-in-the-working-copy/16` was in that state, parked on `acp`, because its test file carried the `acp` tag by mistake: it uses a scripted
stand-in agent and bills nothing. The cure is a code edit by the unit's builder, and nothing lets a person ask for one:

- **`abk requeue` refuses a planned unit.** `requeue_refusal` (`src/agent_build_kit/cli/pipeline.py:5765-5772`) lets only `failed` and `held`
  units through and says "only a failed or held unit can be requeued".
- **The release resumes, it does not rework.** `release_split_held` (`cli/pipeline.py:2082-2107`) delivers `RequeueReason.RESUME` and only when the
  parked split is released (`_releasable_split_units`, 2211-2226); a resume at the e2e step runs the same tests on the same head.
- **The group-split rule needs an edit of `Split:`.** `release_split_changed` (2150-2208) reworks a parked unit only when its group's `Split:` now
  differs from the stored split and from the splits it is parked on. Here the group says what it always said (a `rest` unit parked on `acp` alone
  is left parked by design), and the mistake is in the code.

## What Changes

- **`abk requeue` accepts a parked unit when a mode that runs the agent is given.** A unit is parked when it is `planned` with cause `split_held` or
  a non-empty `parked_splits`. It is accepted with `--rework` (with or without `--note`/`--note-file`, and without a saved failure) or `--restart`,
  provided it is not in flight, has no pull request and no live run.
- **It is delivered like the other requeues of a unit with a thread** (`resume_thread` with the person's note stored as guidance; with no thread the
  guidance is stored and the unit set `planned` with cause `requeued`), after which `parked_splits`, `parked_sha`, `parked_snapshot`, the
  `split_held` cause and the unit's wait record are cleared. The history entry names the splits it was parked on and the person's note. The unit
  runs from `prepare` as a rework.
- **A plain requeue (resume) of a parked unit is judged by its holds.** While a split it is parked on is held it is refused, with a message saying
  the unit is parked on those splits (held: the reason) and to give `--rework` with a note saying what changed, or to release the split. When none
  of its parked splits is held it behaves as the release does.
- **Refusals stay**: a `running` unit, one `in_review`, a `merged` one, a unit in flight and a unit with a pull request are refused as before.
- **Docs**: `abk requeue --help`, `docs/cli.md`, the `abk-pipeline` skill and the changelog say so.

No new command, no new state, no new `RequeueReason` and no change to when the pipeline releases or reworks a parked unit by itself.
