# Spec Delta

## Purpose

Defines that the kit owns the recommendation of what makes an agent refuse the forbidden command classes: it ships the
recommended policy as data, prints it for any agent, compares it with a known agent's configuration, and merges it into
that configuration safely, on request.

## MODIFIED Requirements

### Requirement: Setup asks before changing an agent's configuration

`abk doctor` SHALL fail, not warn, when a forbidden class is unenforced, and
SHALL print the command that would fix it: the installation's own fix when it
configured one, else, for an agent the kit knows how to patch, the kit's own
apply command, else the command that prints the recommended patterns.
`abk init` SHALL report the same
finding and SHALL ask for confirmation before running that command, which the
installation supplies or the kit's own applier provides; declining SHALL leave everything unchanged and say which
guarantee is missing. The framework SHALL NOT edit another tool's
configuration itself, except through the applier of the recommended policy, which edits only the agent's list of
refused commands and, on request, its build-run toolset, on a confirmation.

#### Scenario: Setup finds an unconstrained agent

- **WHEN** `abk init` runs and a forbidden class is unenforced
- **THEN** it reports the class, asks before running the installation's fix
  command, and runs it only on confirmation

#### Scenario: The operator declines

- **WHEN** the operator declines the fix
- **THEN** nothing is changed and the missing guarantee is stated

#### Scenario: A check that costs an agent call

- **WHEN** the check has to ask an agent, and is run repeatedly
- **THEN** its result is reused for a short period rather than re-run every time

#### Scenario: Doctor prints the kit's own fix when the installation has none

- **GIVEN** a class is unenforced, the installation sets no fix, and the agent has an applier
- **WHEN** `abk doctor` runs
- **THEN** it fails naming the class and prints the kit's apply command rather than only a key to set

#### Scenario: Doctor prints how to place the patterns when there is no applier

- **GIVEN** a class is unenforced, the installation sets no fix, and the agent has no applier
- **WHEN** `abk doctor` runs
- **THEN** it fails naming the class and prints the command that prints the recommended patterns, then the key that would
  hold a fix of the installation's own

#### Scenario: The installation's own fix is printed first

- **GIVEN** the installation sets a fix and the agent has an applier
- **WHEN** `abk doctor` runs and a class is unenforced
- **THEN** the installation's fix is the one printed

## ADDED Requirements

### Requirement: The recommended policy is shipped as one table in the kit

The kit SHALL ship, as data, the recommended policy for a build agent: for each forbidden class that agent-side command
patterns can refuse, the command globs that refuse it across spellings, the sample commands each class's globs must match
and the samples they must not, the classes the recommendation does not cover and why, and the dialect the globs are
written in (case-insensitive, matched against the whole command and each segment of a compound command). The classes SHALL
be named as the policy check names them, and the commands SHALL come from the table of spellings the policy check and the
command rules' tests already read, so a command is written once. The shipped list SHALL be a superset of what the policy
check requires: every spelling the check attempts, for a class the recommendation covers, SHALL match a glob of the class.
No glob SHALL match a command a build run needs. The list SHALL have no duplicate and no blank entry.

#### Scenario: Every refused sample matches a glob of its class

- **WHEN** each refused sample of each class is matched against the class's globs by the reference matcher
- **THEN** every one matches at least one glob, including the same command behind a git option, a repository option, a
  quoted refspec and a compound command

#### Scenario: Nothing a build run needs is refused

- **WHEN** each allowed sample (a push of the unit's own branch whose name contains a default branch's name, a pull
  request view, a raw-API read, a read through a working-directory option) is matched against every glob
- **THEN** none matches

#### Scenario: The list covers what the check attempts

- **WHEN** each spelling the policy check attempts for a covered class is matched against that class's globs
- **THEN** every one matches, so a list that would fail the check cannot be shipped

#### Scenario: The globs agree with the command rules

- **WHEN** each refused sample the command rules forbid is judged by them
- **THEN** it is refused, so the globs and the rules agree on the commands both own, and a sample only a glob refuses is
  named as such in the table

