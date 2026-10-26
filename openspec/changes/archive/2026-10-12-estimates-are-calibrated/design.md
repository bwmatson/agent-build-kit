# Design

## The ratio

`calibration(units, kind) -> float` in `pipeline/unit_size.py`, a pure function of the stored units.

1. **Samples.** The units of the kind whose state is merged and that have both a nonzero `estimated_lines` and an
   `actual_lines`, newest merge first, at most `calibration_window` of them. A unit's sample is
   `actual_lines / estimated_lines`, using the planner's own estimate (see "Two figures").
2. **Clamp each sample** to `[calibration_sample_clamp.low, .high]` (default 0.5 and 4.0), so one unit that landed
   8 times its estimate, or at a tenth of it, counts as 4.0 or 0.5.
3. **Median** of the clamped samples (mean of the middle two for an even count). The median, not the mean, so the
   rest of the sample decides.
4. **Shrink toward 1** by sample count `n`: `ratio = 1 + (median − 1) × n / (n + calibration_shrink)`. At the default
   shrink of 5, five samples carry half of the measured gap and twenty carry 80%; a shrink of 0 carries all of it.
5. **Too few.** With `n < calibration_min` (default 3) the ratio is exactly 1.0.
6. **Final clamp** to `[1.0, calibration_max]` (default 3.0). The ratio only raises an estimate: an installation
   whose units land under their estimates is not told to plan bigger units, because the floor and the ceiling are
   already the planner's to respect.

A **kind** is `(repo, tier, flag)`, where the flag is `contract`, `narrow`, `acceptance` or empty. The flag lives on
a task group in `tasks.md`, not on a unit, so it is recorded on the stored unit when the unit is first stored
(`StoredUnit.flag`): the flag of the first flagged group the unit carries. A unit with no flagged group, and every
unit stored before the field existed, has the empty flag.

## Worked example, from real data

The store of the installation this was designed against holds 124 merged units, of which 33 recorded both an estimate
and an actual size: 31 in one repository at tier 1 and 2 at tier 2. None of the 33 carries a flag, so every one is the
empty-flag kind, and the flagged kinds have no samples (ratio 1.0). Ordered by merge time, the 20 newest tier-1
samples (estimate → actual = ratio) are:

```
 600 → 1115 = 1.86   700 → 1175 = 1.68   450 →  853 = 1.90   550 →  551 = 1.00   450 →  719 = 1.60
 600 →  641 = 1.07   500 →  776 = 1.55   600 → 5198 = 8.66   600 → 1000 = 1.67   400 →  386 = 0.96
 350 →  424 = 1.21   300 →  715 = 2.38   250 →  176 = 0.70   650 → 2053 = 3.16   450 →  510 = 1.13
 450 →  712 = 1.58   600 → 1222 = 2.04   450 → 1016 = 2.26   550 →  791 = 1.44   700 → 1906 = 2.72
```

- Sorted, the clamped samples (8.66 → 4.0, nothing below 0.5): 0.70, 0.96, 1.00, 1.07, 1.13, 1.21, 1.44, 1.55,
  1.58, 1.60, **1.67**, 1.68, 1.86, 1.90, 2.04, 2.26, 2.38, 2.72, 3.16, 4.00. The middle two are 1.60 and 1.67,
  so the median is **1.6322** (unclamped: the same, since the extreme sample sits at the top either way; the
  mean would have been 2.03, which is what the clamp and the median protect against).
- n = 20: `1 + 0.6322 × 20/25 = 1.5058`, inside [1.0, 3.0]. **Tier 1, no flag: 1.51.**
- The two tier-2 samples (650 → 479 = 0.74, 250 → 116 = 0.46) are fewer than 3: **1.0**. (Their median, 0.62,
  would clamp to 1.0 anyway.)
- Applied to the 20 units above, ceiling 750: 11 would have been over the ceiling after calibration (for example
  600 → 903, 700 → 1054, 550 → 828); 9 of those 11 did land over 750, and 2 did not (550 → 551 and 600 → 641). Two more
  that landed over 750 (450 → 853 and 450 → 1016) would still have passed, so 9 of 11 oversize units are caught at
  planning, at the price of 2 false splits.
