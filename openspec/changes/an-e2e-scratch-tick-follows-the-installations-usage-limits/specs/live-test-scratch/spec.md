## ADDED Requirements

### Requirement: A live test's scratch tick does not judge usage unless the test is about the guard

The scratch setup of a live test for the Claude Code runtime SHALL start its tick with the usage guard off (`ABK_USAGE_GUARD=off`), whatever limits the installation that runs the tests has, so that the tick's build does not depend on a usage reading. A test about the guard SHALL be able to opt in, which leaves the setting out of the environment so the limits that test writes into its scratch configuration apply. The ACP setup SHALL be unchanged.

#### Scenario: The default scratch

- **WHEN** the scratch for the Claude Code runtime is made without an opt-in
- **THEN** its environment has `ABK_USAGE_GUARD` equal to `off`, and its configuration has no usage limits

#### Scenario: A test about the guard

- **WHEN** the scratch is made with the opt-in
- **THEN** its environment does not have the setting

#### Scenario: The ACP scratch

- **WHEN** the scratch for the ACP runtime is made
- **THEN** it has no usage setting and its configuration is as it was

### Requirement: A usage condition ends a live test as a skip that names it

When a scratch tick built no unit and the scratch's pause marker holds an unexpired pause of kind `usage` or `rate_limit`, the test SHALL be skipped, not failed. The reason SHALL contain the marker's reason (the reading and threshold of a usage pause, or the limit message of a rate-limit pause), say that usage is an environment condition, and say that the build was not attempted. A pause of kind `network`, a tick with no pause, an expired marker, and a tick that built its unit SHALL NOT be skipped by this rule. The rule SHALL be one function used by every live test that starts a scratch tick.

#### Scenario: A usage pause

- **GIVEN** a tick that built nothing and a pause marker of kind `usage` with reason `session usage at 91% (threshold 70%, live)`
- **WHEN** the test ends its tick
- **THEN** it is skipped with a reason containing `91%`, `70%`, that usage is an environment condition and that the build was not attempted

#### Scenario: A rate limit

- **GIVEN** a tick that built nothing and a pause marker of kind `rate_limit`
- **WHEN** the test ends its tick
- **THEN** it is skipped with the marker's reason

#### Scenario: A network pause or no pause

- **GIVEN** a tick that built nothing with a `network` marker, or with no marker
- **WHEN** the test ends its tick
- **THEN** it is not skipped by this rule and fails as it did

#### Scenario: Why a skip and not a failure

- **GIVEN** a usage condition that stopped the tick
- **WHEN** the run's failures are attributed
- **THEN** the test is counted as skipped, so it is neither repeated on the base as a failure nor sent to the agent as feedback
