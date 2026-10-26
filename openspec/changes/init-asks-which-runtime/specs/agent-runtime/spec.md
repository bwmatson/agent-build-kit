# Spec Delta

## Purpose

Defines how a workspace comes to name its runtime: the machine is probed without a model call, the candidates are
shown, the person chooses and answers the runtime's own questions, and only a confirmed choice is written, before any
step that depends on a runtime runs.

## ADDED Requirements

### Requirement: A runtime reports what this machine can run, without a model call

A runtime SHALL be able to report the candidates it finds on this machine: each with the command that would start it,
whether it is usable, and the reasons when it is not. The probe SHALL check only what is observable locally — that a
program is on the path, that its optional library imports, and, for an agent whose flag spelling varies, the output of
one bounded help run — and SHALL NOT start a session, send a prompt or use the network. A run of the probe that exceeds
its time limit SHALL make that candidate unusable with that reason. Known agents SHALL be listed in one table of data
in the protocol runtime's module, each entry naming its program, its start command variants, what it needs and how far
it is verified.

#### Scenario: A usable candidate

- **GIVEN** a known agent's program is on the path and the optional library is importable
- **WHEN** the probe runs
- **THEN** the candidate is usable, carries its start command and its verification note, and shows what it needs

#### Scenario: An unusable candidate says why

- **GIVEN** a known agent's program is not on the path, or its program is but the optional library is missing
- **WHEN** the probe runs
- **THEN** the candidate is listed as unusable with the reason, such as the program not being on the path or the extra
  not being installed

#### Scenario: The command variant follows the installed version

- **GIVEN** an agent whose start flag differs between versions
- **WHEN** the probe reads its help output
- **THEN** the start command is the variant the help text shows, and a help text showing neither makes the candidate
  unusable

#### Scenario: A help run that does not finish

- **WHEN** the help run exceeds its time limit
- **THEN** the candidate is unusable with that reason and the probe moves on

#### Scenario: Probing costs nothing

- **WHEN** the probe runs against fakes that record every call
- **THEN** no session is started, no prompt is sent and no network call is made

#### Scenario: The table is complete

- **WHEN** every entry of the known-agent table is read
- **THEN** each names a program and at least one start command and carries a note on how it was verified

### Requirement: `abk init` asks which runtime, before anything depends on one

`abk init` SHALL, after detecting the repos and before any step that runs an agent, probe the runtimes, show the
candidates with usable ones first and each unusable one with its reason, and always a last line for the person's own
configuration, and ask which to use, defaulting to the only usable one. The choice SHALL be recorded as `runtime:` and
the runtime's own entry in `abk.yaml`, and the research and propose steps SHALL receive the chosen runtime explicitly
rather than resolving the default. Under `--yes`, exactly one usable candidate SHALL be used; several SHALL refuse
with the list and exit 2 unless `--runtime` names one; none SHALL print what each candidate needs and exit 2 having
written nothing. An `abk.yaml` that is kept and already names a runtime SHALL skip the question.

#### Scenario: Nothing installed

- **GIVEN** no candidate is usable
- **WHEN** `abk init --yes` runs
- **THEN** it prints what each candidate needs, exits 2 and writes nothing

#### Scenario: One usable candidate

- **GIVEN** exactly one candidate is usable
- **WHEN** the person presses Enter at the question
- **THEN** that runtime is chosen and recorded

#### Scenario: Several candidates, the second chosen

- **GIVEN** three candidates were found, two usable and one not
- **WHEN** init shows the list and the person picks the second
- **THEN** usable candidates appear first, the unusable one shows its reason, and the second candidate is recorded

#### Scenario: The person's own configuration

- **WHEN** the person picks the last line and enters their own start command
- **THEN** the same questions are asked with empty answers and that command is recorded

#### Scenario: `--yes` with several usable

- **GIVEN** several candidates are usable
- **WHEN** `abk init --yes` runs without `--runtime`
- **THEN** it prints the list, exits 2 and writes nothing, and with `--runtime NAME` it proceeds with that one

#### Scenario: A kept configuration that names a runtime

- **GIVEN** a kept `abk.yaml` with `runtime:` set
- **WHEN** `abk init` runs
- **THEN** the question is not asked, and `--runtime` overrides only after confirmation or with `--force`

#### Scenario: The agent steps use the choice

- **WHEN** init runs research and propose after a choice
- **THEN** both receive the chosen runtime, and neither runs before the choice is made

#### Scenario: The written configuration loads

- **WHEN** init has written `abk.yaml` for the chosen runtime
- **THEN** it loads without warnings

