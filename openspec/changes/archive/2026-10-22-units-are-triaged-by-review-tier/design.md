# Design

## Context

The Phase 1 change records a verdict for every approved unit in `runs/verdicts.json`, with its class, its evidence tier (everything
but history), its tier, its reason, the paths changed and `brief`. Nothing reads it. A person sees units in arrival order: `abk
status` lists them as the store holds them, `notify/cards.py` raises a card for every unit in review, and the review tab shows the
unit alone. A unit's `history` records each state it entered with a cause, which is enough to say after the fact whether it was
reworked, and a merged unit's pull request number is kept, which is enough to ask the host what commit the merge produced.

## Decisions

- **What may read a verdict.** Phase 1 said no part of the pipeline reads a recorded verdict to decide anything. That rule is
  narrowed here, and only to what this change needs: the labels, the ordering of what is shown, the choice of which units get a card,
  the review tab, and the verdict's own history floor may read it. Nothing may read it to decide a state, a hold, a size or a
  merge; that stays true until the change that lands units, and a test pins the list of readers.
- **Labels are cosmetic and exclusive.** `review-auto`, `review-light` and `review-full` are one exclusive family, set through the
  same `set_exclusive_label` path as the state labels and with the same containment: a host that keeps no labels, or a call that
  fails, is logged and never raises or changes a unit. A unit that is reworked and approved again gets the label of its new
  verdict. The review labels stay on a finished pull request as the record of what review it got; clearing the state labels leaves
  them alone, and the vocabulary keeps the two families apart so neither removes the other's.
- **Ordering is a stable sort on a rank.** `full` first, then `light`, then units with no verdict, which sort with `light` since an
  unknown is not safer than a known middle, then `auto`; within a rank, arrival order as today. It orders only what is shown: `abk
  status`'s review lines, the review page's list, the review tab's neighbours. It never changes which unit a pass picks to work on.
- **Cards follow the tier.** A card is raised for a unit in review whose recorded tier is `light` or `full`. A unit with no verdict
  keeps its card, so a workspace that has review off sees no difference. A unit whose verdict is `auto` raises none, because the
  design lets such a unit land without a person. Until a class is allowed to land, no unit gets an `auto` tier (the history floor
  holds every class at `light`), and `abk status` lists any that does as awaiting review so it cannot be lost. Failed and held cards
  are unchanged.
- **The tab answers with the verdict.** The review route's answer gains the tier, the reason and the stored focus and skippable
  lists, which the tab shows in a strip at its head; the pipeline summary gains the tier so the review page can order its list.
  Both are absent for a unit with no verdict and the tab then looks as it does today.
- **The outcome is derived, never decided.** It is computed from the unit's history and the repository and written onto the verdict
  record, and it can be recomputed from the same inputs. Its values are `open` (not merged yet), `clean` (merged by a person with no
  rework in its history), `reworked` (merged after one or more reworks, with the count), `reverted` and `closed` (closed unmerged,
  which is no sample). Rework is counted as the number of history entries whose cause is `rework`; a restack onto a moved base
  is not a rework. Failing checks and conflicts are reworks too: they cost a round and a reader's trust the same.
- **A revert is a commit on trunk that says it reverts the merge.** The forge answers the commit the unit's pull request produced (a
  squash commit on the hosts the pipeline lands on). A unit is `reverted` when a commit reachable from the repository's trunk, after
  that commit, has a message line `This reverts commit <full sha>` naming it (what `git revert` and the hosts' revert buttons write),
  or `Reverts <owner>/<repo>#<number>` naming the unit's pull request (what a host's revert pull request writes). A revert phrased in
  any other way is not seen, and the person who made it can still rework the class by hand; the risk is recorded below. The repository
  is asked through its checkout with `git log`, so the rule is tested with temporary git repositories and a stand-in forge, never a
  live host. A forge that cannot say what commit a merge produced (the local one) answers empty, and such a unit's revert is
  not looked for; its record says the revert was not checked.
- **Recheck has a horizon.** A merged unit's outcome is recomputed whenever the pass runs the sweep, until the unit has been merged
  for a fixed number of days, after which it is final. A revert after that is not counted. The horizon is a constant, not a setting,
  until the data says it should be one.
- **Brief gates everything counted.** The clean-merge rate, the agreement rate and the sample counts take only records with `brief`
  true; a record made before the brief is kept with its outcome and excluded, and the report says how many were excluded. A rate is
  never computed over a class's excluded records, and no figure is shown without its sample count.
- **Rates.** Samples of a class are its brief-carrying records with a final-enough outcome (`clean`, `reworked`, `reverted`). The
  clean-merge rate is `clean` over samples. Agreement is over the samples whose evidence tier was `auto`: the share a person accepted
  as they stood, which is `clean` among them. A class with no such samples has no agreement figure, not a zero.
- **The gates.** A class clears them when its samples reach `review.auto_land.min_samples` and its clean-merge rate reaches
  `min_clean_rate`; these are the two keys Phase 1 already added. A class the policy does not name (a repo-and-kind class) is shown
  with its figures and is marked as not nameable, since only a named class can be listed. Promotion stays a person's edit of
  abk.yaml; the report only says when it may be time.
- **The history floor reads real history.** Phase 1's floor held every class at `light`. It now holds a class at `light` when its
  brief-carrying samples are fewer than `min_samples` or its clean-merge rate is below `min_clean_rate`, and otherwise raises
  nothing. The same rates as the report, one function. With no history it behaves as before.
- **Metrics.** `abk.review.outcome` counts each outcome as a unit reaches it, by outcome, tier and class; `abk.review.agreement`
  counts, per unit whose evidence tier was `auto` and which merged, whether a person accepted it as it stood. No unit id is an
  attribute. Both go in the metric catalogue.
- **`abk review report` is read-only.** It reads the verdict records and prints; it never edits abk.yaml, the records or a unit.

## Risks

- **A revert phrased otherwise is invisible,** and a class would keep a clean record it has not earned. The wording rule is the
  conventional one both hosts and `git revert` produce, the exclusion is stated in the report, and promotion remains a person's
  decision with the full record in front of them.
- **An `auto` unit waits without a card** until a class may land. The history floor makes this unreachable now, `abk status` lists
  such a unit, and the change that lands units gives it a digest instead.
- **Counting rework from history overstates it** for a unit reworked because CI failed, which a person never saw. That errs toward
  fewer clean merges, the safe side.
- **Small samples.** A class with few samples shows its count beside every rate and never clears the gates early.
