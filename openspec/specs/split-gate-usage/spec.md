# split-gate-usage Specification

## Purpose
TBD - created by archiving change a-runtimes-provider-has-usage-windows. Update Purpose after archive.

## Requirements

### Requirement: A split's gate may name the provider of its model

A split entry `tests.e2e_splits.<name>` (and `rest`) SHALL accept `gate` with exactly one of `provider` and `command`. `gate.provider` SHALL take `name`, `budget_usd` and `limits`. `name` SHALL be a row of the
kit's provider table (the first row is `modal`); a name not in the table SHALL be refused when the configuration loads, naming the setting and the
names in the table. A row SHALL say which settings it requires; the `modal` row requires `budget_usd`, a number greater than zero, and a missing or
non-positive one SHALL be refused naming the setting. Any
other key under `provider` SHALL be refused. A `gate` with neither `provider` nor `command`, or with both, SHALL be refused naming the settings. The gate SHALL also accept `on_unknown`, `timeout_seconds`
(for a command), `usage_cache_minutes` and `usage_stale_retry_minutes`. A split without a `gate` SHALL behave as before, and the provider SHALL be a property of the split's gate, not of any runtime.

#### Scenario: A provider on a split

- **GIVEN** `tests.e2e_splits.acp.gate.provider: {name: modal, budget_usd: 200}`
- **WHEN** the configuration is loaded
- **THEN** it loads, `abk config --show` prints the setting, and no other split is affected

#### Scenario: A provider the table does not have

- **GIVEN** `gate.provider: {name: other, budget_usd: 50}`
- **WHEN** the configuration is loaded
- **THEN** it is refused, naming `gate.provider.name` and the names the table has

#### Scenario: The budget is missing or not positive

- **GIVEN** `gate.provider: {name: modal}`, or `budget_usd: 0`, or `budget_usd: -5`
- **WHEN** the configuration is loaded
- **THEN** it is refused, naming `budget_usd`

#### Scenario: One answer per gate

- **GIVEN** a gate with both `provider` and `command`, or with neither
- **WHEN** the configuration is loaded
- **THEN** it is refused, naming the settings

#### Scenario: An unknown key

- **GIVEN** `gate.provider: {name: modal, budget_usd: 200, budget: 5}`
- **WHEN** the configuration is loaded
- **THEN** it is refused, naming the key

### Requirement: The provider table reads usage through the provider's Python library

The provider table SHALL be one module of the runtimes level, the only place a provider's product name appears in framework code. Each row SHALL
give how to read usage, how to turn the result into a reading (an amount used, a window start and a window end) or into unknown, and a hint for a
person whose reading fails. The `modal` row SHALL read the workspace's billing summary through the provider's Python library, behind a small
function a test replaces, with the library imported only inside that function; it SHALL take `metered_cost` (a decimal) as the amount used and the
summary's `start` and `end` as the window, the end being exclusive. `billed_cost`, `adjustments` and `metered_cost_breakdown` SHALL NOT be used. Used
percent SHALL be `metered_cost` over `budget_usd`, rounded up to a whole percent and not capped at 100. Only when the summary has no `start` or no
`end` SHALL the window be the calendar month of the clock in UTC. A summary that lacks `metered_cost`, or holds one that is not a non-negative
decimal, SHALL give unknown with a reason saying which. The library not being installed SHALL give unknown with a reason that names the extra
`modal`; a call that raises (no login, no network, a refused call) SHALL give unknown with the error's class and message, with anything that looks
like a credential redacted. No reading SHALL be written to a log beyond the parsed figures and the reason.

#### Scenario: Used percent from the summary

- **GIVEN** a summary with `metered_cost` of 173.04285316 and a `budget_usd` of 200
- **WHEN** the usage is read
- **THEN** the amount used is 173.04285316, the used percent is 87, and a `billed_cost` of 142.99 and credits in `adjustments` change nothing

#### Scenario: The window comes from the summary

- **GIVEN** a summary with `start` 2026-10-01 00:00 UTC and `end` 2026-11-01 00:00 UTC
- **WHEN** the window is taken
- **THEN** it is that interval, and a clock at exactly the end is outside it

