# unit-sizing Specification

## Purpose
Defines the upper bound on how much work the planner may put in one unit: where
it is configured and how planning respects it. Nothing here constrains a branch
after it is built.

## Requirements

### Requirement: A workspace configures a ceiling on a unit's size

The workspace SHALL configure the largest number of changed lines one unit may
carry. Before per-tier sizing is on (`review.enabled` false) that is
`global_limits.max_unit_lines`, defaulting to 750, for every unit, and it SHALL
be the same as `review.ceilings.full` when both are set. With `review.enabled` true it is the ceiling of
the review tier the unit is expected to get (see review-tier-ceilings), and the
`full` ceiling is the one 750 stands for. The ceiling in effect for a unit SHALL be required to exceed the
floor on unit size, which defaults to 400. A workspace that sets either value
keeps it. A configuration whose floor is at or above a ceiling in effect SHALL fail to
load, naming both values.

#### Scenario: The default

- **WHEN** a workspace configures no ceiling
- **THEN** the ceiling is 750 changed lines and the floor is 400

#### Scenario: A floor above the ceiling

- **WHEN** a workspace sets a floor at or above the ceiling
- **THEN** loading the configuration fails, naming both values, rather than
  producing plans that cannot satisfy either

#### Scenario: Per-tier sizing is on

- **GIVEN** `review.enabled` is true and the default ceilings
- **WHEN** a unit expected to get `auto` review is planned
- **THEN** its ceiling is 5000 changed lines, and the floor is still 400

### Requirement: Planning keeps units under the ceiling

The planner SHALL be told the ceiling, task groups SHALL NOT be combined into a
unit whose estimate, multiplied by its kind's calibration ratio, exceeds it, and a plan that returns such a unit
SHALL be rejected with that reason, naming the ratio and the samples behind it, and re-asked within the existing
attempt budget. A group joined onto a unit SHALL be held to the same figure.

#### Scenario: Grouping small task groups

- **WHEN** consecutive same-repo groups would together exceed the ceiling
- **THEN** they are split across units, even where the floor would have kept
  grouping them

#### Scenario: A plan that ignores the ceiling

- **WHEN** a returned plan contains a unit estimated over the ceiling
- **THEN** the plan is rejected with that reason and the planner is asked again

#### Scenario: Over the ceiling only after calibration

- **GIVEN** a ratio of 1.5 and a ceiling of 750
- **WHEN** a returned plan contains a unit estimated at 600
- **THEN** the plan is rejected, the message naming 600, 900, the ratio and its samples

#### Scenario: Under the ceiling after calibration

- **GIVEN** a ratio of 1.5 and a ceiling of 750
- **WHEN** a returned plan contains a unit estimated at 480
- **THEN** the unit is accepted

#### Scenario: A joined group

- **WHEN** a group is joined onto a unit and the two estimates, multiplied by the ratio, exceed the ceiling
- **THEN** the join is refused with that reason

### Requirement: A task group too large to plan is reported, not planned badly

When one task group's own estimate, multiplied by its kind's ratio, exceeds the ceiling, no grouping can satisfy
it, so the pipeline SHALL report that the change's tasks need splitting and leave
the change unplanned, rather than spending planning attempts or emitting a unit
over the ceiling.

#### Scenario: One oversized group

- **WHEN** a change contains a single task group estimated over the ceiling
- **THEN** the change is left unplanned with a message naming that group and
  saying its tasks must be split

#### Scenario: One group oversized only after calibration

- **GIVEN** a ratio of 1.5 and a ceiling of 750
- **WHEN** a change contains a single group estimated at 600
- **THEN** the change is left unplanned with a message naming that group and saying its tasks must be split

### Requirement: The planner is told what an estimate counts

The planner's instructions SHALL define an estimate as the additions plus deletions in every
file a group changes, including tests, docs, fixtures and the changelog and excluding
generated files, SHALL tell it to count the removed lines of a group that removes or
rewrites code, and SHALL tell it to estimate high when unsure.

#### Scenario: A group that deletes code

- **GIVEN** a group that removes an existing module and replaces it
- **WHEN** the planner is instructed
- **THEN** its instructions tell it to count the removed lines as well as the added ones

### Requirement: A unit records its actual size beside its estimate

A unit with a pull request SHALL record the pull request's actual changed lines, excluding
generated files, when the pull request is opened and again whenever a push updates it, and
SHALL log and list in the status when the actual size exceeds the ceiling. The graph page
SHALL NOT mark a unit for its size. The ceiling SHALL NOT block a unit from landing.

#### Scenario: A unit lands over the ceiling

- **GIVEN** a unit estimated at 600 lines whose pull request changes 1,400
- **WHEN** the pull request is opened
- **THEN** the unit records 1,400 beside its estimate, its log and the status say it is over
  the ceiling, and the graph page shows its node as it shows one under the ceiling

#### Scenario: A rework changes the size

