## ADDED Requirements

### Requirement: The configuration names the runtimes that are blocked, allowed and run by the schedule

`abk.yaml` SHALL take, at the top of the file under `tests`, the lists `runtimes_blocked`, `runtimes_allowed` and `e2e_runtimes`, each defaulting to empty, and a repo SHALL take its own `tests.e2e_runtimes` that, when set, replaces the top-level one for that repo. Each name SHALL be a runtime the registry, the protocol runtime or the file's own `runtimes` entries name. An unknown name, the name `base`, a repeated name, and a runtime named in both `runtimes_blocked` and `runtimes_allowed` SHALL be refused when the configuration loads, naming the setting. `abk config --show` SHALL show the lists set.

#### Scenario: The defaults

- **GIVEN** a configuration with no `tests` block
- **WHEN** it is loaded
- **THEN** the three lists are empty and a repo's variants are only `base`

#### Scenario: A name nothing knows

- **GIVEN** `tests.runtimes_blocked: [nothing]`
- **WHEN** the configuration is loaded
- **THEN** it is refused with a message naming the setting and the runtimes there are

#### Scenario: Blocked and allowed at once

- **GIVEN** `acp` in both `runtimes_blocked` and `runtimes_allowed`
- **WHEN** the configuration is loaded
- **THEN** it is refused naming both settings

#### Scenario: A repo's own list

- **GIVEN** a top-level `e2e_runtimes` of `acp` and one repo whose `tests.e2e_runtimes` is `claude_code`
- **WHEN** the repo's variants are read
- **THEN** they are `base` and `claude_code`

### Requirement: The blocked runtimes are the configuration's and the state file's together, and the configuration wins

The runtimes blocked now SHALL be those in `tests.runtimes_blocked` together with those with an unexpired entry in `e2e-blocked.json` in the state directory, except that a runtime in `tests.runtimes_allowed` SHALL NOT be blocked whatever the file says. A runtime the configuration blocks SHALL be blocked whatever the file holds. An entry SHALL carry its reason, the time it was written, an optional deadline (set only by the provider and availability sources, never by `abk e2e-test block`), its source (`command`, `provider` or `availability`) and who wrote it. An entry whose deadline has passed or is now SHALL NOT block. A configuration entry SHALL have no deadline. A file that cannot be read SHALL block nothing and SHALL be reported as unreadable, and an entry naming an unknown runtime SHALL be ignored and reported. Reading SHALL change nothing on disk, and writing SHALL be atomic under a lock.

#### Scenario: Blocked by the configuration alone

- **GIVEN** `acp` in `tests.runtimes_blocked` and no file
- **WHEN** the blocked set is read
- **THEN** `acp` is blocked, with the origin the configuration

#### Scenario: Blocked by the file alone

- **GIVEN** an unexpired file entry for `acp` and no configuration entry
- **WHEN** the blocked set is read
- **THEN** `acp` is blocked, with the entry's reason and deadline and the origin the file

#### Scenario: The configuration allows what the file blocks

- **GIVEN** an unexpired file entry for `acp` and `acp` in `tests.runtimes_allowed`
- **WHEN** the blocked set is read
- **THEN** `acp` is not blocked, and the result names the file's entry as overridden

#### Scenario: The configuration blocks what the file does not

- **GIVEN** `acp` in `tests.runtimes_blocked` and a file with no entry, or an expired one
- **WHEN** the blocked set is read
- **THEN** `acp` is blocked

#### Scenario: A deadline lifts a block

- **GIVEN** a file entry whose deadline is in the past
- **WHEN** the blocked set is read
- **THEN** the runtime is not blocked, and a deadline in the future still blocks it and is reported

#### Scenario: A file that cannot be read

- **GIVEN** a `e2e-blocked.json` that is not valid JSON
- **WHEN** the blocked set is read
- **THEN** nothing is blocked by it, and the file is reported as unreadable

### Requirement: `abk e2e-test hold`, `release` and `status` change both places

`abk e2e-test hold <split> [--reason TEXT]` SHALL take no deadline (a hand-set hold ends only with `release`) and SHALL set `hold: true` on the split's entry in `abk.yaml` by editing the file as text, and SHALL write the file entry, with no deadline, with the reason, the time, the source `command` and the user, both in one operation: both are written or neither. `abk e2e-test release <split>` SHALL remove the entry from the file and `hold: true` from the configuration; it SHALL say plainly when the split is still held afterwards by a `gate` entry its gate may recreate or by a hand-written configuration line it could not remove. The text edit SHALL keep every comment and every other line, SHALL copy the original once to a backup beside the file, and SHALL write through a temporary file. When the file cannot be edited that way (a duplicate key, an anchor, a multi-line flow entry, a value that is not a mapping, text that does not parse, a file that cannot be written) the command SHALL write nothing at all, exit non-zero, and print the reason and the line to add or remove by hand. A name that is neither a declared split nor `rest` SHALL be refused, and an argument `--until` SHALL be an unknown argument. `abk e2e-test status` SHALL list each declared split and `rest` as usable or held with the reason, the deadline and the origin, a split the configuration releases although the file holds it, and the splits the schedule runs. These commands share the `e2e-test` command group with `abk e2e-test check` of `tier2-splits-replace-runtime-tags`, which defines the held set and the text edit they use.

#### Scenario: Hold a split

- **GIVEN** a configuration with comments that declares the split `acp`
- **WHEN** `abk e2e-test hold acp --reason "model backend out of budget"` runs
- **THEN** `hold: true` is set on its entry as text, every other line is unchanged, a backup of the original exists, and the file holds the entry with the reason

#### Scenario: Hold writes both

- **WHEN** `abk e2e-test hold acp` runs on a file that can be edited
- **THEN** `acp` has `hold: true` and the file holds its entry with no deadline, and a repeated `hold` keeps one entry

#### Scenario: Release a split

- **GIVEN** `acp` held by `abk e2e-test hold`
- **WHEN** `abk e2e-test release acp` runs
- **THEN** `acp` has no `hold: true` and is not in the file

#### Scenario: Release says what still holds

- **GIVEN** `acp` held by a `gate` entry the command cannot own, or by a configuration line it could not remove
- **WHEN** `abk e2e-test release acp` runs
- **THEN** it says plainly that `acp` is still held, by what, and that the gate may write its entry again

#### Scenario: The file cannot be edited

- **GIVEN** a configuration whose entry for `acp` is a multi-line flow mapping
- **WHEN** `abk e2e-test hold acp` runs
- **THEN** neither the file nor the configuration is changed, the exit is non-zero, and the exact reason and the line to add by hand are printed

#### Scenario: No deadline

- **WHEN** `abk e2e-test hold acp --until 2026-11-01` runs
- **THEN** it exits 2 as an unknown argument

#### Scenario: A name nothing declares

- **WHEN** `abk e2e-test hold nothing` runs
- **THEN** it exits 2 naming the declared splits and `rest`

### Requirement: What is held is visible

`abk status` SHALL print one line for each held split with its reason and deadline and none when nothing is held. `abk doctor` SHALL report the held splits as information, a split the file holds and the configuration releases (`hold: false`) as a warning, an unreadable file as a failure, and an entry naming an undeclared split as a warning.

#### Scenario: Nothing held

- **WHEN** `abk status` runs with no held split
- **THEN** it prints no e2e-test split line

#### Scenario: A conflict

- **GIVEN** a file entry for `acp` and `hold: false` on `acp`
- **WHEN** `abk doctor` runs
- **THEN** it warns that the configuration releases what the file holds and that the configuration wins
