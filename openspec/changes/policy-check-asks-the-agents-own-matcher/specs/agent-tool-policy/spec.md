## ADDED Requirements

### Requirement: The policy check reads the agent's configuration and judges each command with the kit's own matcher

For an agent the kit's known-agent table has an applier for, the policy check SHALL read the agent's real configuration
(the file under the home its applier resolves, read-only, by the reader the applier already uses) and SHALL judge each
command of the probe list with the kit's own matcher and dialect: a command is refused when some pattern of the
configuration's deny list matches it, and the result SHALL name that pattern. The probe list is the one list of commands
the check judges. A configuration file that does not exist, or that cannot be read as the applier reads it, SHALL be a
failure that names the path or the reason, and SHALL NOT be read as an empty deny list. Every report SHALL say what it is:
"what the configuration says, in abk's dialect; not observed from the agent". The check SHALL take no agent call and
SHALL finish in well under a second.

#### Scenario: A configuration holding the whole recommendation passes

- **GIVEN** a configuration whose deny list holds every recommended pattern
- **WHEN** the check runs
- **THEN** every covered command is refused and the result names the pattern that refused it, the verdict is ok and the
  output carries the label, and no agent is started and no model is called

#### Scenario: A configuration missing a covered pattern fails

- **GIVEN** a configuration whose deny list lacks the patterns for amending a commit
- **WHEN** the check runs
- **THEN** the verdict is not ok, the amend spellings the lacking patterns would have refused are named as not refused,
  and the fix text is the one `fix_for` gives

#### Scenario: An absent configuration is a failure

- **GIVEN** a home with no configuration file
- **WHEN** the check runs
- **THEN** it fails saying no configuration was found at the path and which variable would point elsewhere, and does not
  report any command as refused or not refused

#### Scenario: A configuration that cannot be read is a failure

- **GIVEN** a configuration that does not parse, or holds its deny list as something other than a list
- **WHEN** the check runs
- **THEN** it fails naming the path and the reason

#### Scenario: The check is instant

- **WHEN** the check runs over a configuration of a few hundred entries
- **THEN** it finishes in under one second

### Requirement: The check runs no code of the agent

Neither `abk doctor` nor `abk init` nor `abk policy check` SHALL start the agent, import from or call into the agent's
installation, or run a script of another program in order to judge the policy. The only code that judges a command SHALL
be the kit's own. The kit SHALL carry no refusal oracle, no interpreter lookup for an agent, no subprocess runner for the
check, no live probe that sends the agent a prompt, no `abk policy check --live`, no setting for a probe or oracle
deadline, no token-spend question, and no cache of the answer.

#### Scenario: The agent's command is a program that fails if run

- **GIVEN** a runtime whose command is a program of the known-agent table's name that records and fails if it is ever started
- **WHEN** the check runs through the chooser, through doctor's runtime-policy check and through `abk init --policy-only`
- **THEN** each judges the policy and the program was never started

#### Scenario: Nothing of the old probe remains

- **WHEN** the kit's source, parser and settings are read
- **THEN** there is no probe of the agent in the protocol runtime, no `--live` flag, no `limits.policy_probe_seconds` or
  `limits.policy_oracle_seconds`, no prompt that says a check spends tokens, and no answer kept in the state directory

### Requirement: Classes the recommendation leaves to the person never fail the check

A result whose class the recommended policy lists as not covered by design SHALL be reported as such and marked so in the
report, and SHALL NOT make the check fail: it SHALL be left out of the unenforced classes and out of the verdict. The report
SHALL still say whether a pattern refused it, naming the pattern. A class the recommendation covers SHALL still fail when
no pattern refuses it. This replaces the earlier probe's rule, under which every class not refused failed, including these.

#### Scenario: A perfect configuration passes

- **GIVEN** a configuration holding exactly the recommended patterns
- **WHEN** the check runs
- **THEN** it passes, and each class the recommendation does not cover is listed as "not covered by design"

#### Scenario: A covered class still fails

- **GIVEN** a configuration that lacks the patterns for one covered class
- **WHEN** the check runs
- **THEN** that class is unenforced and the verdict fails

#### Scenario: A refusal that was not required is shown

- **GIVEN** a configuration that also holds a pattern that refuses a hard reset
- **WHEN** the check runs
- **THEN** the report says the class was refused by that pattern and was not required, and the verdict is unchanged

### Requirement: A check that cannot be made is said, and is never a pass

