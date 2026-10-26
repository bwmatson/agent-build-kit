# Proposal

## Why

The planner's `estimated_lines` is a model's guess, and it runs low: of the 33 merged units in one installation's
store that recorded both figures, 23 landed at 1.2 times their estimate or more, and 18 at 1.5 times or more (up to
8.7 times). A unit's real size is learned only after its pull request is opened, so oversize is found after the
build and the review rather than at planning. The store already holds the evidence: every merged unit keeps its
estimate and, once it has a pull request, its actual lines.

## What Changes

- **A calibration ratio per kind of unit.** A kind is the repository, the tier and the group flag
  (`contract`, `narrow`, `acceptance` or none). The ratio is the median of the last merged units' actual over
  estimate, each sample clamped, shrunk toward 1 when the sample is small, and kept within 1 and a maximum.
  With too few samples it is 1.
- **The plan check uses it.** A unit's estimate is multiplied by its kind's ratio before it is compared with the
  ceiling; a unit over the ceiling after calibration is rejected like any oversize plan, with a message naming
  the ratio and the samples, so the planner splits it. The same figure is used when a group is joined onto a unit.
- **The planning prompt states the ratios as facts**, per kind, so the planner estimates and groups with them.
- **The planner is given the figures in its own terms, and evidence** (second group): per calibrated kind, the
  largest raw estimate a unit may carry (ceiling over ratio, rounded down) and the three most recent merged
  units of the kind as title, raw estimate and landed lines; the rejection of a combined unit names the largest
  raw estimate allowed and the group count so it can be split by group; the join text carries the same figure.
  The addition is bounded, and `limits.calibration_examples` (3, 0 is off) and `calibration_kinds_listed` (5)
  set it.
- **A unit keeps both figures.** Its stored record keeps the planner's estimate and the calibrated figure, fixed
  when the unit is stored; the status command lists both. Samples are always the planner's raw estimate, never
  the calibrated one, so the correction cannot compound.
- **Configuration:** `limits.calibrate_estimates` (default on), `calibration_window` (20), `calibration_min` (3),
  `calibration_shrink` (5), `calibration_sample_clamp` ([0.5, 4.0]) and `calibration_max` (3.0), plus `calibration_examples` and `calibration_kinds_listed` (above). Off, planning is
  as it is today.
- **Not included:** anything that changes a unit that is running (see the design for the follow-ups considered).

## Impact

- agent-build-kit: `pipeline/unit_size.py`, `pipeline/planner.py`, `pipeline/unit_store.py`, `config.py`, the
  status command, `docs/configuration.md`, `docs/architecture.md`, the `abk-config` skill and the changelog.
- Specs: `unit-sizing` gains calibration requirements and two requirements are modified.
