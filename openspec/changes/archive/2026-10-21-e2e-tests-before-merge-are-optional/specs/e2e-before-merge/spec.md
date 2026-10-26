## ADDED Requirements

### Requirement: Whether the e2e-test tier runs before merge is a setting, global with a per-repo override

abk SHALL read a setting `e2e_before_merge` with the values `required` and `deferred`, from `global_limits` and, for one repo, from
that repo's `tests` block, where a repo's own value SHALL win and an unset value SHALL follow the global one. The default SHALL be
`required`. A value other than the two SHALL be refused when the configuration loads, naming the key, and `abk config` SHALL print
the setting in effect.

#### Scenario: The default

- **GIVEN** an `abk.yaml` that does not mention the setting
- **WHEN** it is loaded
- **THEN** every repo's value in effect is `required`

#### Scenario: A repo overrides the global value

- **GIVEN** `global_limits.e2e_before_merge: required` and a repo whose `tests` block says `deferred`
- **WHEN** the value is resolved for that repo and for another
- **THEN** it is `deferred` for the first and `required` for the second

#### Scenario: A global value is followed

- **GIVEN** `global_limits.e2e_before_merge: deferred` and a repo that does not set it
- **WHEN** the value is resolved for the repo
- **THEN** it is `deferred`

#### Scenario: An unknown value

- **GIVEN** `e2e_before_merge: later`
- **WHEN** the file is loaded
- **THEN** loading fails naming the key and the two values it accepts

### Requirement: With the tier required, a unit runs its e2e-test tier before merge as it does today

When the value in effect for a unit's repo is `required`, a unit of the e2e-test kind SHALL run the e2e node before its pull request
opens, and again when its base moves, with the behaviour it has without this setting, and SHALL record its e2e state as `passed` or
`failed`.

#### Scenario: Required

- **GIVEN** a unit of the e2e-test kind in a repo that requires the tier
- **WHEN** review approves it
- **THEN** the e2e node runs before the push, and the unit's e2e state is `passed` when it passes

### Requirement: With the tier deferred, a unit skips the e2e node before merge and records that it did

When the value in effect for a unit's repo is `deferred`, a unit of the e2e-test kind SHALL NOT run the e2e node after review
approves it, and SHALL NOT run it again when its base moves, and SHALL record its e2e state as `deferred`. A scheduled run of the
whole suite SHALL NOT be affected. A unit of the unit-test kind SHALL record `not-required`. A rework that pushes again SHALL reset
the state for the head it pushes.

#### Scenario: Deferred

- **GIVEN** a unit of the e2e-test kind in a repo that defers the tier
- **WHEN** review approves it
- **THEN** the e2e node does not run, the e2e lock is not taken, the unit is pushed and its pull request opened, and its e2e state is `deferred`

#### Scenario: The base moved

- **GIVEN** the same unit and a base that moved after approval
- **WHEN** the unit is moved onto the new base
- **THEN** the e2e node does not run again and the unit goes on to its next step

#### Scenario: A scheduled run

- **GIVEN** a scheduled whole-suite run in a repo that defers the tier
- **WHEN** it runs
- **THEN** the e2e node runs

#### Scenario: A unit-test unit

- **WHEN** a unit of the unit-test kind reaches review in any repo
- **THEN** its e2e state is `not-required`

#### Scenario: A reworked unit

- **GIVEN** a deferred unit that is reworked and pushed again
- **WHEN** the new head is pushed
- **THEN** its e2e state belongs to the new head and is `deferred` again

### Requirement: The pull request says the e2e-test tier was deferred

The pull request body of a unit whose e2e state is `deferred` SHALL say "e2e-test deferred to verify" in its verification section,
SHALL say that the live tests run after the merge against the deployed change and that a failure is found then, and SHALL keep that
section when the body is shortened to fit a host's limit.

#### Scenario: The body

- **WHEN** the body of a deferred unit is built
- **THEN** the verification section holds "e2e-test deferred to verify" and no e2e results

#### Scenario: A long description

- **GIVEN** a deferred unit with a description far over the host's limit
- **WHEN** the body is built to fit
- **THEN** the deferred text is still in it

### Requirement: `verify` runs the live tests after the merge as it does today, and names deferred units when it fails

`verify` SHALL deploy and run the live tests and the acceptance run of a change after its units have merged, whatever any unit's e2e
state, with no change to what it selects or runs. When a verification fails and one or more of the change's units recorded their e2e
state as `deferred`, the failure's detail SHALL name those units.

#### Scenario: A change with a deferred unit

- **GIVEN** a change whose units merged, one of them with a deferred e2e state
- **WHEN** `verify` runs
- **THEN** it deploys and runs the same live tests it would have run otherwise

#### Scenario: A failure after a deferral

- **GIVEN** that verification fails
- **WHEN** its result is recorded
- **THEN** the detail names the unit that deferred its e2e

#### Scenario: A failure with no deferral

- **GIVEN** a change in which no unit deferred
- **WHEN** verification fails
- **THEN** the detail is as it is today