When the agent has no row in the known-agent table, or a row with no applier, the check SHALL say "cannot check: abk has
no policy for this agent", SHALL NOT report any command as refused or not refused, and SHALL NOT pass. `abk policy check`
and `abk init --policy-only` SHALL exit non-zero for it, and `abk doctor` SHALL report it as a warning. A configuration
that is absent or unreadable SHALL be a failure in all three. A runtime that answers on its own, without reading an
agent's configuration, keeps its own answer.

#### Scenario: An agent with no table entry

- **GIVEN** a runtime whose command is a program the known-agent table does not recognise
- **WHEN** `abk policy check` and `abk init --policy-only` run
- **THEN** each says "cannot check: abk has no policy for this agent" and exits 1

#### Scenario: Doctor warns about an agent with no table entry

- **WHEN** `abk doctor` runs for that runtime
- **THEN** its runtime-policy check is a warning with that message and not a pass

#### Scenario: A row with no applier

- **GIVEN** a known agent whose row has no applier
- **WHEN** the check runs
- **THEN** it is reported the same way, as an agent abk has no policy for

#### Scenario: A runtime that enforces the policy itself

- **GIVEN** a runtime whose own enforcement answers the check
- **WHEN** the check runs
- **THEN** its own answer stands and no configuration is read

### Requirement: Doctor and the init policy step use the check, and ask nothing

`abk doctor`'s runtime-policy check and `abk init`'s policy step (`--policy-only`, `--run-policy-fix`, the built-in fix and
the re-check after a fix) SHALL call one function that chooses the check, and SHALL NOT ask a token-spend question, with or
without `--yes`. The result SHALL be a policy report of the shape the check has always had, with the same exit codes: 0 when
every covered class is refused, 1 when not or when the check could not be made, 2 on a usage problem. Doctor SHALL print the
count and the unrefused classes and the label; the policy command SHALL print every class. A recorded "unchecked" marker in
an installation's configuration SHALL still be honoured.

#### Scenario: Doctor passes and says what it read

- **GIVEN** a known agent whose configuration holds the whole recommendation
- **WHEN** `abk doctor` runs
- **THEN** its runtime-policy check passes, says the answer is what the configuration says and not observed from the agent,
  and starts no agent

#### Scenario: Init asks no question

- **WHEN** `abk init --policy-only` runs without `--yes`
- **THEN** no "spends tokens" question is asked, each class is printed with its refusing pattern, and the exit code is 0 or
  1 by the rule

#### Scenario: A fix is checked again by the same function

- **WHEN** `--run-policy-fix` or the built-in fix has changed the configuration
- **THEN** the re-check reads the configuration again and reports what is refused now

#### Scenario: One chooser

- **WHEN** doctor, init and `abk policy check` are read
- **THEN** each calls the same function to choose the check

### Requirement: `abk policy check` runs the check on demand

`abk policy check [--runtime NAME] [--agent NAME]` SHALL run the check for the selected runtime, or for the known agent
named, print every class and spelling with the pattern that refused it or "not refused", print the classes not covered by
design as such, print the label, and exit 0, 1 or 2 as above. It SHALL change nothing and SHALL start no agent.

#### Scenario: Every class is shown

- **WHEN** `abk policy check` runs over a configuration that lacks one covered pattern
- **THEN** every class is printed with its pattern or "not refused", the classes not covered by design are marked, and the
  exit code is 1

#### Scenario: A usage problem

- **WHEN** `abk policy check --agent NAME` names an agent the table does not hold
- **THEN** it exits 2 naming the known agents

### Requirement: A test shows the kit's matcher agrees with the real agent

The kit SHALL carry one e2e-test test that drives the real agent over every command of the probe list, observes for each
whether the agent refused it, and asserts that the observation equals the check's verdict for that command over the
configuration the agent runs with. No command SHALL be executed by the test: its client SHALL allow every request and
SHALL record a terminal request without running it. The test SHALL have its own deadline, well under the e2e-test time
limit, SHALL print a progress line as each command is judged and a heartbeat while none is, SHALL kill the agent's whole
process group on the deadline, an interrupt or a termination signal, and SHALL remove its temporary directories on every
exit. A command on which the agent's behaviour and the verdict differ SHALL fail the test naming the command, the verdict
and the pattern or its absence. This test is the only place the kit runs the agent for the policy, and it is not part of
the product.

#### Scenario: Behaviour agrees with the verdict

- **GIVEN** a real agent whose configuration holds the recommended policy
- **WHEN** the test drives it over the probe list
- **THEN** every command the verdict says is refused was refused by the agent, and every command the verdict says is not
  refused reached the client's terminal

#### Scenario: A disagreement fails by name