#### Scenario: A fallback runtime

- **GIVEN** another usable candidate exists
- **WHEN** the person is asked about a fallback and accepts
- **THEN** that runtime is configured under `runtimes:` and `runtime:` names only the first

### Requirement: A runtime asks its own setup questions

A runtime SHALL be able to declare the questions its setup needs, each with a prompt, a default, a validator and the
key it writes. Init SHALL ask them in order, show the default, validate each answer when it is given and ask again on a
bad one, and let the person go back to choose another runtime. Init SHALL contain no question that belongs to one
runtime. A secret SHALL never be asked for or written to `abk.yaml`: only the names of environment variables the agent
needs.

#### Scenario: A bad answer is asked again

- **WHEN** the person gives a program that is not on the path
- **THEN** init says why and asks again

#### Scenario: Going back

- **WHEN** the person goes back at a runtime's question
- **THEN** the list is shown again and another runtime can be chosen

#### Scenario: A custom executable for the current runtime

- **WHEN** the person gives a wrapper script in place of the executable found on the path
- **THEN** that command is recorded

#### Scenario: A runtime added later

- **GIVEN** a runtime registered with its own questions and no change to init
- **WHEN** it is chosen
- **THEN** its questions are asked and its answers written where it says

#### Scenario: Secrets stay out of the file

- **WHEN** an agent needs environment variables
- **THEN** init asks for their names only and writes no value

#### Scenario: What an agent needs

- **GIVEN** a known agent whose table entry says it needs a running backend
- **WHEN** it is chosen
- **THEN** init asks whether the backend is running and whether to continue anyway

### Requirement: Models are offered only from what needs no model call

Choosing a model SHALL never make a model call. A runtime SHALL offer a list only from what its agent advertises when a
session is opened — which sends no prompt — from a command the agent has for printing its models, or from documented
static names; when none is available, init SHALL say the agent does not list its models, leave the roles empty and
accept a typed name that is not verified at that time. When a list is advertised, init SHALL show it per role with the
agent's current model marked as the default and keeping the agent's default first, and the choice SHALL be written
under `models:`. For a runtime with documented names, one question first SHALL offer the default models, a choice per
role or typed names.

#### Scenario: Defaults accepted, chosen or typed

- **GIVEN** a runtime with documented model names
- **WHEN** the person accepts the defaults, chooses per role from the list, or types names
- **THEN** each is written as given and none is tested by asking a model

#### Scenario: An agent that advertises models

- **GIVEN** an agent that advertises several models and its current one
- **WHEN** init lists them
- **THEN** each is shown with the current one marked as the default, and the person's choice lands under `models:`

#### Scenario: An agent that advertises none

- **GIVEN** an agent that advertises no models
- **WHEN** init reaches the models question
- **THEN** it says the agent does not list its models, leaves the roles empty and still accepts a typed name

#### Scenario: Listing sends no prompt

- **GIVEN** an agent that fails on any prompt it receives
- **WHEN** init lists its models
- **THEN** a session is opened and closed, no prompt is sent and nothing fails

### Requirement: Every answer has a non-interactive route, and nothing is written unconfirmed

Every answer init asks for SHALL be givable without a prompt: `--runtime`, `--agent-command`, repeatable `--set
<key>=<value>`, and `--runtime-config FILE`, a fragment merged into the draft and validated against the configuration
schema. All routes SHALL produce the same fragment as the typed answers, validated by the same checks, and an unknown
key SHALL fail naming it. Init SHALL print the `abk.yaml` fragment the answers produce and write only after the person
confirms; `--dry-run` SHALL print it and write nothing.

#### Scenario: The same fragment by every route

- **WHEN** one set of answers is typed, given by `--set` and given by `--runtime-config`
- **THEN** the three fragments are identical

#### Scenario: An unknown key

- **WHEN** `--set` or the fragment names a key the schema does not have
- **THEN** init fails naming the key and writes nothing

#### Scenario: Nothing written before confirmation

- **WHEN** the person declines at the confirmation
- **THEN** no file is written or changed

#### Scenario: A dry run

- **WHEN** `abk init --dry-run` runs
- **THEN** it prints the fragment and writes nothing

### Requirement: The policy step works for an agent nobody has seen

