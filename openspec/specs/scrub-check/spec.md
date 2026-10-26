# scrub-check Specification

## Purpose
TBD - created by archiving change planning-content-follows-the-public-rule. Update Purpose after archive.

## Requirements

### Requirement: Scanning a planning root's own checkout does not flag the root's name

`abk scrub-check` SHALL leave the planning root's directory name out of the terms when the resolved `--target` is the planning root, and
SHALL keep it for every other target. The repo whose checkout is the target SHALL stay skipped as it is today. A target that is the
planning root SHALL otherwise be scanned with the same rules (suffixes, skipped directories, case-insensitive match) as any other.

#### Scenario: The target is the planning root

- **GIVEN** a planning root named `plan` holding the tool's checkout, whose only repo entry has the root as its path
- **WHEN** `abk scrub-check --target <the root>` runs over files that say `plan`
- **THEN** no hit is reported for `plan` and the exit status is 0

#### Scenario: The target is another checkout

- **GIVEN** the same installation and a different checkout whose file says `plan`
- **WHEN** `abk scrub-check --target <that checkout>` runs
- **THEN** the hit is reported and the exit status is 1

#### Scenario: Another repo's name is still a term

- **GIVEN** a planning root that is the target and a second repo named `platform` in its configuration
- **WHEN** a file under the target says `platform`
- **THEN** the hit is reported

### Requirement: A gitignored local list adds terms and may remove derived ones

The terms SHALL include each line of `scrub.local` in the planning root: blank lines and text after `#` ignored, each term compared
case-insensitively, terms under 3 characters dropped, and a word on the generic list kept when the list names it. A line starting with `!`
SHALL remove that derived term. A missing file SHALL add nothing and be no error.

#### Scenario: A term only the local list knows

- **GIVEN** a `scrub.local` holding `example-host` and a file under the target saying `Example-Host`
- **WHEN** `abk scrub-check` runs
- **THEN** the hit names `example-host` and `--show-terms` lists it

#### Scenario: A comment and a blank line

- **GIVEN** a `scrub.local` of `# note`, an empty line and `svc-x # a host`
- **WHEN** the terms are derived
- **THEN** the local terms are exactly `svc-x`

#### Scenario: A derived term is removed

- **GIVEN** a user name that is a common word and a `scrub.local` line `!thatword`
- **WHEN** the terms are derived
- **THEN** `thatword` is not among them

#### Scenario: No local list

- **GIVEN** no `scrub.local`
- **WHEN** the terms are derived
- **THEN** they are those the configuration gives, and nothing fails

### Requirement: The other installation facts are terms

The terms SHALL also include, from the merged configuration (committed file and local overlay together): each `from: literal` value of
`verify.env` of 4 or more characters that is not all digits and not generic; for each `env-file` and `yaml` provider, the file's name and
its first directory below the home directory; the home directory's user name; and the first dot-directory below home of each configured
path (`repos.*.path`, `deploy.ssh_key`, `deploy.live_written`, `planning.worktree_root`) that the tool-directory allowance does not name.

#### Scenario: A literal value is a term

- **GIVEN** a `verify.env` literal of `agentcmd --flag` for one variable and `7140` for another
- **WHEN** the terms are derived
- **THEN** `agentcmd --flag` is a term and `7140` is not

#### Scenario: A provider file's home directory

- **GIVEN** an `env-file` provider whose file is under a dot-directory below home
- **WHEN** the terms are derived
- **THEN** the dot-directory's name and the file's name are terms

#### Scenario: A tool directory is not a term

- **GIVEN** a configured path under the agent runtime's own directory below home
- **WHEN** the terms are derived
- **THEN** that directory is not a term

#### Scenario: A fact in the overlay

- **GIVEN** a literal moved from `abk.yaml` into `abk.local.yaml`
- **WHEN** the terms are derived
- **THEN** it is still a term

### Requirement: One function defines the terms, and one scrubs text with them

`terms_for` SHALL be the only definition of the term set and SHALL be importable from a module other than the command's, with the command
re-exporting it. `scrub_text(text, terms)` SHALL replace each term case-insensitively, longest first, with a neutral placeholder, SHALL
return text with no term unchanged, and SHALL give the same output when applied to its own output.

#### Scenario: Longest term first

- **GIVEN** terms `app` and `app-service` and the text `see app-service and app`
- **WHEN** it is scrubbed
- **THEN** both words are replaced whole, and no half of `app-service` is left

#### Scenario: Idempotent

- **GIVEN** any text and its scrubbed form
- **WHEN** the scrubbed form is scrubbed again
- **THEN** the output equals its input

#### Scenario: The command reports what the function returns

- **GIVEN** an installation and a target
- **WHEN** `abk scrub-check --show-terms` runs
- **THEN** the printed terms equal `terms_for(installation, target=target)` in the same order
