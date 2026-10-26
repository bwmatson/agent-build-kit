# auto-land Specification

## Purpose
TBD - created by archiving change low-risk-units-land-without-a-person. Update Purpose after archive.

## Requirements

### Requirement: The policy names the classes that may land without a person

The `review` section of abk.yaml SHALL accept `auto_land.classes`, a list of class names defaulting to empty, `audit.sample_rate`, a
rate from 0 to 1 defaulting to 0.1, and `demotion` with `window`, a count of at least 1 defaulting to 30, and `min_agreement`, a rate
from 0 to 1 defaulting to 0.9. Every class in `auto_land.classes` SHALL be a class named in `review.classes`. A value outside its range,
an unknown class or an unknown key SHALL fail loading and name the key. An empty `auto_land.classes` SHALL turn auto-land off, and
nothing SHALL write these keys but a person editing the file.

#### Scenario: Defaults

- **WHEN** a workspace sets none of the keys
- **THEN** it loads with no class listed, a sample rate of 0.1, a window of 30 and a minimum agreement of 0.9

#### Scenario: An unknown class

- **GIVEN** `auto_land.classes: [typo]` and no such class in `classes`
- **WHEN** the configuration is loaded
- **THEN** loading fails naming `typo`

#### Scenario: A rate out of range

- **GIVEN** `audit.sample_rate: 2`
- **WHEN** the configuration is loaded
- **THEN** loading fails naming the key and the value

### Requirement: Only pipeline code lands a unit, and only when every condition holds

The pipeline SHALL land a unit only when all of these hold: review is enabled; the unit is in review with no feedback pending and is
not held; its recorded final verdict, not an interim one, has the tier `auto`; its class is listed in `auto_land.classes` now; its class is not demoted now; its
forge merges; its pull request is open, not a draft, not known to conflict, has no hold label and no request for changes; the pull
request's head is the commit review approved; nothing unmerged lies beneath the unit; and the pull request's checks are all green.
When any does not hold, the unit SHALL not land and the pipeline SHALL record the reason in words where `abk status` shows it. A
unit already declined SHALL be looked at again on the next pass.

#### Scenario: Every condition holds

- **GIVEN** an approved unit of a listed class with an `auto` verdict, an open pull request on the trunk at the approved head and
  green checks
- **WHEN** the landing step runs
- **THEN** the unit is merged by the forge's merge operation

#### Scenario: The class is not listed

- **GIVEN** the same unit in a class absent from `auto_land.classes`
- **WHEN** the landing step runs
- **THEN** nothing is merged and the reason says the class is not enabled

#### Scenario: A hold label

- **GIVEN** the same unit with the hold label on its pull request
- **WHEN** the landing step runs
- **THEN** nothing is merged and the reason says it is held

#### Scenario: A moved head

- **GIVEN** a pull request whose head is not the approved commit
- **WHEN** the landing step runs
- **THEN** nothing is merged

#### Scenario: Stacked on an unmerged unit

- **GIVEN** a unit whose parent has not merged
- **WHEN** the landing step runs
- **THEN** nothing is merged and the reason names the parent

#### Scenario: The off switch

- **GIVEN** `auto_land.classes` is empty
- **WHEN** the landing step runs on any unit
- **THEN** nothing is merged

#### Scenario: Review is off

- **GIVEN** `review.enabled` is false and a class listed
- **WHEN** the landing step runs
- **THEN** nothing is merged

### Requirement: The pipeline reads the checks itself, and no checks is no evidence

Before landing, the pipeline SHALL read the pull request's checks from the forge and SHALL require every one to have passed. A pull
request with no check registered SHALL have no evidence and SHALL NOT land. Pending or cancelled checks SHALL make the unit wait, and a
failed check SHALL leave the unit to the existing rework path. The pipeline SHALL NOT assume that any check is required by the host.

#### Scenario: All green