- How it builds up, as the samples arrive in merge order: 2 samples → 1.0 (fewer than 3); 3 → 1.22; 5 → 1.29;
  10 → 1.23; 20 → 1.47; with all 31, the newest 20 → 1.51. Small samples are pulled hard toward 1, which is the
  point of the shrink.

## Where it is used

- **The plan check** (`planner._check_ceiling`, run from `parse_plan`) compares `estimated_lines × ratio` with the
  ceiling. A group that is alone in its unit and over the ceiling only after calibration is reported as
  `GroupTooLarge` like any other. The message for a combined unit names the raw and calibrated figures, the
  ratio and the sample count, so the planner splits it.
- **The join check** (`joins.check_joins`) compares `(onto + added) × ratio` of the receiving unit's kind with the
  ceiling.
- **The floor stays prompt-guided.** Nothing in code compares an estimate with the minimum unit size; it is only
  stated in the prompt. The prompt says estimates are the planner's raw figures and gives the ratios, so grouping
  toward the floor is done on what units are likely to land at.
- **The prompt** (`planner.PROMPT`, built in `build_prompt`) gains a short section listing each kind whose ratio is
  above 1.0 with the ratio and its sample count, and says that the check multiplies by it. With nothing to list it
  says nothing.
- **The caller** (`cli/pipeline.py`, where `plan_round` is invoked and the unit store is in hand) computes the ratios
  once per round and passes them down; `unit_size.py` and the planner stay free of store access.

## Two figures

`estimated_lines` is never rewritten: it stays the planner's own figure. Calibrating it in place would make the next
sample `actual / (estimate × ratio)`, a ratio nearer 1, and the correction would decay and oscillate. The
calibrated figure is a separate `StoredUnit.calibrated_lines`, `round(estimated_lines × ratio)`, written once when the
unit is first stored and not recomputed. A unit that has started therefore keeps the figure it was planned with, a
later change in the ratio does not touch it, and a join that grows the estimate sets the figure again from the
receiving unit's kind at that time (only before the unit has started; joins onto a started unit are already refused).

The status command lists both: `estimated 600 (calibrated 903)`. The graph page shows neither: the change
`unit-size-off-the-graph` takes size marks off it, and this one adds none.

## Unit-store resilience rule

The unit store is the source of truth and a file on disk that may predate a field. `StoredUnit` rejects unknown keys
(`extra="forbid"`) and validates each unit on read. The two new fields, `flag` (default empty) and
`calibrated_lines` (default none), therefore have defaults, so that a store written before them loads unchanged and
an old unit reads as unflagged and uncalibrated. A present but invalid value (a negative or non-integer
`calibrated_lines`, a flag that is not one of the three) fails the read naming the field, exactly as for any other
field: it is not silently dropped, because dropping it would hide a damaged record. A downgrade is not supported:
an older version forbids the new keys. Units with no calibrated figure are shown and planned as today.

## Configuration

`limits.calibrate_estimates` (true), `calibration_window` (20, at least 1), `calibration_min` (3, at least 1 and not
above the window), `calibration_shrink` (5, not negative), `calibration_sample_clamp` ([0.5, 4.0], low above 0 and
not above 1, high not below 1), `calibration_max` (3.0, at least 1). A bad value fails to load, naming the key. With
`calibrate_estimates: false` every ratio is 1.0, no calibrated figure is stored and the prompt is as it is today.

## Corrections made against the code

- The check that compares an estimate with the ceiling is `_check_ceiling` (called from `parse_plan`), at about line
  170 of `planner.py`, not 206; the join check in `joins.py` is a second comparison that needs the same ratio.
- There is no floor comparison in code (only in the prompt), so calibration cannot "multiply before the floor" in a
  check; the prompt is where the floor is informed.
- `Unit` has no flag: it is a property of a task group in `tasks.md`, so the kind needs `StoredUnit.flag` recorded at
  storing time.
- The graph page does not print the estimate, and `unit-size-off-the-graph` removes its size line, so only the status
  command prints both figures.
- The data holds 33 units with both figures (23 at 1.2 or more, 18 at 1.5 or more), not 12, and no flagged group.

