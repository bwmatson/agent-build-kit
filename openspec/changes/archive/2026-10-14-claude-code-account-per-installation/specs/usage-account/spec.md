## ADDED Requirements

### Requirement: The usage guard reads the credentials of the account in use

With an account set, the guard SHALL read the stored OAuth token and its expiry from `<account directory>/.credentials.json` and not
from `~/.claude/.credentials.json`. With none set it SHALL read the default file as before. A `CLAUDE_CODE_OAUTH_TOKEN` in the
process environment SHALL still be read first, as before. A path given to a reader SHALL win over both.

#### Scenario: The account's credentials

- **GIVEN** the setting `<dir>`, a token in `<dir>/.credentials.json` and another in the default credentials file
- **WHEN** the guard reads the token and its expiry
- **THEN** it reads the token and the expiry of `<dir>`

#### Scenario: Default account

- **GIVEN** the setting is not set
- **WHEN** the guard reads the token
- **THEN** it reads the default credentials file, whose path a test may replace as it does now

#### Scenario: The environment's token still wins

- **GIVEN** the setting `<dir>` and `CLAUDE_CODE_OAUTH_TOKEN` set
- **WHEN** the guard reads the token
- **THEN** it is the environment's, as before

#### Scenario: A refresh after an expired token

- **GIVEN** the setting `<dir>` and an expired token in `<dir>/.credentials.json`
- **WHEN** the guard refreshes the login and reads the token again
- **THEN** the refresh call carries `CLAUDE_CONFIG_DIR=<dir>` and the second read is of `<dir>`'s file

### Requirement: The fallback and the fresh block come from the account's own state file

With an account set, the reading taken from Claude Code's own cache (the `cachedUsageUtilization` block) SHALL be read from
`<account directory>/.claude.json`, and the default account's `~/.claude.json` SHALL NOT be read, by the fresh-block decision, by the
stale fallback, by the held reading and by the usage status. With none set it SHALL be read from `~/.claude.json` as before. The
`usage_claude_cache_minutes: 0` switch SHALL keep turning off the fresh block alone.

#### Scenario: The account's state file

- **GIVEN** the setting `<dir>`, a fresh block in `<dir>/.claude.json` and a different one in `~/.claude.json`
- **WHEN** the guard decides a start, and then when it reads the held reading
- **THEN** each uses the block of `<dir>` and the default file is not opened

#### Scenario: The stale fallback

- **GIVEN** the setting `<dir>`, no live reading and no kept one, and a block only in `~/.claude.json`
- **WHEN** the current usage is read
- **THEN** there is no reading, and the default file is not opened

#### Scenario: Default account

- **GIVEN** the setting is not set and a fresh block in `~/.claude.json`
- **WHEN** the guard decides a start
- **THEN** it decides from that block, with the source `claude.json`, as before

#### Scenario: The fresh block switched off

- **GIVEN** the setting `<dir>` and `usage_claude_cache_minutes: 0`
- **WHEN** the guard decides a start
- **THEN** the fresh block is not read, and the stale fallback still reads `<dir>/.claude.json`

### Requirement: A kept reading belongs to one account

The kept reading in `usage-cache.json` SHALL record the account it came from when an account is set. A kept reading, cool-down or
fallback whose recorded account differs from the one in use, or that records none while one is in use, SHALL be discarded, never
served and never extended, and the next successful call SHALL replace it. A file written with no account SHALL be served only to the
default account, so an installation with no account set is unchanged.

#### Scenario: A reading of another account is discarded

- **GIVEN** the cache holds a fresh reading recorded for `<a>` and the setting is `<b>`
- **WHEN** the guard reads usage
- **THEN** the cached reading is not served, a call is made, and the file then records `<b>`

#### Scenario: A cool-down of another account is discarded

- **GIVEN** the cache holds a cool-down recorded for `<a>`, the setting is `<b>`
- **WHEN** the guard reads usage
- **THEN** no cool-down is in force and a call is made

#### Scenario: An old file with no account

- **GIVEN** a cache written before accounts existed
- **WHEN** it is read with the setting `<dir>`, and then with no setting
- **THEN** it is discarded for `<dir>` and served for the default account

#### Scenario: The default account writes what it wrote

- **GIVEN** no setting and a good answer
- **WHEN** the cache is written
- **THEN** its fields are those of the endpoint's payload and `fetched_at`, with no account field

### Requirement: The calibration of the allowances restarts when the account changes

Each line of the usage call record SHALL record the account directory in use (null for the default). The calibration of the per-unit
allowances SHALL pair only readings recorded after the last line of a different account, so points gained on one account are never
paired with a reading of another. The cache interval and the rate-limit figures SHALL still read every line.

#### Scenario: A change restarts the pairs

- **GIVEN** a record with ten usable pairs for `<a>` followed by readings for `<b>`, and the setting `<b>`
- **WHEN** the allowances are calibrated
- **THEN** only the pairs among the `<b>` readings count, and with too few the configured allowance stands

#### Scenario: One account throughout

- **GIVEN** a record whose lines all name `<a>` (or all name none) and the setting the same
- **WHEN** the allowances are calibrated
- **THEN** the pairs are those that would have been used before this requirement

#### Scenario: The rate figures read every line

- **GIVEN** a record of two accounts
- **WHEN** the cache interval and the call rate are derived
- **THEN** they count the lines of both

### Requirement: `abk status` names the account the usage belongs to

The usage line of `abk status` SHALL name the account directory when an account is set, after the readings and their source, and when
there is no reading SHALL say whose reading is missing. With no account set the line SHALL be as before.

#### Scenario: A set account

- **GIVEN** the setting `<dir>` and a reading
- **WHEN** `abk status` prints its usage line
- **THEN** the line ends with the reading's source and age and names `<dir>`

#### Scenario: No reading

- **GIVEN** the setting `<dir>` and no reading
- **WHEN** `abk status` prints its usage line
- **THEN** it says `usage: unknown` and names `<dir>`

#### Scenario: Default account

- **GIVEN** no setting
- **WHEN** `abk status` prints its usage line
- **THEN** the line is the one printed before this requirement
