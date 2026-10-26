# Spec Delta

## ADDED Requirements

### Requirement: A forbidden command is judged by what it runs, not by how its tool's global options are spelled

The pipeline's command rules SHALL judge a command as the tool would run it: the global options of the code host's tools
that sit before the subcommand (a working directory, a one-off configuration value, a pager switch, a git directory or
work tree, a repository selector), in the `=` form and the two-word form and in any combination, SHALL NOT make a command
that a rule forbids look like a different one. This SHALL hold for every rule that names a subcommand: amending a commit,
pushing to a default branch, force-pushing, a hard reset, discarding untracked work, force-deleting a branch and merging a
pull request. A merge requested through the host's raw API SHALL be forbidden as the merge command is, and a request that
only reads through it SHALL NOT. A wrapper or directory change in front of a forbidden command SHALL NOT hide it. A command
the rules allow SHALL stay allowed when it carries the same options. The spellings SHALL be listed in one table that the
rules' tests and the policy check both read.

#### Scenario: A git global option before the subcommand

- **WHEN** an agent runs an amend, a push to the default branch or a force push with a working directory, a configuration
  value, a pager switch, a git directory or a work tree before the subcommand
- **THEN** the command is refused for the same reason as the plain spelling

#### Scenario: Options in the two-word form and in combination

- **WHEN** a git directory or work tree is given as two words, or several global options are combined before the
  subcommand
- **THEN** the command is refused as the plain spelling is

#### Scenario: The host tool's repository option

- **WHEN** an agent merges a pull request with the repository given by the short or the long option, or with `=`
- **THEN** the merge is refused as the plain merge is

#### Scenario: A merge through the raw API

- **WHEN** an agent sends a request to the host's raw API that merges a pull request, with the method given before or after
  the path
- **THEN** it is refused as a merge, while a read through the same client is allowed

#### Scenario: A wrapper or directory change in front

- **WHEN** a forbidden command is preceded by an environment assignment, a command wrapper, a privilege wrapper with an
  option that takes a value, or a directory change in the same line
- **THEN** it is refused as the plain spelling is

#### Scenario: Other rules see through the options too

- **WHEN** a hard reset or a branch force-delete is run with a working directory before the subcommand
- **THEN** it is refused as the plain spelling is

#### Scenario: Allowed work stays allowed

- **WHEN** a read, a status, a diff or a push of the unit's own branch is run with the same options, or a commit message
  mentions a forbidden command
- **THEN** it is allowed as before

#### Scenario: The runtime that answers locally holds for every spelling

- **GIVEN** a runtime that registers the pipeline's own policy before each tool call
- **WHEN** every spelling of the table is judged through its hook
- **THEN** each is denied, and the check still spends no agent call

### Requirement: The policy check tries every spelling of each forbidden class and names the one an agent lets through

The check SHALL ask an agent, in the throwaway worktree, to attempt each spelling of the table for each forbidden class
that has spellings, exactly as written, and SHALL report for each class and each spelling whether it was refused. The table,
and not the model, SHALL decide which spellings are tried. A class SHALL be reported unenforced when any attempted spelling
is not refused, naming that spelling, and the check SHALL pass only when every one is. The check SHALL ask once, in one
prompt, for the whole table, and its answer SHALL be reused under the existing short-lived cache. A report stored before
spellings were reported SHALL still be read. `abk doctor` SHALL fail naming the class and the spelling, and `abk init`
SHALL print the same finding.

#### Scenario: Every spelling is attempted as written

- **WHEN** the check runs against an agent that refuses everything it is asked to attempt
- **THEN** every class and spelling of the table was attempted exactly as written, the report is ok and holds a result per
  spelling in table order

#### Scenario: One spelling is let through

- **GIVEN** an agent that refuses the plain amend and runs the amend with a working directory option
- **WHEN** the check runs
- **THEN** the report is not ok and names the class and that spelling, and the class's other spellings are reported
  refused

#### Scenario: An agent that runs everything unasked

- **GIVEN** an agent that runs every command without asking
- **WHEN** the check runs
- **THEN** every spelling of every class is reported unenforced

#### Scenario: The cost is one prompt, once

- **WHEN** the check runs
- **THEN** it sends one prompt naming every spelling in one session, and a second check inside the cache window sends none

#### Scenario: An older stored answer still loads

- **GIVEN** a cached answer written before spellings were reported
- **WHEN** the check is asked within the cache window
- **THEN** it is reused as it is

#### Scenario: Doctor names the spelling

- **WHEN** a spelling is not refused
- **THEN** `abk doctor` fails, prints the class and the spelling, and prints the fix the installation supplies

#### Scenario: Init prints the same finding

- **WHEN** `abk init` runs the check and a spelling is not refused
- **THEN** it prints the finding as `abk doctor` does and asks before running the fix