#### Scenario: The dialect is the one the matcher implements

- **GIVEN** a glob written in the shipped dialect
- **WHEN** it is matched against a command in other letter case, one with doubled spaces, and one preceded by another command
  after `&&`, `;` or a pipe
- **THEN** it matches in each case, and a command that only quotes the words in a message is a documented false positive

#### Scenario: The classes with no glob are named

- **WHEN** the recommendation is shown
- **THEN** the classes the policy check attempts that it has no glob for are listed with the reason, so a person using it
  for an agent that does not gate them knows

#### Scenario: A stale claim cannot rot

- **GIVEN** a documented false positive or gap
- **WHEN** the table's own test runs
- **THEN** the sample for each still behaves as documented, and a glob that starts catching a documented gap fails the test

### Requirement: `abk policy patterns` prints the recommended globs for an agent nobody can patch

`abk policy patterns` SHALL print the recommended globs in table order, as one per line, as a JSON array or as a YAML
sequence of quoted scalars, for all classes or those named, and SHALL add the installation's own extra patterns when asked.
It SHALL need no installation, make no model call and write no file, and its structured outputs SHALL load back to the
same list.

#### Scenario: The default output

- **WHEN** `abk policy patterns` runs outside any installation
- **THEN** it prints every recommended glob, one per line, in table order, exits 0 and writes nothing

#### Scenario: A structured output loads back

- **WHEN** the output is requested as a JSON array or as a YAML sequence
- **THEN** parsing it gives the same list of patterns, in the same order, including those with quotes, brackets and colons

#### Scenario: A class filter

- **WHEN** one or more classes are named
- **THEN** only their globs are printed, in table order, and an unknown class exits 2 naming the classes there are

#### Scenario: The installation's extras

- **GIVEN** an installation that lists extra patterns for its runtime
- **WHEN** extras are asked for
- **THEN** they follow the kit's list, with no duplicate

### Requirement: `abk policy show` compares an agent's configuration with the recommendation, read-only

`abk policy show` SHALL print the recommendation per class, the classes it does not cover, its known false positives and its
dialect, and, for an agent with an applier, whether its configuration exists and parses, which recommended patterns it has
and lacks, how many other entries it holds, and the recommended toolset against the current one. It SHALL change nothing and
SHALL NOT run the policy check, which costs agent calls.

#### Scenario: A known agent with patterns missing

- **GIVEN** an agent whose configuration lists some of the recommended patterns
- **WHEN** `abk policy show` runs
- **THEN** it names the missing patterns by class, counts the entries that are not the kit's, and changes no file

#### Scenario: An agent with no applier

- **WHEN** `abk policy show` runs for an agent the kit has no applier for
- **THEN** it prints the recommendation and says the kit cannot read or patch this agent's configuration, pointing at the
  command that prints the patterns

#### Scenario: An absent or unreadable configuration

- **GIVEN** an agent whose configuration is absent, or present and not parseable
- **WHEN** `abk policy show` runs
- **THEN** it says which, naming the path, and still prints the recommendation

#### Scenario: The check is not run

- **WHEN** `abk policy show` runs against a runtime whose check would prompt an agent
- **THEN** no agent is started and the output says that `abk doctor` runs the check

### Requirement: The kit applies the recommended policy to a known agent's configuration safely

For an agent whose known-agent row carries an apply descriptor (where its configuration lives, in what format, and the key
path of its list of refused commands), the kit SHALL merge the recommended patterns, and the installation's extras, into that
list: add every missing pattern after the operator's own entries, never remove, reorder or edit an entry, and change nothing
when nothing is missing. It SHALL write by inserting the added lines into the file's original text, never by writing the
parsed document out again, so that every other byte of the file (comments, spellings of values, spacing, line breaks,
indentation, document markers) is unchanged and a diff of before and after holds only the added lines. It SHALL refuse a
configuration that does not parse, whose list or its parents have the wrong shape, or whose list is written in a form that
cannot be extended by inserting lines (an inline list or a single string), naming the file and the key, and write nothing. It
SHALL do nothing and say so when the agent's configuration does not exist. It SHALL write through a temporary file in the
same directory, keeping the file's mode, and SHALL keep a copy of the original beside it the first time it writes and never
overwrite that copy. The agent's configuration directory SHALL be resolvable through the variable the agent reads, so a
scratch directory can stand in for it. The descriptor SHALL be data on the row, so a new agent needs a row and no code.