Init SHALL check whether the chosen agent refuses the forbidden command classes, and SHALL ask before running a check
that spends model tokens. A check that passes SHALL ask nothing further. For an unrefused class, the fix the
installation configures as `runtimes.<name>.policy_fix`, or a known agent's fix, SHALL be offered; for an unknown
agent, or one with no fix, init SHALL offer to rely on abk's own protocol layer and state how much of the agent's tool
use it can see, to supply the person's own fix command, or to continue without — recorded as unchecked, with a warning
on every `abk doctor` run and no probe. Before a fix runs, init SHALL show the command and the classes and spellings
that are not refused; the fix SHALL run with its output shown, never silenced. After any fix the check SHALL run again,
and init SHALL report, per class and spelling, what is now refused and what is still not, and SHALL report only what it
observed. A fix that exits non-zero SHALL be reported with its exit status and the check SHALL still run again. A fix
after which the same spellings are still not refused SHALL be reported as having made no change, naming them, so the
person learns that the policy content, not the fix, is what is missing.

#### Scenario: The check passes

- **WHEN** the check finds every class refused
- **THEN** nothing further about policy is asked

#### Scenario: A check that costs tokens

- **GIVEN** a runtime whose check prompts the agent
- **WHEN** the policy step starts
- **THEN** init says it spends tokens and asks before running it, and a refusal records the entry as unchecked

#### Scenario: A known fix is offered

- **GIVEN** the check finds a class unrefused and the agent has a fix
- **WHEN** init offers it
- **THEN** the fix runs only on a yes, and the check runs again

#### Scenario: An unknown agent

- **GIVEN** an agent without a known fix and a class unrefused
- **WHEN** the policy step runs
- **THEN** init offers the three choices and guesses none

#### Scenario: A fix that did not work

- **WHEN** a fix has run and the check still finds a class unrefused
- **THEN** init reports the class as still unenforced and does not claim a pass

#### Scenario: The fix is shown before it runs and its output is not hidden

- **GIVEN** a configured fix and one class unrefused in one spelling
- **WHEN** the policy step reaches the fix
- **THEN** the fix command and that class and spelling are printed before it runs, and what the fix prints reaches the
  person

#### Scenario: What is now refused and what is not

- **GIVEN** a fix after which one spelling of a class is refused and another is not
- **WHEN** the check runs again
- **THEN** init prints each class and spelling as refused or not, and exits 1 under `--policy-only`

#### Scenario: A fix that exits non-zero

- **GIVEN** a fix that exits with status 3
- **WHEN** it has run
- **THEN** init reports the exit status 3 and still runs the check again

#### Scenario: A fix that changes nothing

- **GIVEN** a fix that exits 0 and leaves every unrefused spelling unrefused
- **WHEN** the check runs again
- **THEN** init says the fix made no change and names the spellings still not refused

#### Scenario: A spelling let through

- **GIVEN** a check that refuses a class in its plain spelling and lets one spelling through
- **WHEN** the policy step runs
- **THEN** that spelling is named before init finishes, and a known-agent table row claims a spelling covered only when
  its note records a live check that showed it, and otherwise reads UNVERIFIED

#### Scenario: A kept configuration reaches the policy step

- **GIVEN** a kept `abk.yaml` with `runtime:` set and a configured fix
- **WHEN** `abk init` runs
- **THEN** the runtime question is not asked, the policy step runs, and the configured fix is offered and applied

### Requirement: The policy step can be run alone on an existing installation, and with a fix given by flag

`abk init --policy-only` SHALL load the existing `abk.yaml`, identify the selected runtime, run the policy step and
nothing else: no repo detection, no research, no propose, no commit and no other change to the file. It SHALL exit 0
when the check passes after the step, 1 when a class is still not refused, and 2 on a usage problem (no `abk.yaml`, an
unknown runtime, a flag that cannot be used with it). It SHALL write `runtimes.<name>.policy_fix`, or `policy:
unchecked`, only when the person chose to record it, after showing the change and asking, and under `--yes` only for a
value given by flag. A check that spends model tokens SHALL be asked about before it runs unless `--yes` is given.
`--policy-fix ARGV` SHALL supply the fix command and record it as `policy_fix` once validated as an existing
executable; it SHALL be usable with or without `--yes` and with or without `--policy-only`. Under `--yes`, a configured
fix SHALL run unasked only when `--policy-fix` or `--run-policy-fix` is also given, because running a command an
operator supplied, unattended, must be explicit; without either, `--yes` SHALL report the unrefused classes, run no
fix and exit 1.

#### Scenario: Only the policy step runs

- **GIVEN** an existing planning repo with `abk.yaml` naming a runtime
- **WHEN** `abk init --policy-only` runs
- **THEN** no repository is detected, research and propose do not run, nothing is committed, and the file changes only
  by a recorded fix or marker

