# Spec Delta

## Purpose

Defines how init's policy step uses the kit's own recommended policy as the fix it offers for an agent the kit knows how to
patch, so the step no longer depends on the agent's own repository being present.

## ADDED Requirements

### Requirement: A known-agent row may carry an applier descriptor

A row of the known-agent table MAY carry an apply descriptor: the variable the agent reads for its home and the default home,
the configuration file, its format, the key path of its list of refused commands, how its scalars are read, an optional
recommended toolset, and how the entry was verified. Only the table's rows and tests under the runtimes package SHALL name an
agent product; the engine SHALL be product-neutral. A row without a descriptor SHALL have no applier, and nothing SHALL
guess a path for it.

#### Scenario: Every descriptor is complete

- **WHEN** the table's structural test runs
- **THEN** every descriptor names a home variable, a default home, a file, a format with a writer, a key path and a
  verification note, and a row's descriptor that is incomplete fails naming the row

#### Scenario: An unverified agent has none

- **WHEN** a row has not been verified against the agent's own configuration
- **THEN** it carries no descriptor, and the policy step offers the patterns to place by hand

#### Scenario: Only the table and its tests name an agent

- **WHEN** the framework's text is scanned for agent product names
- **THEN** they appear in the known-agent table's rows and in tests under the runtimes package and nowhere else

### Requirement: The policy step offers the kit's recommended policy as the fix

When the check finds a class unrefused, the installation sets no fix, and the selected agent has an applier, init's policy
step SHALL offer to apply the kit's recommended policy: it SHALL show the configuration's path and the diff, ask before
writing, show the applier's output, run the check again and report what is now refused and what is not. An installation's
own fix SHALL take precedence when it is set. Under the assume-yes flag the built-in fix SHALL run only when the flag that
authorises a fix is also given. The step SHALL NOT apply the build-run toolset; it SHALL say how to. For an agent with no
applier, the step SHALL print the recommended patterns' command among its choices.

#### Scenario: The kit's fix is offered when the installation has none

- **GIVEN** a class unrefused, no configured fix, and an agent with an applier
- **WHEN** the policy step runs
- **THEN** init shows the configuration path and the diff and asks before applying the kit's recommended policy

#### Scenario: A yes applies it and the check runs again

- **WHEN** the person confirms
- **THEN** the policy is applied, the check runs again, and init prints per class and spelling what is now refused and what
  is not, never claiming a pass it did not observe

#### Scenario: A no leaves everything unchanged

- **WHEN** the person declines
- **THEN** no file is written, the missing guarantee is stated, and `abk init --policy-only` exits 1

#### Scenario: The installation's own fix wins

- **GIVEN** a configured fix and an agent with an applier
- **WHEN** the policy step runs
- **THEN** the configured fix is the one offered, and the kit's applier is not

#### Scenario: Assume-yes does not run it unasked

- **GIVEN** a class unrefused, no configured fix and an agent with an applier
- **WHEN** init runs with the assume-yes flag and without the flag that authorises a fix
- **THEN** no file is written, the unrefused classes are named and the exit status is 1, and with the authorising flag the
  fix is applied without asking

#### Scenario: A fix that did not cover a spelling

- **GIVEN** an applied policy after which the check still finds one spelling unrefused
- **WHEN** the check runs again
- **THEN** init names that spelling as still not refused, and says the agent's own matcher, not the list, may be what lets
  it through

#### Scenario: An agent whose configuration is absent

- **GIVEN** an agent with an applier whose configuration does not exist
- **WHEN** the policy step runs
- **THEN** init says the agent's configuration was not found, offers nothing to apply and prints the command that prints the
  patterns

#### Scenario: An agent with no applier

- **GIVEN** an agent with no apply descriptor and a class unrefused
- **WHEN** the policy step runs
- **THEN** among its choices init offers to print the recommended patterns for the person to place in the agent's own
  configuration

#### Scenario: The toolset is a separate decision

- **WHEN** the kit's fix has been applied from init
- **THEN** the build-run toolset is unchanged, and the output names the command that applies it
