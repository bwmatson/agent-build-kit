## ADDED Requirements

### Requirement: The dry guidance is proven with a real agent by structural assertions

There SHALL be tier-2 acceptance tests that build small units with a real agent in a scratch application that tempts
duplication, and review units with a real agent, and that decide the outcome by parsing what the agent wrote: the
definitions a branch adds, the occurrences of a key literal, and the calls from one definition to another resolved by
name. No assertion SHALL depend on a model's reading of the output. The helper that does the parsing is test code and
MAY be specific to the scratch application's language. The tests SHALL be marked to run where the framework's other
acceptance tests run and not in the default suite, SHALL fail and not skip when the agent command is not set, SHALL
run each case once, and SHALL run each agent-driven tick under a timeout shorter than the tier-2 time limit. The
helper SHALL be covered by an unmarked test with a copy it must flag and a delegating function it must not. A failure
SHALL carry the diff, the definitions counted as added, and the agent's transcript tail. An assertion SHALL NOT be
weakened to make a run pass.

#### Scenario: A task names a helper an existing function covers

- **GIVEN** a scratch application with one helper of a distinctive body, and a task that names a new helper doing the
  same
- **WHEN** a real agent builds the unit
- **THEN** the branch adds no definition whose normalised body matches the helper's, the helper's key literal occurs
  once in the source, and the code the task names calls the existing helper

#### Scenario: A task needs a variant of an existing function

- **GIVEN** the same application and a task for a variant of the helper
- **WHEN** a real agent builds the unit
- **THEN** the existing function's source differs from the base's, its key literal still occurs once, no added
  definition matches its body, and its earlier tests still pass

#### Scenario: Logic is needed at two call sites with no helper

- **GIVEN** a task for two functions in two modules that need the same formatting, and no helper for it
- **WHEN** a real agent builds the unit
- **THEN** the branch adds the two functions and exactly one other definition, the formatting's key literal occurs
  once, and both functions call that definition

#### Scenario: The prompts reached the agent

- **GIVEN** the prompts a real agent was sent in one built unit, recorded at the agent's protocol and not from its
  own account
- **WHEN** they are read
- **THEN** the tests step's prompt holds the reuse part and the three-way instruction, the implementing prompt
  holds the repointing line, no continuation prompt holds the reuse part, and the review prompt holds the
  prior-art clause

#### Scenario: A seeded duplicate is blocked

- **GIVEN** a unit whose branch holds a tests commit and an implementation that re-implements an existing helper
- **WHEN** a real agent reviews it with one review round allowed
- **THEN** a finding is required and names the existing function or its file

#### Scenario: A clean unit is not blocked for a duplicate

- **GIVEN** a unit whose implementation calls the existing helper
- **WHEN** a real agent reviews it
- **THEN** no required finding names the existing helper or its file

#### Scenario: The assertion helper tells a copy from a call

- **GIVEN** a source with a renamed copy of a function and one with a function that only calls it
- **WHEN** the helper compares each with the original
- **THEN** the copy is flagged as a duplicate and the delegating function is not

#### Scenario: The default suite stays hermetic

- **WHEN** the default test suite runs
- **THEN** the agent-driven tests are not among it

#### Scenario: A failure is attributed

- **WHEN** a case fails
- **THEN** the failure says whether the prompt was not delivered, the agent copied, or the assertion was stricter
  than the guidance asks, from the recorded prompts, the diff and the definitions counted
