## ADDED Requirements

### Requirement: The known secret values are gathered once per tick and never written

The pipeline SHALL gather, from the workspace configuration and the settings, a set of known secret values, each under the name of its source: every `verify.env` value, every
credential field of the settings (the code-host token, the Azure DevOps PAT, the gateway master key and the telemetry dashboard token), every value in `runtimes.*.env`, the value of
each environment variable named in the configuration's `redact` list, and each key the gateway layer mints for a call. The set SHALL be computed when a tick starts and again when the
settings reload. It SHALL NOT be logged, written to a file, put in telemetry or in a checkpoint, and its printed form SHALL show names only. A value that cannot be resolved SHALL be
left out with one warning that names it and does not print any value, and SHALL NOT stop the tick.

#### Scenario: Every source is in the set

- **GIVEN** a `verify.env` entry, a token in the settings, a `runtimes.*.env` entry, a name in `redact` whose variable is set, and a minted gateway key
- **WHEN** the set is gathered
- **THEN** each value is in it under its own name

#### Scenario: Settings reload

- **GIVEN** a token that changes when the settings reload
- **WHEN** the reload happens
- **THEN** the old value is no longer in the set and the new one is

#### Scenario: The set is not printed or saved

- **WHEN** the set is printed, its repr taken, and a tick run with logging on
- **THEN** only names appear, and no value appears in any log line, state file or ledger line

#### Scenario: A provider that fails

- **GIVEN** a `verify.env` entry whose provider cannot be resolved
- **WHEN** the set is gathered
- **THEN** the other values are in it, one warning names the entry without a value, and the tick goes on

### Requirement: A known value is replaced by name wherever text is stored or posted

One redaction function SHALL replace each occurrence of a known secret value, matched as an exact, case-sensitive substring, with `[redacted:<NAME>]`, where the name is the source
variable. The value, any prefix of it and its length SHALL NOT appear in the replacement. A value of fewer than 8 characters SHALL NOT be redacted: short configuration values are not
secrets in practice, replacing them would make failure text unreadable, and a secret that short protects little. When one known value contains another, the longer SHALL be replaced
first. Redaction SHALL be applied before text is cut to a length, so that a cut cannot leave half a secret that matches nothing. The function SHALL be applied where text leaves a run:
the unit store when it saves feedback, run logs, transcripts, the pipeline's printed output, the usage ledger's text fields, the tier-1 and tier-2 result text, everything written to the
code host (pull request titles and bodies, comments, statuses) and the prompt given to an agent on a rework.

#### Scenario: Feedback saved on a unit

- **GIVEN** a tier-2 failure whose output holds a known value
- **WHEN** the feedback is saved
- **THEN** the unit store holds `[redacted:<NAME>]` in its place and the value appears nowhere in the file

#### Scenario: A run log

- **WHEN** a line holding a known value is written to a unit's run log, and an agent reply holding it is written whole
- **THEN** the file holds the replacement in both

#### Scenario: A transcript

- **WHEN** a tool result holding a known value, longer than the transcript's result limit with the value before the limit, is recorded
- **THEN** the line holds the replacement, and no part of the value remains at the cut

#### Scenario: A posted pull request description

- **GIVEN** a tier-2 failure whose output holds a known value
- **WHEN** the pull request description is created or updated
- **THEN** the "Full output" block holds the replacement and the body sent to the host holds no value

#### Scenario: A posted comment

- **WHEN** a reply holding a known value is posted as a comment
- **THEN** the body sent to the host holds the replacement

#### Scenario: A posted status

- **WHEN** a status is posted with a description holding a known value
- **THEN** the description sent to the host holds the replacement

#### Scenario: A rework prompt

- **GIVEN** feedback saved before this requirement existed, holding a known value
- **WHEN** a rework prompt is assembled from it
- **THEN** the prompt holds the replacement, and the stored feedback is not changed by that

#### Scenario: A usage ledger line

- **WHEN** a record whose `outcome` holds a known value is appended
- **THEN** the line holds the replacement

#### Scenario: A value inside a larger string