#### Scenario: A summary with no dates

- **GIVEN** a summary with no `start` or no `end`, and a clock at 2026-10-14 09:00 UTC, then another at 2026-12-31 23:30 UTC
- **WHEN** the window is taken
- **THEN** it is 2026-10-01 to 2026-11-01 and then 2026-12-01 to 2027-01-01, each ending 00:00 UTC

#### Scenario: A tiny amount

- **GIVEN** `metered_cost` of 2.3E-7
- **WHEN** the usage is read
- **THEN** the used percent is 1

#### Scenario: A summary that cannot be read

- **GIVEN** a summary with no `metered_cost`, or one of `"abc"` or -3
- **WHEN** the usage is read
- **THEN** the result is unknown, with a reason naming what was wrong

#### Scenario: The library is not installed

- **GIVEN** the library missing from the environment the tick runs in
- **WHEN** the usage is read
- **THEN** the result is unknown, the reason names the extra `modal`, and nothing else was imported to find out

#### Scenario: The call raises

- **GIVEN** the library installed and a call that raises an authentication error whose message holds a token
- **WHEN** the usage is read
- **THEN** the result is unknown, the reason holds the error's class and message with the token redacted, and the error does not propagate

#### Scenario: Nothing imports the library at import time

- **WHEN** every module of the kit is imported with the library absent
- **THEN** each imports without error, and the library is imported only when a reading is taken

### Requirement: The provider's library is an optional extra of the kit