- **WHEN** a push after a rework changes the pull request's size
- **THEN** the recorded actual size is updated

#### Scenario: A lockfile

- **WHEN** a pull request includes a lockfile's changes
- **THEN** they are not counted in the actual size

### Requirement: An estimate is corrected by what units of its kind landed at

The framework SHALL compute, for each kind of unit (its repository, its tier and the flag of its first flagged
group, or none), a calibration ratio from the last configured number of merged units of that kind that recorded
both a nonzero estimate and an actual size. Each sample, the actual size over the planner's own estimate, SHALL be
clamped to the configured sample range, the ratio SHALL start as the median of the clamped samples, SHALL be
moved toward 1 by `n / (n + shrink)` of its distance from 1 for `n` samples, SHALL be exactly 1 when there are
fewer samples than the configured minimum, and SHALL be kept between 1 and the configured maximum.

#### Scenario: The median of the samples

- **GIVEN** five merged units of a kind landing at 1.2, 1.4, 1.6, 1.8 and 2.0 times their estimates, shrink 5
- **WHEN** the ratio is computed
- **THEN** the median is 1.6 and the ratio is 1.3

#### Scenario: A single extreme sample is clamped

- **GIVEN** eleven samples of a kind, ten at 1.5 and one landing at 8.66 times its estimate
- **WHEN** the ratio is computed
- **THEN** the extreme sample counts as 4.0, and a sample at a tenth of its estimate counts as 0.5

#### Scenario: Shrinkage grows with sample count

- **GIVEN** samples that are all 2.0 and a shrink of 5
- **WHEN** there are 5 samples the ratio is 1.5, and when there are 20 it is 1.8

#### Scenario: Too few samples

- **WHEN** a kind has fewer merged samples than the minimum
- **THEN** its ratio is 1.0

#### Scenario: Units that landed under their estimate

- **WHEN** the median of a kind's clamped samples is below 1
- **THEN** its ratio is 1.0, never lower

#### Scenario: Kinds are separate

- **GIVEN** samples at unit-test and at e2e-test, in two repositories, and for a `[contract]` group
- **WHEN** ratios are computed
- **THEN** each kind's ratio comes only from its own samples

#### Scenario: Units with nothing to compare

- **WHEN** a merged unit has no estimate, or has no recorded actual size
- **THEN** it is not a sample

#### Scenario: The correction does not compound

- **WHEN** a unit was planned with a calibrated figure
- **THEN** its sample is its actual size over the planner's own estimate, not over the calibrated figure

### Requirement: Calibration is configured and can be switched off

The framework SHALL configure calibration under `limits`: `calibrate_estimates` (default on),
`calibration_window` (20), `calibration_min` (3), `calibration_shrink` (5), `calibration_sample_clamp` (0.5 to
4.0) and `calibration_max` (3.0). A configuration whose minimum exceeds its window, whose clamp does not contain
1, whose maximum is below 1 or whose shrink is negative SHALL fail to load, naming the key. With calibration off
every ratio SHALL be 1.0 and planning SHALL be as it is without it.

#### Scenario: The defaults

- **WHEN** a workspace configures none of them
- **THEN** calibration is on, with window 20, minimum 3, shrink 5, clamp 0.5 to 4.0 and maximum 3.0

#### Scenario: A minimum above the window

- **WHEN** a workspace sets a minimum above its window
- **THEN** loading fails, naming the key

#### Scenario: Calibration switched off

- **WHEN** calibration is off
- **THEN** a plan is checked against the ceiling with the planner's raw estimates, no calibrated figure is
  stored and the planner's instructions carry no ratios

### Requirement: The planner is told the ratios

When calibration is on, the planner's instructions SHALL state, for each kind whose ratio is above 1, the ratio and
the number of samples behind it, and SHALL say that the check multiplies the planner's estimates by it.

#### Scenario: The planning prompt carries the ratios

- **GIVEN** a kind with a ratio of 1.51 from 20 samples
- **WHEN** the planner is instructed
- **THEN** its instructions give that kind, 1.51 and 20, and say estimates are checked after multiplying

### Requirement: A unit records its calibrated figure beside its estimate

A unit SHALL record, when it is first stored, its kind's flag and its estimate multiplied by its kind's ratio. The
estimate SHALL stay the planner's own figure, and the calibrated figure SHALL NOT change after the unit is first
stored, so a unit that has started keeps the figure it was planned with. The status command SHALL list both figures
for a unit that has one. A store written before these fields existed SHALL load, reading as unflagged and without a
calibrated figure; a present value that is not valid SHALL fail the load naming the field.

#### Scenario: A started unit's figure does not change

- **GIVEN** a running unit stored with a calibrated figure of 903
- **WHEN** its kind's ratio later changes
- **THEN** the unit's calibrated figure is still 903

#### Scenario: An older store

- **WHEN** the store was written before the fields existed
- **THEN** it loads, and its units have no calibrated figure