- **GIVEN** an agent that runs a command the verdict says is refused
- **WHEN** the test compares the two
- **THEN** it fails naming that command and the pattern that was expected to refuse it

#### Scenario: The harness cannot hang

- **GIVEN** a fake agent that never answers and a deadline of one second
- **WHEN** the harness drives it
- **THEN** it returns within a few seconds with a did-not-finish result, the agent's process group is gone and no
  temporary directory remains

#### Scenario: An interrupt cleans up

- **WHEN** the harness is interrupted by SIGINT or SIGTERM while driving a fake agent
- **THEN** the same cleanup runs and the signal handlers are restored

### Requirement: The documents say what the check reads

`docs/cli.md`, `docs/init.md`, `docs/agent-runtimes.md`, the abk-pipeline and abk-config skills SHALL describe, where the
policy check is described today, that the check reads the agent's configuration and judges it in the kit's dialect, that its
answer is not an observation of the agent, the classes not covered by design, the "cannot check" case, and that the live
probe and the answer's cache are gone; and `CHANGELOG.md` SHALL have an `## Unreleased` bullet saying so.

#### Scenario: A reader finds it

- **WHEN** the documents and skills are searched for `abk policy check` and for the label
- **THEN** each is described where the check is, no document describes a probe that sends the agent a prompt, and the
  changelog's Unreleased section has a bullet that says the live probe is gone

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

- **WHEN** the check is run repeatedly
- **THEN** no run costs an agent call, and each reads the configuration again, because a kept answer of a configuration
  someone has just edited would mislead

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

### Requirement: The policy check tries every spelling of each forbidden class and names the one an agent lets through

The check SHALL judge, for the agent's configuration, each spelling of the table for each forbidden class that has
spellings, exactly as written, and SHALL report for each class and each spelling whether a pattern of the configuration
refuses it. The table, and not the model, SHALL decide which spellings are judged. A class SHALL be reported unenforced when
any judged spelling is not refused, naming that spelling, and the check SHALL pass only when every spelling of every class
the recommendation covers is. The check SHALL take no agent call and SHALL not be kept between runs. A report written
before spellings were reported SHALL still be read. `abk doctor` SHALL fail naming the class and the spelling, and `abk init`
SHALL print the same finding.

#### Scenario: Every spelling is attempted as written

- **WHEN** the check runs over a configuration that refuses everything the recommendation covers
- **THEN** every class and spelling of the table was judged exactly as written, and none was sent to an agent, the report is ok and holds a result per
  spelling in table order

#### Scenario: One spelling is let through

- **GIVEN** a configuration with a pattern that refuses the plain amend and none that refuses the amend with a working
  directory option
- **WHEN** the check runs
- **THEN** the report is not ok and names the class and that spelling, and the class's other spellings are reported
  refused

#### Scenario: An agent that runs everything unasked

- **GIVEN** a configuration whose deny list is empty, so the agent runs every command it is asked to
- **WHEN** the check runs
- **THEN** every spelling of every covered class is reported unenforced

#### Scenario: The cost is one prompt, once

- **WHEN** the check runs, twice in a row
- **THEN** no prompt is sent either time and no agent is started, and the second run reads the configuration again

#### Scenario: An older stored answer still loads

- **GIVEN** a report written before spellings were reported
- **WHEN** it is read
- **THEN** it loads with the added fields at their defaults

#### Scenario: Doctor names the spelling

- **WHEN** a spelling is not refused
- **THEN** `abk doctor` fails, prints the class and the spelling, and prints the fix the installation supplies

#### Scenario: Init prints the same finding

- **WHEN** `abk init` runs the check and a spelling is not refused
- **THEN** it prints the finding as `abk doctor` does and asks before running the fix

### Requirement: `abk policy apply` shows the change, asks, writes and says how to confirm

`abk policy apply` SHALL resolve the agent from the selected runtime (or one the person names), print a diff of the change,
ask before writing, write, and tell the person how to confirm with `abk policy check`, which reads the configuration and
costs no model call. It SHALL NOT start the agent. It SHALL support a dry run that writes nothing. It SHALL exit 0 when the change was
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
- **THEN** the output names `abk policy check` as the way to confirm, and says it reads the configuration and spends no
  model tokens, and no agent is started by `apply` itself

#### Scenario: The agent is named when the command is a wrapper

- **GIVEN** a runtime whose command is a wrapper script the known-agent table does not recognise
- **WHEN** `abk policy apply --agent NAME` names a row
- **THEN** that row's applier is used, and an unknown name exits 2 naming the known rows