- **GIVEN** three checks all passed
- **WHEN** the landing step runs
- **THEN** the unit lands

#### Scenario: One failing

- **GIVEN** three checks of which one failed
- **WHEN** the landing step runs
- **THEN** the unit does not land

#### Scenario: Pending

- **GIVEN** a check still running
- **WHEN** the landing step runs
- **THEN** the unit waits and lands on a later pass once the checks pass

#### Scenario: No checks

- **GIVEN** a pull request with no check registered
- **WHEN** the landing step runs
- **THEN** it does not land and the reason says there is no evidence

### Requirement: A landed unit is recorded merged with the cause `auto_landed`

When the forge has merged the unit's pull request, the pipeline SHALL record the unit `merged` with the cause `auto_landed` through the
path a person's merge is recorded by, so children are retargeted and restacked, the worktree and branch are removed, and verify and
archive treat the unit as any merged unit. Before calling the forge the pipeline SHALL record an intent naming the unit and pull
request, and SHALL remove it once the merge is recorded. A merged event the poller later reports for a pull request that has an
intent SHALL be recorded with the cause `auto_landed`.

#### Scenario: Recorded

- **WHEN** a unit lands
- **THEN** it is in state `merged` with cause `auto_landed`, its children are restacked on the new base, and its intent is removed

#### Scenario: A stacked child

- **GIVEN** a child unit built on a unit that lands
- **WHEN** the landing is recorded
- **THEN** the child is retargeted and restacked as for a person's merge of its parent

#### Scenario: Verify and archive

- **GIVEN** a change whose every unit has merged, one of them by landing
- **WHEN** verify and archive are due
- **THEN** they run as for any merged change

#### Scenario: A crash between merge and record

- **GIVEN** a merge the forge completed and an intent still on file
- **WHEN** the poller reports the pull request merged
- **THEN** the unit is recorded `merged` with cause `auto_landed`, not `merged` by a person

### Requirement: Recording a merge is idempotent

An event that a pull request merged, for a unit already recorded `merged`, SHALL change nothing: no history entry, no second restack
of its children, no second removal of its worktree or branch. This SHALL hold whichever of the landing step and the poller records the
merge first.

#### Scenario: The poller after the landing step

- **GIVEN** a unit the landing step recorded `merged`
- **WHEN** the poller reports the same pull request merged
- **THEN** the unit's history, its children and its worktree are unchanged

#### Scenario: The landing step after a person's merge

- **GIVEN** a unit a person merged and the poller recorded
- **WHEN** the landing step finds its pull request already merged
- **THEN** it records nothing and calls no merge

#### Scenario: A refusal

- **GIVEN** a merge the host refuses
- **WHEN** the landing step runs
- **THEN** the unit stays in review, its intent is removed and the reason is recorded

### Requirement: The pull request says it was auto-landed and why

After recording a landing, the pipeline SHALL comment on the pull request that the unit landed without a person and why, quoting the
verdict's reason and the unit's class, and SHALL add the label `auto-landed`. A failure of either SHALL be logged and SHALL NOT
undo or delay the record.

#### Scenario: The comment

- **WHEN** a unit lands
- **THEN** its pull request carries a comment naming the class and the verdict's reason, and the label `auto-landed`

#### Scenario: The comment fails

- **GIVEN** a host that refuses the comment
- **WHEN** a unit lands
- **THEN** the failure is logged and the unit stays recorded `merged`

### Requirement: A digest card lists what auto-landed, and an auto unit that will not land is not hidden

A card of its own kind SHALL list the units that auto-landed in the last 24 hours with their classes and a link each, SHALL be shown
once with no reminder, and SHALL be cleared when none remain in the window. No card SHALL be raised per landed unit. A unit in review
whose recorded tier is `auto` SHALL raise a review card like a `light` unit unless the landing step will land it, which is when its
class is listed, not demoted and its forge merges; a unit that is only waiting for pending checks SHALL raise none.