#### Scenario: Both figures in the status

- **GIVEN** a unit estimated at 600 with a calibrated figure of 903
- **WHEN** the status is shown
- **THEN** it lists 600 and 903

### Requirement: The planner is given the ceiling in its own terms and recent evidence

When calibration is on, the planner's instructions SHALL state, for each listed kind, the largest raw estimate a
unit of that kind may carry (the ceiling divided by the ratio, rounded down) and the same for the minimum unit
size, and, unless the configured number of examples is 0, the most recent merged units of the kind, up to that
number (default 3), each as its title, its raw estimate and the lines it landed at, chosen by merge time with a
fixed tie-break so that the same store gives the same text. The instructions SHALL show nothing of a unit beyond its
title and SHALL name no installation. A kind whose ratio is 1 or which has fewer samples than the minimum SHALL NOT
be listed. The added text SHALL be bounded: at most the configured number of kinds (default 5), those with the most
samples first, with a line saying how many were left out, and a fixed maximum size. The instructions SHALL NOT state
a share of landed lines by file type, because the store does not hold it.

#### Scenario: The largest raw estimate per kind

- **GIVEN** a kind with a ratio of 1.51 from 20 samples and a ceiling of 750
- **WHEN** the planner is instructed
- **THEN** its instructions give that kind's largest raw estimate as 496

#### Scenario: Examples are the most recent merged units

- **GIVEN** a kind with six merged units that have both figures
- **WHEN** the planner is instructed with the default number of examples
- **THEN** the three that merged last are shown, newest first, each as title, raw estimate and landed lines, and
  the same text results on every call

#### Scenario: Examples switched off

- **WHEN** the number of examples is 0
- **THEN** no example is shown and the ratio and the largest raw estimate still are

#### Scenario: A kind that is not listed

- **WHEN** a kind has a ratio of 1.0, or fewer samples than the minimum
- **THEN** the instructions say nothing about it

#### Scenario: The section is bounded

- **GIVEN** eight kinds with ratios above 1 and a limit of 5 kinds
- **WHEN** the planner is instructed
- **THEN** the five kinds with the most samples are listed, and a line says three were left out

#### Scenario: Calibration off adds nothing

- **WHEN** calibration is off
- **THEN** the instructions carry no largest raw estimate and no example

### Requirement: A rejection for size says how to split

When a combined unit is rejected for being over the ceiling after calibration, the message SHALL also state the
largest raw estimate allowed for its kind and the number of task groups the unit carries, and say to split it by
group. A single group over the ceiling SHALL be reported as it is without this.

#### Scenario: The rejection names the allowed estimate and the groups

- **GIVEN** a ratio of 1.5, a ceiling of 750 and a unit of three groups estimated at 600
- **WHEN** the plan is checked
- **THEN** the message names 900, the ratio, the samples, a largest raw estimate of 500 and three groups

### Requirement: The join text carries the largest raw estimate

When calibration is on, the planner's instructions about joining SHALL state the largest raw estimate a unit of the
receiving unit's kind may carry beside the ceiling, and a refused join SHALL name it.

#### Scenario: The join prompt carries the figure

- **GIVEN** a receiving unit whose kind has a ratio of 1.5 and a ceiling of 750
- **WHEN** the planner is instructed
- **THEN** the joining text states 500 as the largest raw estimate

### Requirement: The added planner context is configured

The framework SHALL configure it under `limits`: `calibration_examples` (default 3, at least 0, 0 turns the examples
off) and `calibration_kinds_listed` (default 5, at least 1). An invalid value SHALL fail to load, naming the key.

#### Scenario: A negative number of examples

- **WHEN** a workspace sets `calibration_examples` below 0
- **THEN** loading fails, naming the key

### Requirement: An e2e-test group is sized and planned alone

The size rules SHALL treat an `[e2e-test]` group as a unit by itself: the planner SHALL NOT group consecutive `[e2e-test]` groups to reach the
minimum size, the unit's estimate SHALL be that group's, and a single `[e2e-test]` group estimated over the ceiling SHALL be reported as needing
its tasks split, as any single group is. The planner prompt's grouping bullet SHALL say that it does not apply to `[e2e-test]` groups.

#### Scenario: Small consecutive e2e-test groups are not grouped for size

- **GIVEN** two consecutive `[e2e-test]` groups of one repo each estimated at 60 lines, with a minimum of 300
- **WHEN** the change is planned
- **THEN** each is a unit of its own and neither plan nor join groups them to reach the minimum

#### Scenario: One e2e-test group over the ceiling

- **GIVEN** an `[e2e-test]` group whose honest estimate is over the ceiling
- **WHEN** the change is planned
- **THEN** it is reported as needing its tasks split

#### Scenario: Unit-test groups are grouped as before

- **GIVEN** consecutive small `[unit-test]` groups of one repo
- **WHEN** the change is planned
- **THEN** they may be grouped to reach the minimum, as before