The kit's `pyproject.toml` SHALL declare an optional extra named `modal` that holds the provider's library with a bounded version range and SHALL include the `acp` extra (by naming the kit with that extra), beside the
`acp` and `telemetry` extras, and its development dependency group SHALL include it (the extra bringing `acp` with it) so that a contributor's or the pipeline's `uv sync` has the package and unit-test can import it, never
needing an account: the library SHALL be importable in unit-test but never called without the injected fake. The lock SHALL be regenerated with the change to `pyproject.toml`. The extra SHALL be needed in the environment the tick runs in, which is the installation's own; the documents SHALL say so, say
how to add it (`uv sync --extra modal` in the installation, or `modal` named among the extras of the installation's dependency on the kit, which needs nothing else because the extra includes `acp`) and say what it pulls in.

#### Scenario: The extra is declared

- **WHEN** the kit's `pyproject.toml` is read
- **THEN** `[project.optional-dependencies]` holds `modal` with a range that has an upper bound, and the development group names it

#### Scenario: The extra includes acp

- **WHEN** the `modal` extra is resolved
- **THEN** it holds the packages of the `acp` extra as well, and the doctor's hint names only `modal`

#### Scenario: The development group has it

- **WHEN** the development group is resolved
- **THEN** it includes the `modal` extra, so the library and the `acp` packages are present after `uv sync`

#### Scenario: Unit-test needs no account

- **WHEN** the unit-test tests run in an environment with no credentials for the provider
- **THEN** they pass, the reading function being replaced by a fake that returns the library's own summary type or raises

### Requirement: The window limits apply to a split's provider window

`gate.provider.limits` SHALL be one window: `usage_pause_pct` (default
70), `usage_pause_ceiling_pct` (default: the pause percent, so the threshold does not move), `usage_relief_fraction` (default 0.25) and
`usage_resume_buffer_pct` (default 5), with the ranges, the ceiling check and the meaning they have for the Claude Code windows. The gate SHALL take `usage_cache_minutes` (default 15) and `usage_stale_retry_minutes` (default 5),
for a provider or a command. The settings that exist only for a subscription window
(`session`, `weekly`, the allowance settings and the estimate settings) SHALL be refused under `limits`, naming the setting. `limits` beside `gate.command` SHALL be refused, saying a command has no window. The Claude Code runtime's `limits` SHALL be unchanged.

#### Scenario: Limits on a split with a provider

- **GIVEN** `tests.e2e_splits.acp.gate.provider` set with `limits: {usage_pause_pct: 60, usage_pause_ceiling_pct: 90}`
- **WHEN** the configuration is loaded
- **THEN** it loads with the other limits at their defaults, and a ceiling of 50 is refused as it is for a Claude Code window

#### Scenario: A setting that only a subscription window has

- **GIVEN** the same gate with `limits: {weekly: {usage_pause_pct: 60}}` or `usage_unit_allowance_pct: 3`
- **WHEN** the configuration is loaded
- **THEN** it is refused, naming the setting and saying it belongs to the Claude Code runtime

#### Scenario: Limits with a command

- **GIVEN** `gate: {command: [probe], limits: {usage_pause_pct: 60}}`
- **WHEN** the configuration is loaded
- **THEN** it is refused, saying a command has no window for limits to mean anything

#### Scenario: Only the cache settings with a command

- **GIVEN** a gate with `command` and `usage_cache_minutes: 5`
- **WHEN** the configuration is loaded
- **THEN** it loads

#### Scenario: Claude Code is unchanged

- **GIVEN** `runtimes.claude_code.limits` with `session` and `weekly` sections
- **WHEN** the configuration is loaded
- **THEN** it loads as before

### Requirement: A provider's month is a window with the same threshold

For a split whose gate has a provider, the threshold at a moment SHALL be computed by the code that computes it for the Claude Code windows: the pause
percent until the last `usage_relief_fraction` of the window, then a straight line to the ceiling at the window's end, and the pause percent
throughout when the ceiling equals it. The split SHALL be held when used percent is at or above the threshold. A hold the gate wrote SHALL
stand until used percent plus `usage_resume_buffer_pct` is at or below the threshold, or until the window ends. Every split with a gate SHALL
be evaluated, whichever runtime the pipeline builds on. A reading SHALL NOT be used at or after the window end it assumed, and usage SHALL NOT be
estimated forward from a reading.

#### Scenario: Over the pause percent, before the ramp

- **GIVEN** a pause percent of 70, a ceiling of 90, a relief fraction of 0.25, a 31-day window, ten days after its start, and used percent 87
- **WHEN** the split is evaluated
- **THEN** the threshold is 70 and the split is held

#### Scenario: Under the pause percent

- **GIVEN** the same limits and used percent 40
- **WHEN** the split is evaluated
- **THEN** it is not held

#### Scenario: The threshold rises near the end

- **GIVEN** the same limits and a moment with the last quarter of a ramp span to go (1.9375 days of the 7.75 the ramp covers), used percent 87
- **WHEN** the split is evaluated
- **THEN** the threshold is 85, and the split is held; and at half a day before the end the threshold is 89 and, with used percent 80, the split is not held

#### Scenario: A standing hold lifts only with room

- **GIVEN** a gate hold standing, used percent 80, a resume buffer of 5, and the threshold at 84 and then at 85
- **WHEN** the split is evaluated at each
- **THEN** the hold stands at 84 and lifts at 85

#### Scenario: The month turns

- **GIVEN** a gate hold standing with its window ending at 2026-11-01 00:00 UTC
- **WHEN** it is 2026-11-01 00:01 and the reading taken before is all there is
- **THEN** that reading is not used, the hold's `until` has passed and it is gone, and a new reading is asked for

#### Scenario: Usage falls

- **GIVEN** a hold standing at used percent 87 and a configured `budget_usd` raised from 200 to 400
- **WHEN** the next reading is evaluated
- **THEN** used percent is 44 and the hold is lifted

#### Scenario: A split whose tests the build does not drive

- **GIVEN** the pipeline built on the Claude Code runtime and a split `acp` with a gate over its threshold
- **WHEN** a round runs
- **THEN** the `acp` split is evaluated and held, and the build is not affected

### Requirement: The result is a held-split entry, written by source

The evaluation of a split's gate SHALL write its result into the state that `abk e2e-test hold` writes
(`<state_dir>/e2e-held.json`) with `source: gate`, a reason that names the provider, the used percent, the budget and the threshold (or the command's reason), and an
`until` at the window's end (for a command, one cache time from its reading). It SHALL lift the entry when the rules above say so. It
SHALL write, replace and remove only entries whose source is `gate`: an entry set by hand, or a split with `hold: true`, SHALL NOT be replaced, shortened or removed by any reading. The evaluation SHALL run once in each round of the tick before e2e-test tests
are selected, and for `abk status --refresh`; `abk tick --dry-run` SHALL report what it would write and write nothing. A gate hold removed by
hand SHALL come back at the next evaluation while the usage is still over the threshold. An e2e-test step already running SHALL NOT be interrupted.

#### Scenario: A hold is written

- **GIVEN** a split over its threshold and no entry for it
- **WHEN** a round runs
- **THEN** an entry with `source: gate`, the reason and `until` at the next window end is written, and e2e-test selection leaves that split's tests out

#### Scenario: A hold lifts itself

- **GIVEN** a gate entry for a split and a reading that says there is room
- **WHEN** a round runs
- **THEN** the entry is removed and the split's tests are selected again

#### Scenario: A hand-set hold is never lifted by a reading

- **GIVEN** a split held by `abk e2e-test hold` with source `command`, and a reading far below the threshold
- **WHEN** rounds run
- **THEN** the entry is unchanged; and with a reading over the threshold it is not replaced either

#### Scenario: A split the configuration releases

- **GIVEN** a split with `hold: false` and a reading over the threshold
- **WHEN** a round runs
- **THEN** the entry may be written, and the split is not held, as the configuration wins; the status says so

#### Scenario: A split the configuration holds

- **GIVEN** a split with `hold: true` and a reading below the threshold
- **WHEN** a round runs
- **THEN** it stays held and no gate entry is written for it

#### Scenario: A dry run writes nothing

- **WHEN** `abk tick --dry-run` runs with a split over its threshold
- **THEN** it says `would hold: <split>` with the reason, and the state file is not changed

#### Scenario: A hold removed by hand

- **GIVEN** a gate hold removed with `abk e2e-test release` while usage is still over the threshold
- **WHEN** the next evaluation runs after the cache time
- **THEN** the entry is written again

### Requirement: An unreadable usage is unknown, never a pass

A result that cannot be read SHALL be unknown, with its reason, and SHALL be shown as unknown by `abk status` and `abk doctor`, never as usable. With
`gate.on_unknown: allow` (the default) an unknown result SHALL write nothing and lift nothing. With `hold` it SHALL write a gate
entry whose reason says the usage is unknown, with `until` `usage_stale_retry_minutes` away, renewed by each unknown evaluation, and lifted by the
first good reading. Any other value SHALL be refused when the configuration loads. A standing gate hold SHALL NOT be lifted by an unknown
result.

#### Scenario: Unknown with the default

- **GIVEN** no `on_unknown` and the provider's library not installed
- **WHEN** a round runs
- **THEN** no entry is written, the split's tests are selected, and `abk status` shows the usage as unknown with the reason

#### Scenario: Unknown that holds

- **GIVEN** `on_unknown: hold` and the same library missing
- **WHEN** a round runs
- **THEN** a gate entry saying the usage is unknown is written, and the first later reading that can be read replaces it with the real result

#### Scenario: Unknown does not lift a hold

- **GIVEN** a gate hold standing and an unreadable result
- **WHEN** a round runs
- **THEN** the hold stands until its `until` or a good reading

#### Scenario: A value that is neither

- **GIVEN** `on_unknown: maybe`
- **WHEN** the configuration is loaded
- **THEN** it is refused, naming the setting and the two values

### Requirement: A gate command answers for a provider the table does not know

`gate.command` SHALL be an argv, run without a shell and with stdin closed, with a timeout of `gate.timeout_seconds`
(default 30). Exit status 0 SHALL mean usable and any other status held, with the first line of standard output, trimmed, redacted and cut at 200
characters, as the reason (`gate command exited <n>` when it is empty). A command that cannot be started, or that runs past the timeout
(and is killed), SHALL give unknown. An empty argv SHALL be refused when the configuration loads. The result SHALL be handled as any provider result
is, including the cache time, with the entry's source `gate`.

#### Scenario: Usable

- **GIVEN** a command that exits 0
- **WHEN** the split is evaluated
- **THEN** it is usable and no entry stands for it

#### Scenario: Held with a reason

- **GIVEN** a command that prints `quota spent` and exits 3
- **WHEN** the split is evaluated
- **THEN** an entry with `source: gate` is written with the reason `quota spent`

#### Scenario: Held with no line

- **GIVEN** a command that exits 1 and prints nothing
- **WHEN** the split is evaluated
- **THEN** the reason is `gate command exited 1`

#### Scenario: Cannot be run or too slow

- **GIVEN** a command that does not exist, and another that sleeps past a timeout of one second
- **WHEN** each is evaluated
- **THEN** each gives unknown, the second having been killed

#### Scenario: Both ways at once

- **GIVEN** an empty argv, or `gate.command` beside `gate.provider`
- **WHEN** the configuration is loaded
- **THEN** it is refused

### Requirement: A reading is cached

A good reading SHALL be kept per split in the state directory for `usage_cache_minutes` (default 15), SHALL answer every reader and every process in
that time without asking the provider, and SHALL NOT be kept past its window's end. An unknown result SHALL be kept for `usage_stale_retry_minutes`
(default 5). The file SHALL be written whole under a lock. `abk status --refresh` and `abk doctor` SHALL read afresh. `abk status` without a refresh
SHALL ask no provider and run no command.

#### Scenario: Several readers within the time

- **GIVEN** a good reading taken three minutes ago and the default time
- **WHEN** a round, `abk status` and a second process ask
- **THEN** the provider is not asked

#### Scenario: The time has passed

- **GIVEN** a good reading taken sixteen minutes ago
- **WHEN** a round runs
- **THEN** the provider is asked and the reading replaced

#### Scenario: A failing provider is not asked every round

- **GIVEN** an unknown result taken two minutes ago
- **WHEN** three rounds run
- **THEN** the provider is not asked again until five minutes have passed

#### Scenario: A refresh

- **WHEN** `abk status --refresh` is run with a good reading in the cache
- **THEN** the provider is asked and the cache replaced

### Requirement: The status and the doctor show a split's gate usage

`abk status` SHALL show, for each split with a gate, a line with the split, the provider, used amount and percent against the budget, when
the window resets, the threshold now (and, while it moves, what it moves towards), whether the split is held or usable or the usage unknown, and
the source and age of the reading. For a command gate it SHALL show the result and its reason. When the provider's library is not installed the doctor SHALL print both forms of the fix, `uv sync --extra modal` run in the installation and naming `modal` among the extras of the installation's dependency on the kit (never `acp` as well: the extra includes it), without importing anything else; when it is installed and the call raises, the doctor SHALL print the error's class and message, redacted. `abk doctor` SHALL check each such split:
the library is importable, a reading can be taken, the budget is set, and say what to fix when it cannot (the table's hint); a hold that stands for a
gate reading is information, not a failure, and an unknown result is a warning.

#### Scenario: The status line

- **GIVEN** a split over its threshold
- **WHEN** `abk status` is run
- **THEN** it shows a line such as `gate usage: acp (modal) 173.04 of 200 USD (87%), threshold 70%, resets 11-01 00:00 UTC, held (provider reading, 4m old)`

#### Scenario: Unknown in the status

- **GIVEN** a provider whose library is missing or whose call raises
- **WHEN** `abk status` is run
- **THEN** the line says the usage is unknown with the reason, and does not say usable

#### Scenario: A split with no gate

- **WHEN** `abk status` and `abk doctor` are run for a workspace whose splits have no gate
- **THEN** no gate line or check appears

#### Scenario: The doctor

- **GIVEN** a provider whose library is not installed
- **WHEN** `abk doctor` runs
- **THEN** it warns that a reading cannot be taken, naming the split, and prints `uv sync --extra modal` and the extras form of the fix; and a standing gate hold is shown as information

#### Scenario: Installed but not logged in

- **GIVEN** the library installed and a call that raises
- **WHEN** `abk doctor` runs
- **THEN** it warns with the error's class and message, redacted, and no secret is printed
