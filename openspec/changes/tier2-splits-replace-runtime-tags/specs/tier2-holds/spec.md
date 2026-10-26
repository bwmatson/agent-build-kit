## ADDED Requirements

### Requirement: The held splits are the configuration's and the state file's together, and the configuration wins

A split SHALL be held when its entry has `hold: true`, or when it has no `hold` and an unexpired entry for it is in `e2e-held.json` in the state directory. A split with `hold: false` SHALL NOT be held whatever the file says, and a split with `hold: true` SHALL be held whatever the file holds. `rest` SHALL be held the same ways as a declared split. An entry SHALL carry its reason, the time it was written, its source (`command` for a hold set by hand, `gate` for one a split's gate wrote) and who wrote it; it SHALL carry a deadline only when its source is `gate`, and the writer SHALL refuse a deadline on a `command` entry. An entry whose deadline has passed or is now SHALL NOT hold. A configuration entry SHALL have no deadline. An entry whose source the code does not know SHALL hold and SHALL be shown as written. A file that cannot be read SHALL hold nothing and SHALL be reported as unreadable, and an entry naming a split nothing declares SHALL be ignored and reported. Reading SHALL change nothing on disk; writing and removing an entry SHALL be atomic under a lock. A file named `e2e-blocked.json` SHALL NOT be read.

#### Scenario: Held by the configuration alone

- **GIVEN** `hold: true` on `acp` and no file
- **WHEN** the held set is read
- **THEN** `acp` is held, with the origin the configuration

#### Scenario: Held by the file alone

- **GIVEN** an unexpired file entry for `acp` and no `hold` on its entry
- **WHEN** the held set is read
- **THEN** `acp` is held, with the entry's reason, source and deadline and the origin the file

#### Scenario: The configuration releases what the file holds

- **GIVEN** an unexpired file entry for `acp`, of source `command` or `gate`, and `hold: false` on `acp`
- **WHEN** the held set is read
- **THEN** `acp` is not held and the result names the file's entry as overridden

#### Scenario: The configuration holds what the file does not

- **GIVEN** `hold: true` on `acp` and no entry, or an expired one
- **WHEN** the held set is read
- **THEN** `acp` is held

#### Scenario: A deadline

- **GIVEN** a `gate` entry whose deadline is in the past or now, and another whose deadline is in the future
- **WHEN** the held set is read
- **THEN** the first does not hold and the second holds and reports its deadline

#### Scenario: A hold set by hand has no deadline

- **GIVEN** a write with source `command` and a deadline
- **WHEN** it is made
- **THEN** it is refused and nothing is written

#### Scenario: A file that cannot be read

- **GIVEN** a state file that is not valid
- **WHEN** the held set is read
- **THEN** nothing is held by it, the result says the file is unreadable, and the file is left as it was

#### Scenario: An entry nothing declares

- **GIVEN** an entry naming a split that is not declared and is not `rest`
- **WHEN** the held set is read
- **THEN** it is ignored and reported

#### Scenario: The older file name

- **GIVEN** a file `e2e-blocked.json` in the state directory and no `e2e-held.json`
- **WHEN** the held set is read
- **THEN** nothing is held by it

### Requirement: A split's `hold` is edited in `abk.yaml` as text

A function SHALL set a split entry's `hold` to true or false, or remove the key, at `tests.e2e_splits.<name>` or at a repo's own `tests.e2e_splits.<name>`, by inserting, replacing or deleting lines, so that every comment, every other line and every line ending stays as it was. Setting `hold` on `rest` with no entry SHALL append an entry (creating a missing `tests` or `e2e_splits` mapping), and removing the only key of a `rest` entry SHALL remove the entry. The function SHALL copy the original once to a backup beside the file and leave that first backup alone afterwards, SHALL write through a temporary file, SHALL reload the result and write it only when it gives the expected `hold`, SHALL keep the file's mode, and SHALL refuse, naming the reason and leaving the file byte for byte as it was, when the file has a duplicate key on the path, an anchor or alias on the entry, a multi-line flow entry, an entry that is not a mapping, text that does not parse, a `tests` mapping in flow style, a split that is not declared, or a file that cannot be written.

#### Scenario: Insert and replace

- **GIVEN** a split entry with no `hold`, and another with `hold: false` and a trailing comment
- **WHEN** `hold` is set to true on each
- **THEN** the first gains a `hold: true` line at the entry's indentation and the second has its value replaced with its comment kept, and no other line changed

#### Scenario: A flow entry

- **GIVEN** `acp: {marker: runtime_acp}`
- **WHEN** `hold` is set to true
- **THEN** the entry is edited in place

#### Scenario: A repo's own entry

- **GIVEN** a split declared at the top and again under a repo's `tests.e2e_splits`
- **WHEN** `hold` is set at the repo's location
- **THEN** only the repo's entry changes

#### Scenario: Remove the key

- **GIVEN** a split entry with `hold: true`
- **WHEN** the key is removed
- **THEN** the entry and its marker stay

#### Scenario: `rest`

- **GIVEN** no `rest` entry
- **WHEN** `hold` is set to true on `rest`, and later removed
- **THEN** `rest: {hold: true}` is appended and later the entry is removed

#### Scenario: A file that cannot be edited this way

- **GIVEN** an anchor on the entry, a multi-line flow entry, a duplicate key, text that does not parse or a read-only file
- **WHEN** an edit is asked for
- **THEN** it is refused naming the reason and the file and its backup are as they were

#### Scenario: The backup is made once

- **GIVEN** a first edit that made a backup
- **WHEN** a second edit is made
- **THEN** the first backup is untouched
