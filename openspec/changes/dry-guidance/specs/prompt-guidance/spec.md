## ADDED Requirements

### Requirement: Builders are told to find and reuse existing code

The full prompts for writing tests, implementing, fixing checks and reworking SHALL include a part that tells
the agent to search for an existing helper, constant, pattern, fixture or test helper before adding one and to use or
extend it; to write logic needed in two places, including two variants of one feature, once; to give calls that must
change together one function; to use the shared test support; to delete what its change makes dead; and to stay
within the change. A continuation prompt that resumes a session which already holds the part SHALL NOT repeat it. The part SHALL name no
installation, language, tool or path.

#### Scenario: Every builder prompt carries it

- **WHEN** the prompt for writing tests, implementing, fixing checks, reworking after review, reworking after
  feedback is built
- **THEN** it contains the reuse part

#### Scenario: A continued session is not told again

- **GIVEN** a build session that began with the prompt for writing tests
- **WHEN** a later node continues that session with its continuation prompt
- **THEN** the continuation prompt does not contain the reuse part

#### Scenario: A node that starts a new session

- **GIVEN** a unit that enters past the tests, a session that could not be continued, or session reuse switched off
- **WHEN** a node starts a new session
- **THEN** its full prompt contains the reuse part

#### Scenario: The adapt prompt keeps its own instruction

- **WHEN** the prompt for adapting to a changed predecessor is built
- **THEN** it does not contain the reuse part, and still tells the agent not to re-implement what the
  predecessor provides

#### Scenario: The part names nothing specific

- **WHEN** the part is read
- **THEN** it names no installation, language-specific tool or file path

#### Scenario: Braces in the part

- **WHEN** the prompts are filled in
- **THEN** the part does not break the filling and appears unchanged

### Requirement: The agent is told how to find existing code without configuration

The part SHALL tell the agent to read what the neighbouring code imports, to look in the modules and directories a
repository names for shared code and in the test runner's usual places for shared test support, to use the
language's conventions or, for an unfamiliar language, common ones, and to search by the behaviour of what it is
about to write as well as by name. The pipeline SHALL NOT read, inject or draft a repository section for this.

#### Scenario: No configuration

- **GIVEN** a repository that says nothing about where shared code lives
- **WHEN** a builder prompt is built
- **THEN** the guidance on how to look is the same and nothing is missing

### Requirement: Feedback about one duplicate leads to a search for the others

The prompts for acting on review feedback, for fixing checks and for reworking SHALL tell the agent that when
feedback names one duplicate it looks for the others of the kind (the first two already do, and keep their
wording), and the prompt for writing tests SHALL point to the shared fixtures
before new ones are written.

#### Scenario: Feedback names a copied helper

- **WHEN** review feedback says a helper was copied
- **THEN** the prompt tells the agent to look for other copies of the same kind

### Requirement: The reviewer searches for prior art for what the change adds

The review prompt SHALL ask, for each new function, constant, pattern or test helper in the diff, for a search for
an existing equivalent and for a second copy within the diff, and for the existing one to be named by file and
line.

#### Scenario: A new helper with an existing equivalent

- **GIVEN** a diff that adds a function equivalent to one elsewhere in the repository
- **WHEN** the reviewer reviews it
- **THEN** it names the existing function by file and line

### Requirement: A duplicate the change introduces is a required finding

The review prompt SHALL tell the reviewer that a duplicate the change introduces or makes worse is a required
finding whose consequence is that two copies must change together, and SHALL say what done looks like: use or
extend the existing one, or extract one shared function. It SHALL NOT ask for a finding about duplication that was
already present and that the change neither adds to nor extends.

#### Scenario: A copied test helper

- **GIVEN** a diff that copies a test helper from another file
- **WHEN** the reviewer finds it
- **THEN** the finding is required, its consequence is stated, and done is to use the shared one

#### Scenario: Duplication that was already there

- **GIVEN** a duplicate in code the diff does not touch
- **WHEN** the reviewer reviews the diff
- **THEN** the prompt gives it no reason to report it, even as an optional follow-up

#### Scenario: Design-level refactors keep their split

- **WHEN** fixing a finding well needs a design decision across several callers
- **THEN** it is optional, as before

### Requirement: Writing tests first does not pin a duplicate function

The prompt for writing tests SHALL tell the agent that when a task names code to add, or the same logic is needed in a
second place, it searches for an existing equivalent before it adds a stub and decides which case applies. Where an
existing function does the job, the agent SHALL test through it, add no stub, and report the reuse in its summary.
Where an existing function nearly does the job, the tests SHALL target that function's missing behaviour and no new
name SHALL be created. Where no reusable helper exists and two places need the logic, the agent SHALL stub one helper
at the place the repository keeps shared code, test it at its own interface and test each call site, and SHALL NOT
stub a copy per call site. The agent SHALL prefer asserting behaviour at the nearest existing entry point to asserting
on a new internal name, and SHALL stub a name that is a contract as named. The prompt SHALL tell the agent to put new
tests in files in which every test fails before the implementation. The paragraph SHALL name no installation,
language-specific tool or path.

