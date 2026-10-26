## ADDED Requirements

### Requirement: How long a unit waits for the tier 2 lock is a setting

The longest a tier 2 step waits for the tier 2 lock before failing as busy SHALL be the setting `limits.tier2_lock_wait_seconds`, a positive whole
number of seconds that defaults to 5400. The tier 2 runner and post-merge verification, when it is given no wait of its own, SHALL both use it. A
value that is zero, negative or not a whole number SHALL be refused when the config is loaded, with a message that names the key. The failure for a
wait that ends SHALL state the seconds waited and, when they came from the setting, the setting's name. The setting SHALL appear in the output of
`abk config --show`.

#### Scenario: The default

- **GIVEN** a config that does not set `limits.tier2_lock_wait_seconds`
- **WHEN** it is loaded
- **THEN** the wait is 5400 seconds

#### Scenario: A configured value is used by both callers

- **GIVEN** `limits.tier2_lock_wait_seconds` set to a number
- **WHEN** a unit's tier 2 step and a post-merge verification that was given no wait of its own each find the lock held
- **THEN** each waits that many seconds before reporting the lock busy

#### Scenario: A value that cannot be a wait

- **GIVEN** `limits.tier2_lock_wait_seconds` set to zero, to a negative number, or to a value that is not a whole number
- **WHEN** the config is loaded
- **THEN** loading fails with a message that names `limits.tier2_lock_wait_seconds`, and no unit starts

#### Scenario: The busy message names the setting

- **GIVEN** a lock held for longer than the configured wait
- **WHEN** the wait ends
- **THEN** the failure says how many seconds were waited and names `limits.tier2_lock_wait_seconds`

#### Scenario: The setting is shown

- **GIVEN** a config with or without the setting
- **WHEN** `abk config --show` is run
- **THEN** it lists `tier2_lock_wait_seconds` under `limits` with the value in force
