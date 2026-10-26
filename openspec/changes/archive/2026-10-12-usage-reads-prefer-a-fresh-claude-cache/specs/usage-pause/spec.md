## MODIFIED Requirements

### Requirement: The usage endpoint is asked only when a fresh reading could change a decision

For a decision to start work or to resume paused work, the guard SHALL use the reading it holds when that
reading settles the decision, and SHALL ask the endpoint only when a fresh reading could change it. A refusal made on a reading of
a window that has not reset SHALL stand without a call, an allowance SHALL stand while the usage could not have reached the
threshold since the reading, and a reading of a window that has reset SHALL not be used. Before the endpoint is asked, a fresh reading
in Claude Code's own usage cache SHALL be used when the usage-pause requirement for it applies.

#### Scenario: Far from the threshold

- **GIVEN** a reading of twenty percent used, a threshold of ninety-two and three hours to the reset
- **WHEN** a unit asks to start, even though the cached reading is older than the cache time
- **THEN** it is allowed and the endpoint is not called

#### Scenario: A window already used up

- **GIVEN** a reading at or over the threshold in a window that has not reset
- **WHEN** units ask to start
- **THEN** they are refused without a call, until the time the threshold is worked out to reach the reading or the window resets

#### Scenario: Close to the threshold

- **GIVEN** a reading whose headroom is less than the usage that could have been added since it was taken
- **WHEN** a unit asks to start
- **THEN** the endpoint is asked

#### Scenario: The window has reset

- **GIVEN** a reading whose window reset has passed
- **WHEN** a unit asks to start
- **THEN** the endpoint is asked

#### Scenario: No reading

- **WHEN** the guard holds no reading
- **THEN** the endpoint is asked

#### Scenario: A fresh reading in Claude Code's own cache

- **GIVEN** no reading of the guard's own that settles the decision, and a block in Claude Code's own cache fetched four minutes ago
- **WHEN** a unit asks to start
- **THEN** the decision is made from that block and the endpoint is not asked

## ADDED Requirements

### Requirement: A fresh reading in Claude Code's own cache is used before the endpoint is asked