#### Scenario: An existing function does the job

- **GIVEN** a task that names a function for which an equivalent already exists
- **WHEN** the agent writes the tests
- **THEN** it tests through the existing function, adds no stub, and its summary says it reused the existing one
  instead of adding the named one

#### Scenario: An existing function needs generalizing

- **GIVEN** an existing function that lacks one case the change needs
- **WHEN** the agent writes the tests
- **THEN** the tests target the existing function's missing behaviour, they fail because it is missing, and no new
  function name is created

#### Scenario: A new helper needed in two places

- **GIVEN** logic needed in two places for which no helper exists
- **WHEN** the agent writes the tests
- **THEN** there is one stub, at the place the repository keeps shared code, with tests for its own interface and for
  each call site, and no second copy is stubbed per call site

#### Scenario: A named contract

- **GIVEN** a task that names a public function, command or wire shape
- **WHEN** the agent writes the tests
- **THEN** the name is stubbed and tested as named

#### Scenario: A conversion with no new behaviour

- **GIVEN** a call site that is only to be converted to an existing or shared function
- **WHEN** the agent writes the tests
- **THEN** the test shows the call site reaching that function, which fails before the conversion, and the tests are
  in a file in which every test fails

#### Scenario: The paragraph is in the tests prompt only

- **WHEN** the prompt for writing tests and the other builder prompts are built
- **THEN** only the prompt for writing tests contains the paragraph about deciding before stubbing

### Requirement: Implementing may repoint a test at existing code

The prompt for implementing, in its full form and as a continuation, SHALL tell the agent that when a stub the tests
added duplicates existing code it deletes the stub and repoints the test at the existing function with the same
assertions, that this is not weakening a test, and that its summary says so. Both SHALL keep the sentence "Do not
weaken or delete a test to make it pass". The line SHALL be present in the continuation although the reuse part is
not, because it concerns the tests commit in hand. It SHALL add no placeholder, and no other continuation prompt SHALL
carry it.

#### Scenario: A duplicate stub is replaced

- **GIVEN** a stub added by the tests commit that duplicates an existing function
- **WHEN** the agent implements
- **THEN** it may delete the stub and repoint the test at the existing function with unchanged assertions, and its
  summary says so

#### Scenario: Weakening is still refused

- **WHEN** the implementing prompt or its continuation is built
- **THEN** it still tells the agent not to weaken or delete a test to make it pass, and a changed assertion is not
  covered by the exception

#### Scenario: A continued session

- **GIVEN** a build session continued with the implementation continuation
- **WHEN** the continuation is filled in
- **THEN** it contains the repointing line and its changelog placeholder is filled, and it does not contain the
  reuse part

#### Scenario: A node that starts a new session

- **GIVEN** an implementing step that enters past the tests, after a fallback, or with reuse switched off
- **WHEN** its full prompt is built
- **THEN** it contains the repointing line

### Requirement: The reviewer counts a stub the tests commit added

The review prompt SHALL tell the reviewer that a stub or helper added by the tests commit is part of what the change
adds and gets the same search for an existing equivalent, and SHALL tell it that a test repointed at an existing
function with unchanged assertions is not a finding.

#### Scenario: A stub with an existing equivalent

- **GIVEN** a diff whose tests commit stubs a function that has an existing equivalent
- **WHEN** the reviewer reviews it
- **THEN** it raises it as a duplicate the change introduced, naming the existing function by file and line

#### Scenario: A repointed test

- **GIVEN** a test repointed at an existing function with the same assertions
- **WHEN** the reviewer reviews it
- **THEN** the prompt gives no reason to report it

### Requirement: The authoring guidance tells authors to describe behaviour

The authoring guidance that ships with the framework SHALL tell authors that a task describes behaviour and names a
new function, class or constant only when the name is a contract, with a good and a bad example in no particular
language. It SHALL name no installation. Copies already written into a planning repository SHALL NOT be changed except
by running the install command again, which the changelog says.

#### Scenario: A task that names a helper

- **WHEN** the authoring guidance is read
- **THEN** it says to replace "add a helper that does X" with what must be true, unless the name is a contract

#### Scenario: A stale copy

- **GIVEN** a planning repository whose copy of the guidance predates this change
- **WHEN** nothing has run the install command
- **THEN** the copy is unchanged