#### Scenario: Missing patterns are added after the operator's own

- **GIVEN** a configuration whose list holds two rules of the operator's and some recommended patterns
- **WHEN** the recommended policy is applied
- **THEN** the missing patterns follow the existing entries in table order, and the operator's two rules are unchanged and
  first

#### Scenario: Comments and other keys are preserved

- **GIVEN** a configuration with comments, quoted values and other sections
- **WHEN** the policy is applied
- **THEN** the only lines that differ are the added patterns, and every comment and every other key is as it was

#### Scenario: Every other byte is unchanged

- **GIVEN** a configuration with values the YAML library would respell if it wrote the file out again: `~` and `null`,
  `True`, extra spaces before a value or a comment, a multi-line plain scalar, mixed indentation, a list indented unlike its
  neighbours, a leading directive and `---`, a trailing `...`, bare `off`, `on` and `yes`, no final newline, or CRLF line
  endings
- **WHEN** the policy is applied
- **THEN** the diff of before and after removes no line, every added line follows the list's last item in that list's own
  indentation and quoting, and a trailing `...` is still last

#### Scenario: A missing list or section is inserted as a block of its own

- **GIVEN** a configuration whose section exists without the list, or whose key holds no value, or which has no section at all
- **WHEN** the policy is applied
- **THEN** the key and the patterns are inserted as text (after the section's last entry at its siblings' column, right
  under the empty key, or at the end of the file before a trailing `...`) and no existing line is removed or changed

#### Scenario: A second run changes nothing

- **WHEN** the policy is applied a second time
- **THEN** it says nothing needed changing, writes nothing and makes no second backup

#### Scenario: A list written as one string

- **GIVEN** a configuration whose list is a single string
- **WHEN** the policy is applied
- **THEN** it refuses naming the file and the key path, says the list cannot be extended without rewriting the operator's
  line, exits 2 and writes nothing, not even a backup

#### Scenario: A list written inline

- **GIVEN** a configuration whose list is written as an inline list (`[a, b]`, or empty `[]`), `~` or `null`
- **WHEN** the policy is applied
- **THEN** it refuses naming the file and the key path and why, exits 2 and writes nothing

#### Scenario: A result that does not read back as intended

- **GIVEN** an insertion whose text does not parse back to the original plus the added patterns
- **WHEN** the policy is applied
- **THEN** it refuses, writes nothing and says so, rather than writing a file it could not confirm

#### Scenario: Missing sections are created

- **GIVEN** a configuration with no section for the list
- **WHEN** the policy is applied
- **THEN** the section and the list are created holding the recommended patterns, and nothing else changes

#### Scenario: A configuration that does not parse

- **GIVEN** a configuration file that is not valid in its format
- **WHEN** the policy is applied
- **THEN** it refuses naming the file, exits 2 and writes nothing, not even a backup

#### Scenario: A list of the wrong shape

- **GIVEN** a configuration whose list is a number, or whose parent section is not a mapping
- **WHEN** the policy is applied
- **THEN** it refuses naming the file and the key path, exits 2 and writes nothing

#### Scenario: The agent is not installed

- **GIVEN** no configuration file at the resolved location
- **WHEN** the policy is applied
- **THEN** it says there is no configuration there and names the variable that moves it, creates no file or directory, and
  exits 2

#### Scenario: A scratch home stands in for the real one

- **GIVEN** the agent's home variable set to a scratch directory
- **WHEN** the policy is applied
- **THEN** that directory's configuration is the one read and written and the person's real configuration is not touched

#### Scenario: The first write keeps a copy, and only the first