#### Scenario: The check passes after the step

- **GIVEN** a stand-in agent that lets one spelling through and a configured fix that patches it
- **WHEN** `abk init --policy-only` runs, the person agrees to the check and to the fix
- **THEN** the check is refused-after for every class and spelling, and the exit status is 0

#### Scenario: A class is still not refused

- **WHEN** the check after the step finds a class or spelling not refused
- **THEN** it is named and the exit status is 1

#### Scenario: A usage problem

- **WHEN** `abk init --policy-only` runs with no `abk.yaml`, or with `--runtime` naming an unknown runtime
- **THEN** it says what is wrong, writes nothing and exits 2

#### Scenario: A fix command by flag

- **WHEN** `abk init --policy-only --policy-fix ARGV` runs and ARGV is an existing executable
- **THEN** it is recorded as `policy_fix` after the confirmation, run, and followed by the check; an ARGV that is not
  an existing executable exits 2 and records nothing

#### Scenario: Nothing recorded unconfirmed

- **WHEN** the person declines the confirmation before the write
- **THEN** `abk.yaml` is unchanged, and the fix, if already confirmed, still runs on the configured value

#### Scenario: `--yes` does not run a configured fix by itself

- **GIVEN** a configured fix and an unrefused class
- **WHEN** `abk init --policy-only --yes` runs with neither `--policy-fix` nor `--run-policy-fix`
- **THEN** the unrefused classes are reported, no fix runs and the exit status is 1

#### Scenario: `--yes` with an explicit fix

- **WHEN** `abk init --policy-only --yes --run-policy-fix` or `--policy-fix ARGV` runs
- **THEN** the fix runs without a question and the check runs again

#### Scenario: A check that costs tokens is asked about

- **GIVEN** a runtime whose check prompts the agent
- **WHEN** `abk init --policy-only` runs without `--yes`
- **THEN** it says the check spends tokens and asks before running it, and a refusal exits 1 without recording
  anything

### Requirement: `abk doctor` reports the machine's other runtimes

`abk doctor`'s runtime check SHALL use the same probe to report, as information, the other usable runtimes on this
machine, SHALL warn when the selected entry is one whose verification is only documented, and SHALL NOT probe an entry
recorded as unchecked, warning instead on every run.

#### Scenario: Other usable runtimes

- **GIVEN** a second runtime is usable on this machine
- **WHEN** `abk doctor` runs
- **THEN** it is reported as information, and the selected runtime's checks are unchanged

#### Scenario: A documented-only entry

- **GIVEN** the selected entry's verification is only documented
- **WHEN** `abk doctor` runs
- **THEN** it warns that the start command was not verified

#### Scenario: An unchecked entry

- **GIVEN** the selected entry is recorded as unchecked
- **WHEN** `abk doctor` runs
- **THEN** it warns and sends the agent no prompt

### Requirement: The real command is driven end to end against a stand-in agent

The acceptance run SHALL drive `abk init` as a subprocess against a stand-in agent that speaks the protocol and fails
the run if it ever receives a prompt other than the policy check's, covering the candidate list, the choice, a model
list or its absence, the written configuration, the confirmation and the refusals, and `abk init --policy-only` against
a stand-in that lets a spelling through, with a fix command that patches it and one that changes nothing.

#### Scenario: Init against a stand-in agent

- **GIVEN** a scratch planning repo and a stand-in agent on the path that fails on any prompt
- **WHEN** the real `abk init` runs, lists the candidates and the stand-in is chosen
- **THEN** usable and unusable candidates are listed with reasons, the written `abk.yaml` loads, `abk doctor`'s runtime
  check passes, and no prompt reached the stand-in

#### Scenario: An installed agent, when present

- **GIVEN** an agent installed on the host, and otherwise skipped
- **WHEN** init lists against it
- **THEN** no prompt is sent and a model list is reported only if the agent advertises one

#### Scenario: `--policy-only` applies a fix on an existing installation

- **GIVEN** a scratch planning repo whose `abk.yaml` names a stand-in agent that lets one spelling through, and a fix
  command that patches the stand-in's policy
- **WHEN** the real `abk init --policy-only` runs and the person agrees to the check and the fix
- **THEN** the report shows the spelling as not refused before and refused after, and the exit status is 0

#### Scenario: `--policy-only` with a fix that changes nothing

- **GIVEN** the same stand-in and a fix command that exits 0 without patching anything
- **WHEN** the real `abk init --policy-only` runs
- **THEN** the output says the fix made no change and names the spelling still not refused, and the exit status is 1