## What the planner is told (second group)

Group 1 gives the planner the ratios and rejects what is over. It does not give the planner the ceiling in its own
terms, any evidence behind a ratio, or a way to act on a rejection; the planner has to divide, trust a number, and
guess how to split. Group 2 adds those, as a bounded, language-neutral addition to the same prompt section.

1. **The ceiling in raw terms.** `largest_raw(limit, ratio) = floor(limit / ratio)`, in `pipeline/unit_size.py`. For
   each listed kind the prompt states the largest raw estimate (ceiling 750, ratio 1.51: 496) and the same for the
   minimum unit size, so grouping toward the floor and stopping at the ceiling are both done in the figures the
   planner writes. Only the ceiling is checked in code; the floor stays guidance.
2. **Recent evidence.** `recent_examples(units, kind, n)` returns the `n` most recent merged units of the kind with
   an estimate and an actual size, ordered as the ratio's samples are (merge time, newest first; ties by unit id),
   so the same store gives the same text. Each is shown as its title (cut to 80 characters), raw estimate and landed
   lines: `"Add the retry helper": estimated 450, landed 853`. Nothing else of the unit is shown: no description,
   path, branch or repository name beyond the kind's own heading. `limits.calibration_examples` (default 3, at least
   0; 0 lists none and keeps the figures) sets `n`.
3. **What drove the overruns: not included.** The share of landed lines in test files would be the useful
   explanation, but the store keeps only `actual_lines`, one number per unit, taken from the pull request's file
   list when it is opened (`wiring._record_size`) and not kept. Splitting it for merged units would take a host call
   per sampled unit at planning time (`forge.pr_changes`), and the profile's `is_test_path` is per repository. That
   is not cheap, so it is left out rather than guessed. A later change could record the test share beside
   `actual_lines` where the file list is already in hand; it would then cover only units merged after it.
4. **The rejection suggests a split.** For a combined unit over the ceiling after calibration the message also
   states the largest raw estimate allowed for its kind and its number of groups, and says to split by group. A single
   group over the ceiling is still `GroupTooLarge`, unchanged.
5. **Joins.** The join text that states the ceiling states the largest raw estimate for the receiving unit's kind
   next to it, and a refused join names it. The kind is the receiving unit's, as in group 1.

**Bounds.** The section lists at most `limits.calibration_kinds_listed` kinds (default 5, at least 1), those with
the most samples first (ties by kind name), then one line saying how many kinds were left out. With the defaults and
titles cut to 80 characters it is under 2000 characters; examples are dropped before kinds if a kind's lines would
pass that, newest kept. It names no installation: kinds are written as the repository and tier names the workspace
already puts in the prompt. With calibration off, or a kind at ratio 1.0 or with too few samples, nothing is added
for it, and with calibration off the prompt, message and join text are as group 1 leaves them.

**Where.** `unit_size.py` holds the two pure functions; `planner.build_prompt` and `_check_ceiling` take ratios and
examples as arguments, as they do the ratios; `cli/pipeline.py`, where the store is in hand and the ratios are
already computed once per round, computes the examples there. The planner stays free of store access.

## Corrections made against the code (second group)

- The brief proposes the test-versus-other share of landed lines "if cheap". It is not: `StoredUnit` holds only
  `actual_lines`, and paths are not kept, so it needs a host call per unit; left out.
- There is no join "proposal prompt" separate from `planner.PROMPT`: the join text is the "Joining" paragraph of
  the same prompt, so the figure goes there and in `joins.check_joins`'s refusal.
- `FileChange` carries only path and line counts; `is_test_path` lives on the toolchain profile, used elsewhere for
  other checks, not in `unit_size.py`.

## Not included (follow-ups if oversize persists)

Recorded here as considered, not built, and nothing in this change depends on them:

- **A size checkpoint after the tests step.** The cheapest point to cut a running unit: only the tests step is redone
  and the rest becomes a stacked unit.
- **A cut by commit range before review**, so a unit that has grown past the ceiling is divided on its own commits.
- **A reviewer guide** for a unit that landed over the ceiling.

None may split a unit after review has started, and this change alters no unit that is running.
