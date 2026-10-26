# Design

## Context

A unit is one branch, one pull request and one verdict (the philosophy rejects several pull requests from one unit, since the branch
name, the pull request, the labels, the poller's map from pull request to unit and the state all assume one). So a split is a change of
plan: the unit is replaced by units. Today a started unit's shape is fixed: `UnitStore.upsert` keeps state, branch and pull request;
`_STARTED` in `cli/pipeline.py` makes the groups of running, in-review, failed, held, merged and satisfied units *taken*, which
`_taken_groups` hides from the planner and `_gone_groups` insists still exist in `tasks.md`; `closed` is none of those, is finished
for `in_progress`, is not in `REVIEWED`, and blocks archiving. The poller turns a closed pull request into `closed`. The verdict is a
pure function over recorded facts (shadow-mode change), computed in the review node after every review round, interim until the
round that approves, with the unit's changed lines and the reviewer's `drivers` in its record. Per-tier ceilings, the expected review tier on a unit and the plan record's sizing digest exist
from the previous change.

## Decisions

- **The buffer and the rounds are settings of `review`.** `ceiling_buffer` is a fraction from 0 to 1 and `split_rounds` an integer
  from 0 to 2, validated when the configuration loads, which also fails when the buffered `auto` ceiling of the workspace or of any
  repo would reach the reviewer's reading limit, a constant of 10,000 lines in the framework, since a unit that large cannot be read by
  the reviewer model at all. `abk doctor` prints the buffered ceilings and warns when the buffered `auto` ceiling is above 80% of the
  limit, and when `split_rounds` is 0 with review enabled, because every unit over its tier would then go to a person. The planner never
  reads the buffer.
- **The size step is part of the verdict, after the tier.** The verdict computes the tier a unit earns as before, then compares the
  unit's changed lines (counted as a pull request's are, generated files left out) with the ceiling in effect for that tier in the
  unit's repo times one plus the buffer. Over it, the outcome is *hold and split*, with the tier it earned, the tier it was planned for,
  the lines, the ceiling and the reviewer's drivers. Comparing with the earned tier covers the other case, a unit over the ceiling of the
  tier it was planned for with nothing higher earned, because the earned tier is never below the planned one: then the drivers are empty.
  It is a pure function with a table test, like the rest of the verdict. A failure to compute it is logged and the unit goes on as in
  shadow mode; a unit is never split because something broke.
- **Drivers are groups.** The reviewer may name groups or files. A file is taken to name the groups of the unit whose task text names
  that path; one that matches none is dropped, and a verdict whose drivers all drop has none, so the split is only asked to bring
  each unit under its ceiling. Pins are groups of the unit's own change.
- **The hold comes after any round, not only the last.** The review node weighs each round's reply, computes the verdict, and when the
  verdict (interim or final) says hold and split it holds the unit at once, instead of asking the builder for another round or
  approving. A unit that will be split is found at the first round that shows it, so no further rework rounds are spent on a unit
  whose pieces will be rebuilt or cherry-picked anyway. A round whose reply holds the unit for a person (`needs_human` or
  `escalate`) is held for that reason first, and the size step does not run for it. The hold is: `held`, `Cause.TOO_BIG_FOR_TIER`,
  `HeldBy.SIZE`, the request (tiers, drivers, lines, ceiling) kept on the unit, and the unit's pull request, if it has one, recorded.
  It is not a failure and not a review round: `review_round` is not advanced and the rounds a rework uses are untouched. Held by size,
  waiting to be split, it raises no card (a card is for a person); the cards go to a unit held for a person.
- **Held for a person.** When a split cannot happen the unit is held again with `HeldBy.REVIEW` and the same cause, and a note giving
  the reason: rounds spent (`2 of 2`, or `split_rounds` is 0); the unit has one group, or one group alone is over the ceiling of the tier
  it earned; the unit carries groups of another change, which a one-change plan cannot split; or a unit is stacked on it that has
  started, since superseding would orphan that branch. A person's `abk requeue` of such a unit records `size_waived`, and the verdict's
  size step is skipped for a unit with it set, so a person who reads an oversized unit and lets it through is not held again by the same
  rule. The tier the unit earned still applies.
