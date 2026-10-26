# Tasks

Acceptance: none — a pure function over the unit store, one planner check and one status line; tier-1 tests prove each.

## 1. [agent-build-kit] [tier1] Estimates are corrected by what units of the same kind landed at

Done when a plan whose raw estimate is under the ceiling but whose calibrated estimate is over it is rejected naming
the ratio, the status lists both figures, and with `calibrate_estimates: false` planning is unchanged.

- [x] 1.1 Test (`tests/pipeline/test_unit_size_calibration.py`): `calibration(units, kind)` takes the median of the
      last `calibration_window` merged units of the kind that have both an estimate and an actual size; units with
      no estimate (0) or no actual size are ignored; an unmerged unit is not a sample; window ordering is by the
      time the unit merged, newest kept.
- [x] 1.2 Test: each sample is clamped to `calibration_sample_clamp` before the median — a single 8.66 sample among
      eleven is read as 4.0, and a 0.1 sample as 0.5.
- [x] 1.3 Test: shrinkage — samples all at 2.0 give 1 + 1.0 × n/(n+5): 1.5 for n=5 and 1.8 for n=20; with
      `calibration_shrink` 0 the median is used whole.
- [x] 1.4 Test: fewer than `calibration_min` samples give exactly 1.0; the result is never below 1.0 (median 0.62
      gives 1.0) and never above `calibration_max`.
- [x] 1.5 Test: kinds are separate — tier1 and tier2, two repositories, and a `[contract]` group's unit each get
      their own ratio from their own samples; a unit's kind takes the flag of its first flagged group.
- [x] 1.6 Test (worked example of the design as fixture): the 20 newest tier-1 samples of the example give 1.5058;
      the tier-2 kind with 2 samples gives 1.0.
- [x] 1.7 Test: the plan check rejects a unit estimated 600 with ratio 1.5 against ceiling 750 (900), message
      naming the ratio, the sample count and the raw and calibrated figures, and re-asks within the attempt
      budget; accepts a unit estimated 480 (720); a single group over the ceiling only after calibration is
      reported as `GroupTooLarge`.
- [x] 1.8 Test: joining a group onto a unit compares the calibrated sum with the ceiling.
- [x] 1.9 Test: with `calibrate_estimates: false` every ratio is 1.0, nothing is stored or printed beyond today's,
      and the prompt carries no ratios.
- [x] 1.10 Test: the planning prompt lists each kind that has a ratio above 1.0 with its ratio and sample count and
      says estimates are the planner's raw figures.
- [x] 1.11 Test: a unit stored with a calibrated figure keeps it when its kind's ratio later changes, and its
      samples use the raw estimate; a store file written before the fields existed loads, with the figure absent
      and the kind's flag empty; a calibrated figure that is not a positive whole number fails the load naming the
      field, as for any other field.
- [x] 1.12 Test: the status command prints the estimate and the calibrated figure for a unit that has one, and
      is unchanged for one that has none.
- [x] 1.13 Test: configuration — the six keys with their defaults; `calibration_min` above `calibration_window`, a
      clamp whose low is above 1 or whose high is below 1, a `calibration_max` below 1 and a negative shrink each
      fail to load naming the key.
- [x] 1.14 Add `calibration(units, kind)` and the kind of a unit to `pipeline/unit_size.py`; the six keys to
      `LimitsConfig` with their checks; `flag` and `calibrated_lines` (defaults empty and none) to `StoredUnit`.
- [x] 1.15 Apply the ratio in the planner's ceiling check and in the join check, fix the figure when a unit is first
      stored, put the ratios in the prompt, and print both figures in the status command.
- [x] 1.16 Update `docs/configuration.md`, `docs/architecture.md` (sizing paragraph), the `abk-config` skill's limits
      block, the comment on `max_unit_lines`, and add a changelog entry.

## 2. [agent-build-kit] [tier1] The planner is given the ceiling in its own terms, recent evidence and a split to make

Done when the planning prompt states, per calibrated kind, the largest raw estimate a unit may carry and the few
most recent merged units of that kind, the rejection message names the largest raw estimate allowed and the
number of task groups, the join text carries the same figure, and with `calibrate_estimates: false` or
`calibration_examples: 0` the prompt adds nothing for them.

- [x] 2.1 Test (`tests/pipeline/test_unit_size_calibration.py`): `largest_raw(ceiling, ratio)` is `floor(ceiling /
      ratio)` — 500 for ceiling 750 and ratio 1.5, 750 for ratio 1.0 — and the same for the minimum unit size
      (the figure below which grouping continues, stated in the planner's raw terms).
- [x] 2.2 Test (`tests/pipeline/test_planner_calibration_prompt.py`): the prompt's calibration section gives, for
      a kind with ratio 1.51 and 20 samples at ceiling 750, the largest raw estimate (496) and the raw floor
      figure, and never the word of an installation; a kind with ratio 1.0 or fewer samples than the minimum is
      not listed.
- [x] 2.3 Test: examples — for a kind with more merged units than `calibration_examples`, the section lists the
      most recent N by merge time (default 3), each as its title, raw estimate and landed lines, in a fixed order
      (newest first, ties by unit id), the same on every call; it carries no unit text beyond the title and no
      repository path or installation name; `calibration_examples: 0` lists none and keeps the figures; a unit
      without an estimate or an actual size is not an example.
- [x] 2.4 Test: the section is bounded — at most `calibration_kinds_listed` (5) kinds are listed, kept by most
      samples first (ties by kind name), and the section ends with one line saying how many kinds were left out;
      a title is cut to 80 characters; the whole section stays under a fixed maximum size (2000 characters) for
      the default settings and the largest allowed inputs.
- [x] 2.5 Test: the rejection message for a combined unit over the ceiling after calibration also states the
      largest raw estimate allowed for its kind and the number of groups the unit carries, and says to split by
      group; the message for a single group over the ceiling is unchanged from group 1.
- [x] 2.6 Test: the join text of the prompt states the largest raw estimate allowed for a unit of the receiving
      unit's kind next to the ceiling, and a refused join names it; with `calibrate_estimates: false` the join text
      is as before group 2.
- [x] 2.7 Test: with `calibrate_estimates: false`, the prompt, the rejection message and the join text are
      byte-for-byte what group 1 leaves them as.
- [x] 2.8 Test: configuration — `calibration_examples` defaults to 3, 0 is valid, a negative or non-integer value
      fails to load naming the key; `calibration_kinds_listed` defaults to 5, must be at least 1.
- [x] 2.9 Add `largest_raw` and `recent_examples(units, kind, n)` (a pure function over the stored units, ordered
      as the ratio's samples are) to `pipeline/unit_size.py`; `calibration_examples` and
      `calibration_kinds_listed` to `LimitsConfig` with their checks.
- [x] 2.10 Extend the prompt section built in `planner.build_prompt` with the per-kind figures and examples under
      the bounds above, extend `_check_ceiling`'s message and the join text and `joins.check_joins` refusal with
      the largest raw estimate, and pass the examples with the ratios from `cli/pipeline.py`, where they are
      computed once per round from the unit store.
- [x] 2.11 Update `docs/configuration.md`, `docs/architecture.md` (sizing paragraph), the `abk-config` skill's
      limits block and the changelog.