- **GIVEN** a known value inside a URL and again after `Bearer `
- **WHEN** the text is redacted
- **THEN** only the value is replaced and the rest of each string is kept

#### Scenario: A value shorter than the minimum

- **GIVEN** a configured variable whose value is `true`, and another whose value is seven characters
- **WHEN** text holding them is redacted
- **THEN** both are left as they are, and `abk doctor` names the variables as too short to be redacted

#### Scenario: Two secrets in one string

- **WHEN** a string holds two different known values, one twice
- **THEN** each occurrence is replaced under its own name

#### Scenario: One value contains another

- **GIVEN** a known value that is a substring of another known value
- **WHEN** text holding the longer one is redacted
- **THEN** the longer is replaced whole, under its own name, and nothing of it is left

### Requirement: Well-known token shapes are a second net, and are heuristics

After the known values, text SHALL be searched for the shapes of well-known tokens: `sk-` followed by at least 20 key characters, the `ghp_`, `gho_`, `ghu_`, `ghs_` and `ghr_`
prefixes followed by at least 36 alphanumerics, `github_pat_` followed by at least 22 key characters, and a bearer value of at least 20 token characters after `Bearer `. A match SHALL
be replaced by `[redacted:token-shape]`. The documentation SHALL say that these patterns are heuristics: they miss a token with no recognisable shape and may match a string that is not
one, and the set of known values is the guarantee.

#### Scenario: A token of a known shape that is not in the set

- **WHEN** text holds a string shaped like a `github_pat_` token that no configuration names
- **THEN** it is replaced by `[redacted:token-shape]`

#### Scenario: A value of no known shape that is not in the set

- **WHEN** text holds a 52-character plain string that no configuration names
- **THEN** it is left as it is

### Requirement: A failed redaction withholds the text

When redaction raises, the text SHALL NOT be stored or posted as it was. The short notice `[redaction failed: text withheld]` SHALL take its place, and one log line SHALL record the
failure's type and place without the text or the exception's message. A tier-2 result SHALL keep its counts and verdict and lose only its output. The failure SHALL NOT stop the run.

#### Scenario: Redaction raises on feedback

- **GIVEN** a redaction that raises
- **WHEN** feedback holding a known value is saved
- **THEN** the unit store holds the notice, no value, and one log line that holds neither the text nor the exception's message

#### Scenario: Redaction raises on a posted body

- **WHEN** a pull request description is built and redaction raises
- **THEN** the body sent to the host has the notice in place of the "Full output" text, and the counts are unchanged

### Requirement: Stored history is not rewritten by this requirement, and a temporary command redacts it once

Text stored or posted before this requirement existed SHALL NOT be rewritten by the pipeline. A temporary command, `abk redact-history`, SHALL redact what is stored on the machine:
the unit store's feedback, run logs, transcripts and the usage ledger of the active workspace. It SHALL default to a dry run that reports, per file, which names were found and never a
value, SHALL rewrite only with `--apply`, and SHALL keep a copy of each file it changes beside it. It SHALL NOT edit anything on a code host. Rotating a key that reached stored or
posted text SHALL be the operator's decision, and a secret already sent to a model provider SHALL be understood to be beyond recall.

#### Scenario: A dry run

- **GIVEN** a unit store, a run log and a ledger that hold known values
- **WHEN** the command runs without `--apply`
- **THEN** it lists each file with the names found, changes no file, and prints no value

#### Scenario: Apply

- **WHEN** the command runs with `--apply`
- **THEN** each file holds the replacement in place of every known value, a copy of each changed file is beside it, and a second run reports nothing found

#### Scenario: Nothing on the host is touched

- **WHEN** the command runs with `--apply`
- **THEN** no call is made to a code host

## MODIFIED Requirements

### Requirement: The journal still receives everything

Writing these files SHALL NOT remove or reduce what the pipeline prints to its own output, so a
pass remains readable in one place, including the lines that belong to no unit. The one change to
what is printed is that a known secret value in it is replaced as it is in the files, since the
journal is stored too.

#### Scenario: A pass with several units

- **WHEN** a pass builds more than one unit
- **THEN** its whole output is still printed as it is today, and each unit's lines are also in that
  unit's file