- **Superseded is `closed` with a cause.** A new state would have to be taught to every reader of unit state, and `closed` is already
  finished for them. The unit is set to `closed` with `Cause.SUPERSEDED` and a `superseded_by` field naming its pieces, and the readers
  that differ are named in the table below. This is the exact behaviour:

  | Reader | Behaviour for a superseded unit |
  |---|---|
  | `_STARTED`, `_taken_groups`, `_gone_groups` | Not started: its groups are not taken and need not still be in `tasks.md` |
  | `in_progress`, `start_room` | Finished: occupies no slot |
  | `REVIEWED`, `waiting_on` | Not reviewed; nothing waits on it, because dependents are re-pointed |
  | `is_ready_to_archive` | Counts as finished without merging, like `unplanned`: its pieces carry its groups |
  | `on_closed` (the poller's closed event) | Left alone, as a satisfied unit's own close is, so the cause is not overwritten |
  | `retry_closes` | Also closes the pull request of a superseded unit, from `close_pending` |
  | `upsert` | Keeps it closed; a plan may not use its id (a check, below) |
  | status, graph, web | Shown as closed, with "superseded by" its pieces |

  The unit keeps its `pr` and `branch`, so the poller can still map the closed pull request to it.
- **One atomic write.** `UnitStore.supersede` writes, under the store's lock and in one write: the pieces as `planned` units with their
  dependencies, the old unit closed with its cause and pieces and a `close_pending` for its pull request, and every other unit's
  `depends_on` and `needs` that named the old unit re-pointed to the last piece, which waits on the others by chain. Before it, with the
  branch lock held, the old branch is kept at `refs/spec-driven/superseded/<unit id>` (the way `reset_to` keeps work under a ref); the
  remote branch is left, so the closed pull request still shows. The pull request is closed afterwards by the existing close and its
  retry, with a comment naming the pieces, the lines, the ceiling and the tier, in this order so a reason is never missing.
- **Ids.** A piece's id is its parent's id plus `-s<k>` for its place `k` from 1 in the split: `app/3` becomes `app/3-s1` and
  `app/3-s2`, and `app/3-s2` split again becomes `app/3-s2-s1`. The branch name is the prefix and the id, so it is `spec/app/3-s1`,
  a valid ref that does not sit under `spec/app/3`. Ids stay unique because a child extends its parent, siblings differ in `k`, and a
  superseded id is retired: the plan check refuses a plan using one, and the planner's instructions list the retired ids. Three places
  read the last segment of an id as an integer and are changed: `unit_number` takes its leading integer, so a piece sorts where its
  root did and `earlier_units` still puts an acceptance or narrowing unit after it; the run-log prefix (`run_log.py`) and the
  transcript prefix and readers (`transcript.py`, two functions) take the suffix into the file name, as `<change>-03-s2-`, which the
  existing "stamp follows the prefix" match keeps apart from `<change>-03-`.
- **Pins are an input to the planner.** `plan_round`, `build_prompt` and `parse_plan` take an optional split request. The prompt names
  the unit's groups in order, says that this is a split, lists the pins and the tiers (drivers: the earned tier; the rest: the tier it
  was planned for; with no drivers every piece takes the earned tier), gives the ceilings, and asks for piece ids of the form above and
  a chain. The groups the planner may plan are the unit's alone: every other group of the change is passed as built.
- **`_check_pins` refuses rather than repairs.** Next to `_check_groups`: each run of consecutive driver groups is in units that hold
  only driver groups, at the earned tier; every other unit holds none and is at the planned tier; a driver group between others gives a
  unit before, the driver, and a unit after. `_check_split_shape` checks that the pieces partition the unit's groups into contiguous runs
  in their order, that piece ids are exactly the parent's id with `-s<k>`, that the first piece depends on what the unit depended on, that
  each later one depends on the one before, and that no piece depends on any other unit of the change. `_check_ceiling` and the flag and
  dependency checks run as for any plan, at each piece's tier, to the plain ceiling.