Before the guard asks the endpoint, it SHALL read the usage block in Claude Code's own cache (`cachedUsageUtilization` in
`~/.claude.json`) and SHALL decide from it, making no call, when the block was fetched within `usage_claude_cache_minutes`
(by its `fetchedAtMs`, never by the file's modification time), describes both windows, has no window past its reset, and is fresher than the
reading kept in the guard's own cache, a tie going to the guard's own. When both cached readings are fresh the fresher SHALL be used. The
reading SHALL be judged like any other (thresholds, ramp and relief), so a fresh block over a threshold refuses and pauses as an actual
reading does, and a decision from it SHALL be made without a call even when the minimum interval holds the endpoint back. A block that is
older than the window, past a reset, missing, unreadable, torn or malformed SHALL read as absent, silently, and never as zero usage. The
block carries no credits state, so the credits and spend-limit rules SHALL NOT fire on a reading from it.

#### Scenario: A fresh block is used

- **GIVEN** a block fetched six minutes ago with the session at 20% and the weekly at 31%, a window of fifteen minutes, and a reading in the guard's own cache older than the cache time
- **WHEN** a unit asks to start
- **THEN** it is allowed from the block, the endpoint is not called, and the guard's own cache file is not changed

#### Scenario: A block older than the window

- **GIVEN** a block fetched twenty minutes ago and a window of fifteen minutes
- **WHEN** a unit asks to start
- **THEN** the block is not used and the decision is made as it is without the step

#### Scenario: Only the fetch time counts

- **GIVEN** a file modified a minute ago whose block was fetched two days ago
- **WHEN** a unit asks to start
- **THEN** the block is not used

#### Scenario: The block is fresher than the guard's own reading

- **GIVEN** a reading in the guard's own cache nine minutes old and a block six minutes old, both within the window
- **WHEN** a unit asks to start
- **THEN** the block is the reading used

#### Scenario: The block is older than the guard's own reading

- **GIVEN** a reading in the guard's own cache three minutes old and a block six minutes old, both within the window
- **WHEN** a unit asks to start
- **THEN** the guard's own reading is used

#### Scenario: A tie

- **GIVEN** a reading in the guard's own cache and a block observed at the same moment
- **WHEN** a unit asks to start
- **THEN** the guard's own reading is used

#### Scenario: A window in the block has reset

- **GIVEN** a block fetched six minutes ago whose session window reset three minutes ago
- **WHEN** a unit asks to start
- **THEN** the block is not used

#### Scenario: An unreadable block

- **GIVEN** a Claude Code file that is missing, is not valid JSON, is cut off part way, has no usage block, has one window only, or has a fetch time that is not a number
- **WHEN** a unit asks to start
- **THEN** the block reads as absent, nothing is logged for it, no usage is taken as zero, and the decision is made as it is without the step

#### Scenario: A fresh block over a threshold

- **GIVEN** a block fetched six minutes ago with the session at 95% against a threshold of 92%
- **WHEN** a unit asks to start
- **THEN** it is refused and paused until the window's relief, as an actual reading would, and the endpoint is not called

#### Scenario: Inside the minimum interval

- **GIVEN** a call made two minutes ago, so that the minimum interval has not passed, and a fresh block that allows
- **WHEN** a unit asks to start
- **THEN** it is allowed from the block and not refused for the time left to the next permitted call

#### Scenario: The credits rule does not fire

- **GIVEN** a fresh block with the session at 20% and the weekly at 31%
- **WHEN** a unit asks to start
- **THEN** it is decided by the thresholds alone, as a reading from the fallback is

#### Scenario: The status command

- **GIVEN** a fresh block fresher than the reading held in the guard's own cache
- **WHEN** the status command is run without a refresh
- **THEN** it prints the block's reading with its age and source, and makes no call

### Requirement: A reading from Claude Code's own cache is only a reading

A reading taken from Claude Code's own cache for this rule SHALL NOT be written to the guard's own cache, SHALL NOT start a cool-down,
SHALL NOT move the time a reading is kept or the time of the next permitted call, SHALL NOT be the base of an estimate, and SHALL NOT
count as a call to the endpoint in the record's refusal and safe-interval figures. The pipeline SHALL NOT write to Claude Code's file.

#### Scenario: The guard's own cache is untouched

- **GIVEN** a fresh block used for a decision
- **WHEN** the guard's own cache file is read afterwards
- **THEN** it holds what it held before, with no new reading and no cool-down

#### Scenario: The next permitted call

- **GIVEN** a call to the endpoint ten minutes ago and a decision answered from a fresh block one minute ago
- **WHEN** the time of the next permitted call is worked out
- **THEN** it is the same as if no decision had been answered from the block

#### Scenario: A stale block is no base

- **GIVEN** a block older than the window and no reading kept in the guard's own cache
- **WHEN** a unit asks to start with the endpoint refusing
- **THEN** the block is not used to estimate anything and the stale rule applies to it as today

### Requirement: A reading from Claude Code's own cache says where it came from and is counted apart

A decision from the block SHALL say so: the reason and the status command give the source `claude.json` and the block's age, for example
`usage: session 20%/92%, weekly 31%/80% (claude.json, 6m old)`. The call record SHALL gain a line for it with the outcome `claude-json`,
the caller and the block's age, held to the same rules as every other line. The call-rate line SHALL count the share answered from it
separately from the cache's: `usage calls: N in the last hour, K refused, P% from the cache, Q% from claude.json, safe interval S`.

#### Scenario: The label

- **WHEN** a start is decided from a fresh block six minutes old
- **THEN** the reason and the status command end `(claude.json, 6m old)`

#### Scenario: The record

- **WHEN** a start is answered from a fresh block
- **THEN** the record gains a line with the outcome `claude-json`, the caller and the block's age in seconds, and no status code or token

#### Scenario: The rate line

- **GIVEN** in the last hour three calls to the endpoint, four answers from the guard's own cache and five from the block
- **WHEN** the call-rate line is printed
- **THEN** it says 33% from the cache and 42% from claude.json, and the two shares are not added together

### Requirement: The time Claude Code's own cache is trusted is a setting

The time a block in Claude Code's own cache is used for a decision SHALL be `usage_claude_cache_minutes`, which SHALL default to
`usage_cache_minutes`, SHALL be refused when below zero, and SHALL turn the step off when it is zero, so that the read order is as it
was before this requirement. Its effective value SHALL NOT exceed the age past which a cached reading from Claude Code's own cache is
refused as stale.

#### Scenario: The default

- **GIVEN** no value set and `usage_cache_minutes` of fifteen
- **WHEN** the setting is read
- **THEN** it is fifteen minutes

#### Scenario: Zero turns it off

- **GIVEN** a value of zero and a block fetched a minute ago
- **WHEN** a unit asks to start
- **THEN** the block is not used and the order of readings is as before

#### Scenario: A negative value

- **WHEN** the value is below zero
- **THEN** the configuration is refused

#### Scenario: A value above the stale age

- **GIVEN** a value of ninety minutes and a block fetched seventy minutes ago
- **WHEN** a unit asks to start
- **THEN** the block is not used, since it is older than the age after which a reading from Claude Code's own cache is refused as stale
