# review-verdict-e2e-state Specification

## Purpose
TBD - created by archiving change e2e-tests-before-merge-are-optional. Update Purpose after archive.

## Requirements

### Requirement: The verdict reads a unit's e2e result as one of four states

The verdict SHALL take a unit's e2e gate as one of `passed`, `deferred`, `failed` and `not-required`. `failed` SHALL give a floor of
`full`. `deferred` SHALL give a floor of `light` in the evidence tier, and SHALL give no floor when
`review.auto_land.allow_deferred_e2e` is true. `passed` and `not-required` SHALL give no floor. A unit of the e2e-test kind with no
recorded state SHALL be read as pending while the e2e gate has not yet run, which gives no floor in an interim verdict (one computed
after a review round) and is a missing gate result in a final verdict (the round that approves), which gives `full`; a unit of the
unit-test kind with none SHALL be read as `not-required`. A floor SHALL only raise the tier.

#### Scenario: A deferred e2e

- **GIVEN** a unit with every other gate green, no flag, no protected path, classification `auto` and a class with a clean record, whose e2e state is `deferred`
- **WHEN** the verdict is computed
- **THEN** the tier is `light` and the reason says the e2e result was deferred to verify

#### Scenario: A failed e2e

- **GIVEN** a unit whose e2e state is `failed`
- **WHEN** the verdict is computed
- **THEN** it is `full` and the reason names the failed e2e result

#### Scenario: A passed e2e

- **GIVEN** the same unit with the e2e state `passed`
- **WHEN** the verdict is computed
- **THEN** the e2e result adds no floor and the tier is `auto`

#### Scenario: A unit-test unit

- **GIVEN** a unit of the unit-test kind with state `not-required`
- **WHEN** the verdict is computed
- **THEN** the e2e result adds no floor

#### Scenario: A record from before the setting

- **GIVEN** a unit of the e2e-test kind stored with no e2e state
- **WHEN** the final verdict is computed
- **THEN** the gate is read as missing and the tier is `full`

#### Scenario: Not yet run, in an interim verdict

- **GIVEN** a unit of the e2e-test kind whose e2e gate has not yet run, after a review round that asks for changes
- **WHEN** the interim verdict is computed
- **THEN** the e2e gate adds no floor

### Requirement: A deferred e2e result reaches `auto` only when the policy allows it

The `review.auto_land` block SHALL accept a boolean `allow_deferred_e2e`, false by default, and no other section SHALL accept it. A
unit whose e2e state is `deferred` SHALL NOT have the verdict `auto` unless it is true. When it is true, `deferred` SHALL behave as
`passed`. A deferred result SHALL NOT lower a tier any other floor has set.

#### Scenario: The default

- **GIVEN** a policy that does not mention the key
- **WHEN** the policy is loaded
- **THEN** `allow_deferred_e2e` is false

#### Scenario: Allowed

- **GIVEN** `allow_deferred_e2e: true` and a unit that is green in every other respect with a deferred e2e
- **WHEN** the verdict is computed
- **THEN** the e2e result adds no floor

#### Scenario: Another floor still holds

- **GIVEN** `allow_deferred_e2e: true` and a deferred unit that changed a protected path
- **WHEN** the verdict is computed
- **THEN** the tier is `full`

#### Scenario: The key in another place

- **GIVEN** `allow_deferred_e2e` set under `review` and not under `auto_land`
- **WHEN** the configuration loads
- **THEN** it is refused as an unknown key