- **A split is its own call with its own counter.** A tick step after planning takes each unit held by size, in priority order, and: holds
  it for a person when no round is left or the unit cannot be split; otherwise asks for a plan, and records an attempt in the unit's
  lineage whatever comes of it. `split_rounds_used` is kept on the unit and passed to its pieces, so a piece that is split again has
  one fewer left, and the maximum of 2 counts splits along a lineage. A failed or invalid reply, a refused plan and a plan that fails
  `_check_pins` each consume a round; an outage of the network or the model service does not, as for planning. A refusal for a single
  group over its ceiling holds the unit for a person at once. After a failed round the unit stays held by size and is tried again on the
  next tick, until the rounds are used.
- **Later plans of the change keep the pins.** An ordinary plan of the change would regroup unstarted pieces and lose the constraint, so
  every plan of a change is given the pins of its superseded units whose pieces have not all started, and refused if it ignores them.
- **Reuse by cherry-pick, or rebuild.** The rule for which path a piece takes is fixed by the old branch alone: if its commits are
  exactly a `test:` and `feat:` pair for each of the unit's groups, in order (the per-group commit change's shape, read from the
  branch's subjects), the pair of each group of the piece is cherry-picked, in order, onto the piece's branch when its run is prepared,
  and the run resumes from the branch as a build that is already part done; otherwise, or from the first group whose pair does not
  apply cleanly, the piece is built as any unit is. A branch with a rework or fix commit on it is therefore rebuilt, since such a commit
  belongs to no group. Reuse needs no setting of its own: it follows from how the old branch was built, and it is what the per-group
  commit change made possible. Either way the old branch stays under its ref.
- **Per-tier sizing is on by default in the last group.** There is no second switch: `review.enabled` is the build-out flag that gates the
  recording of verdicts and the sizing, and the last group makes its default true, which is what makes the 5000 and 2000 ceilings take
  effect and the verdict's size step act. Auto-land stays off, since it needs a class listed. The soak criterion is stated in the group:
  with the flag on in the installation that builds this framework, at least 25 units built, every unit split ending in pieces that each
  passed review, none held for a person except for a single oversized group, and a planner-accuracy reading that shows fewer than one
  unit in four planned below its verdict. The group changes the default, its test, the documents and the template, and the changelog
  says plainly that turning the flag off returns every unit to `max_unit_lines`.

## Risks

- **Superseding touches many readers of unit state.** The table names each and a test pins each. Choosing `closed` plus a cause kept
  the list short, and the one reader that would silently fail, archiving, is on it.
- **A started dependent.** A unit stacked on the held one blocks the split, which holds the unit for a person. It is the rare case of a
  rework that grows a pull request over its ceiling after others began on it.
- **A planner that ignores the pins.** Each failure is a round and the check names what was ignored; two rounds later a person has the
  unit with the reason.
- **An early hold for a driver a rework would have removed.** A round-one classification of `full` for a path the builder would have
  taken out in the next round splits a unit that did not need it. The cost is a re-plan, bounded by `split_rounds`, and the review
  prompt tells the reviewer to classify the unit as it stands; the interim record shows how often a later round's tier is lower
  than the one that caused a split, so the rule can be tightened from evidence.
- **Cherry-picks that do not apply.** A later group may depend on an earlier group's rework that is in no pair; the picks stop at the
  first that conflicts and the rest of the piece is built, so the cost is a partial rebuild, not a wrong branch.
- **A wrong estimate that is only wrong a little.** The buffer keeps a unit within 20% of its ceiling out of the expensive path.
- **Turning the default on.** It makes every installation record verdicts and size by tier. The soak criterion is measured in one
  installation, and the flag is the rollback.