#### Scenario: Two landings

- **GIVEN** two units that auto-landed this morning
- **WHEN** the cards are computed
- **THEN** there is one digest card listing both and no card for either alone

#### Scenario: No reminder

- **GIVEN** a digest card already shown
- **WHEN** the reminder interval passes
- **THEN** it is not shown again

#### Scenario: An auto unit in a class not listed

- **GIVEN** an `auto` unit in review whose class is not in `auto_land.classes`
- **WHEN** the cards are computed
- **THEN** it has a review card

#### Scenario: An auto unit that will land

- **GIVEN** an `auto` unit of a listed class waiting for pending checks
- **WHEN** the cards are computed
- **THEN** it has none

#### Scenario: No checks registered

- **GIVEN** an `auto` unit of a listed class declined for having no checks
- **WHEN** the cards are computed
- **THEN** it has a review card

### Requirement: A sampled share of landed units is put to a person afterwards

A landed unit SHALL be picked for audit when a number derived from a hash of its id and the commit it landed as, between 0 and 1, is
below `audit.sample_rate`, so the same unit and rate always give the same answer; a rate of 0 SHALL pick none and 1 SHALL pick every
one. A picked unit SHALL be recorded as awaiting audit and SHALL raise an audit card with a link to its pull request. `abk review audit
<unit> ok|wrong` SHALL record the result, clear the card and be refused for a unit not awaiting audit. `abk status` SHALL list audits
awaiting a result.

#### Scenario: Picked

- **GIVEN** a sample rate of 1
- **WHEN** a unit lands
- **THEN** it is awaiting audit and an audit card is raised

#### Scenario: Not picked

- **GIVEN** a sample rate of 0
- **WHEN** a unit lands
- **THEN** it is not awaiting audit

#### Scenario: A result

- **GIVEN** a unit awaiting audit
- **WHEN** a person runs `abk review audit <unit> ok`
- **THEN** the result is recorded and the card is cleared

#### Scenario: A unit not awaiting audit

- **WHEN** `abk review audit` names a unit that was not picked
- **THEN** it is refused and nothing is recorded

### Requirement: Auto-landed units enter the rates only when read or reverted

An auto-landed unit SHALL have an outcome derived by the rules for any merged unit and SHALL be recorded as landed by the pipeline. It
SHALL be a sample for the clean-merge rate and the agreement rate only when it was audited (`ok` counting as accepted and `wrong` as
not) or reverted (not accepted); an auto-landed unit neither audited nor reverted SHALL be no sample.

#### Scenario: Unaudited

- **GIVEN** an auto-landed unit never audited or reverted
- **WHEN** its class's rates are computed
- **THEN** it is not counted

#### Scenario: Audited ok

- **GIVEN** an auto-landed unit audited `ok`
- **WHEN** the rates are computed
- **THEN** it is one sample, accepted

#### Scenario: Reverted

- **GIVEN** an auto-landed unit later reverted
- **WHEN** the rates are computed
- **THEN** it is one sample, not accepted and not clean

### Requirement: `abk doctor` warns when auto-land has no server-side guard

When `auto_land.classes` is not empty, `abk doctor` SHALL warn for each repo whose forge reports no branch protection that the policy
hook is then the only guard and does nothing against the pipeline's own merge, and SHALL warn when the list is not empty and
`review.enabled` is false. With the list empty, the guard SHALL be reported as information, as before.

#### Scenario: No protection

- **GIVEN** a listed class and a repo whose forge reports no branch protection
- **WHEN** `abk doctor` runs
- **THEN** it warns for that repo

#### Scenario: Protected

- **GIVEN** a listed class and a repo with branch protection
- **WHEN** `abk doctor` runs
- **THEN** there is no warning for that repo

#### Scenario: Nothing listed

- **GIVEN** an empty list and a repo with no branch protection
- **WHEN** `abk doctor` runs
- **THEN** it reports the guard as information and does not warn