- **WHEN** the policy is applied to a configuration that needs changes, and then a rule is added by hand and it is applied again
- **THEN** the copy holds the file as it was before the first write and is not overwritten by the second

#### Scenario: A write that fails leaves the original

- **GIVEN** a write that fails after the temporary file was made
- **WHEN** the policy is applied
- **THEN** the original is unchanged and no temporary file remains

#### Scenario: A second agent shape needs only a row

- **GIVEN** a row whose configuration file, key path and format version differ from the first agent's
- **WHEN** the policy is applied through it
- **THEN** its list is merged by the same rule with no change to the engine

#### Scenario: A row naming a format nobody can write

- **GIVEN** a row whose format has no writer
- **WHEN** the table's structural test runs
- **THEN** it fails naming the row

#### Scenario: The installation's extras are merged

- **GIVEN** an installation that lists extra patterns for its runtime
- **WHEN** the policy is applied
- **THEN** the extras are added after the kit's, once, and a blank extra fails at configuration load naming the key

### Requirement: The build-run toolset is a recommendation, applied only on request

An agent's row MAY carry a recommended build-run toolset, the tools a build run needs and no more. The kit SHALL show it, with
the current value, and SHALL set it only when asked with an explicit flag, replacing the current list and showing the
replacement as a change from one value to the other; it SHALL NOT set it in the course of any other fix, nor in init's step.

#### Scenario: Not applied by default

- **WHEN** the recommended policy is applied without the toolset flag
- **THEN** the toolset is left as it was, and the output states the recommendation and the current value

#### Scenario: Applied on request

- **WHEN** the policy is applied with the toolset flag
- **THEN** the diff shows the toolset changing from the current list to the recommended one, and it is written on
  confirmation along with the patterns, changing no line outside the toolset list's own

#### Scenario: A row with no toolset

- **WHEN** the toolset flag is given for a row that carries no recommended toolset
- **THEN** it exits 2 saying there is none for this agent and writes nothing

### Requirement: `abk policy apply` shows the change, asks, writes and says how to confirm

`abk policy apply` SHALL resolve the agent from the selected runtime (or one the person names), print a diff of the change,
ask before writing, write, and tell the person how to confirm with a live check, which it SHALL NOT run without being
asked because it spends model tokens. It SHALL support a dry run that writes nothing. It SHALL exit 0 when the change was
written or none was needed, 1 when the person declined, and 2 on a usage problem, a configuration it refuses, an absent
configuration or an agent it has no applier for.

#### Scenario: The diff is shown and a yes writes

- **WHEN** `abk policy apply` runs against a configuration that needs patterns and the person confirms
- **THEN** the diff is printed first, the file is written, the backup's path and the count of patterns added are printed, and
  the exit status is 0

#### Scenario: A no writes nothing

- **WHEN** the person declines
- **THEN** no file, backup or temporary file is written and the exit status is 1

#### Scenario: A dry run

- **WHEN** `abk policy apply --dry-run` runs
- **THEN** the diff is printed, nothing is written, and the exit status is 0

#### Scenario: Nothing to change

- **GIVEN** a configuration that already holds every recommended pattern
- **WHEN** `abk policy apply` runs
- **THEN** it says there is nothing to change, asks nothing, writes nothing and exits 0

#### Scenario: An agent without an applier

- **WHEN** `abk policy apply` runs for an agent with no apply descriptor
- **THEN** it exits 2 saying so and prints the command that prints the patterns

#### Scenario: A runtime that enforces the policy itself

- **WHEN** `abk policy apply` runs for a runtime whose enforcement is built in
- **THEN** it says there is nothing to apply and exits 0

#### Scenario: The live check is offered, not run

- **WHEN** the policy has been written
- **THEN** the output names the command that runs the live check and says it spends model tokens, and no agent is started
  by `apply` itself

#### Scenario: The agent is named when the command is a wrapper

- **GIVEN** a runtime whose command is a wrapper script the known-agent table does not recognise
- **WHEN** `abk policy apply --agent NAME` names a row
- **THEN** that row's applier is used, and an unknown name exits 2 naming the known rows
