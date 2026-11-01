# Testing strategy: how the kit classifies, writes, checks and fixes tests

The kit builds code by writing tests first, proving they fail, and then writing the code that makes them pass. That loop only
saves effort when the tests are trustworthy: when a failure means the code is wrong, and a pass means it is right, on a quiet
machine and on a loaded one. This document states the target: what kinds of test there are and where each runs, how the
test-first loop is proved and not only requested, the standards a test is held to, how a failing test is classified before anyone
spends a fix on it, and how the same rules reach every agent and every toolchain.

It is a design: the state the kit is moving toward. It holds no status, no order of work and no code references; how and when each
part is delivered is kept outside the kit, in an implementation plan that points back to the standard numbers used here.

## Goals and non-goals

**Goals**

- A test has one kind, and the kind says where it runs and what it may need.
- The test-first loop is enforced by a program in the build, not by an instruction to the agent. A test that was not seen to fail,
  or failed for the wrong reason, goes back to the agent that wrote it before any code is built on it.
- Every test is held to one numbered catalogue of standards. A guard failure, a review finding and a fix change all cite the
  standard's number, and a new test and an existing one are compared against the same list.
- A failure is classified by cause before a fix is written: the code, the test, the machine's load, or isolation between tests.
  Only the first two get a fix change.
- Tests, guards and the toolchain behave the same under heavy parallel load as on a quiet machine.
- Every toolchain profile has the same test capabilities. A gap is a defect that a test finds, not a silent fallback.
- Standing guidance reaches each agent by the channel that suits the agent, and whatever a program can decide is decided by a
  program before a reviewer is asked.

**Non-goals**

- Choosing a test framework. The profile owns that; this design says what every profile must be able to do.
- Replacing review. The reviewer keeps the judgement a guard cannot make.
- A coverage target. The loop proves each new test can fail; it does not measure how much code is covered.
- Rules for one installation's code. A project's own standards live in the project and reach its agents through its own files.

## Vocabulary

**Test kind.** A task group is tagged `[unit-test]`, `[integration-test]` or `[e2e-test]`. A unit's *tier* is the widest kind among its
groups. An `[e2e-test]` group is built on its own and writes tests only. The tests of an `[integration-test]` group carry the
`integration` selector below, and the build checks it.

**Terms used throughout.** A *unit* is the work the pipeline builds, reviews and lands as one pull request, made of one or more task
groups; it is not a unit test. A *floor* is the least a group's mode may be, set by the paths its tasks name: a group that names
source files must keep its tests. The *red check* is the check that a new test fails before its implementation exists (see "TDD as a
proved loop"). The *push gate* is the same check run by a person or a hook on a branch. The *checks round* is the step after a unit's
tests run, where lint, types and the standards check run. A *stubbed build* writes signatures that only raise before the tests.
*Affected selection* chooses the tests whose covered code a change touched. A *tree-wide test* reads many files across the
repository; a *wide scan* is the kind that walks the whole tree, and a *conformance test* checks that documents, configuration,
layout or code structure agree.

**Group mode.** `tests_and_code` (a test commit, then a code commit), `tests_only` (a lone test commit, no code), `no_code` (a lone
code commit, no tests: documents and configuration), `refactor` (a lone code commit that reorganizes code and edits existing tests
only mechanically; see "Reorganizing code"). A group's mode has a floor set by the paths its tasks name (a `refactor` group is the
exception), and an author can raise the floor by stating a reason.

**Review tier.** `auto`, `light` or `full`: how much review a unit gets. It is a separate axis from the test kind and from the
group mode.

**Selector.** What a test declares about itself so that a run can include or leave it out: a marker, a file-name convention, a tag or
category attribute, or whatever the toolchain offers. The kinds are the same in every language; how a toolchain spells them is its
profile's business (see "How a toolchain realises the selectors"). Where this document says *marker*, it means a selector.

## Where a test lives, and which kind it is

A builder decides in this order.

1. It needs a live service, credentials, a model, an agent, or an MCP or API call: **e2e**. It carries the e2e selector, named `e2e`
   (a repository may name it otherwise by configuration), and the runtime tag where a runtime applies.
2. Otherwise it needs only what a CI job can give it, or it reads the whole repository, or it collects other modules in a child
   run, or it checks something that is not code behaviour: **integration**. It is wider than one file's behaviour: it exercises
   several modules together, a process or tree boundary, or the repository itself, and it uses no live service. The last case is a
   *conformance test* of the repository: documents say what the code does, configuration files, CI templates, layout, names and
   selector registrations agree, a guard's list is current. Conformance tests have real value. They are integration tests because
   they read the tree, not because they are suspect.
3. Otherwise it is a **unit** test: pure logic, fakes, temporary folders. It does not walk the repository.

**Placement.** A new test goes into the existing test file for its subject, a file named for the module it exercises. A new test
file is created only when a new logic file is created for the unit under test. A new behaviour of an existing module is a new case
in that module's existing test file, never a new file. File names are unique across the tree.

**Folders say the kind.** Unit tests sit under the tests root, mirroring the source tree. Integration tests live in an `integration`
folder and e2e tests in an `e2e` folder, each at the root of the project's tests, and inside them the files are grouped by subject.
A reader can then tell a test's kind from its path, a run can be pointed at a folder as well as at a selector, and a test never needs
its selector read to know where it belongs. The folder and the selector must agree: an e2e test in the integration folder is
misfiled even when its selector is right, and the same holds for an integration test outside its folder. Helpers shared by a kind's
tests live in that kind's folder.

**Where each kind runs.**

| Kind | Unit gate | CI | Elsewhere |
|---|---|---|---|
| unit | all of them | yes | |
| integration | only the ones the unit added or changed, and the ones whose covered code the unit changed (the same affected selection the unit tests use) | **every one, on every pull request, as a required check** | |
| e2e | no | never | where a stack exists: the e2e-test step, the scheduled run |

An integration test runs in a unit's local build and checks only when the unit added or changed it, or changed the code it covers.
The ones the unit added are run before its pull request opens, red first and repeated like any new test, and the ones the change
might have affected are run so a regression is found before review. CI runs every integration test on every pull request whatever
the change, and it is the backstop for the ones the local selection could not know about.

### Kind selectors

The names below are the canonical ones. Every toolchain gives each a spelling (next section), and the default run of a repository
leaves out the `integration` and `e2e` selectors. The e2e selector is named for what the test is, never for how a stack is run.

| Selector | Meaning | In the default run | In CI |
|---|---|---|---|
| none (unit) | pure logic, fakes, temporary folders; deterministic on a loaded machine; does not walk the repository | yes | yes |
| `integration` | runnable in CI: needs only what the CI job provides (the toolchain, public package hosts, local subprocesses), or reads the whole repository, or collects modules in a child run. No credentials, no live service, no model, no agent, no MCP or API call | no | **yes, all** |
| `e2e` | needs a live stack, credentials, a model, a real agent or an MCP or API call; bills or takes minutes | no | no |
| runtime tags | which agent runtime an e2e test drives; at most one per test | with `e2e` | no |
| stack tags | what an e2e test needs beside the stack | with `e2e` | no |
| a per-test limit | a budget in place of the default, for a test whose cost is outside its control | any | any |

### How a toolchain realises the selectors

Every profile provides the same six *selector capabilities*, each in the toolchain's own terms. The examples are illustrations, not a
list of supported toolchains: a profile for another language chooses whatever its runner offers and says so in the profiles
document.

| Capability | A pytest project | An npm project with vitest | Another toolchain, for example |
|---|---|---|---|
| Declare a kind on a test (and keep the file in the kind's folder) | a registered marker | a file-name convention (`<name>.integration.test.ts`, `<name>.<e2e>.test.ts`) | a tag or category attribute, a build tag, a separate test directory or target |
| The default run leaves out `integration` and e2e | a deselecting `-m` expression in the repository's configuration | include and exclude patterns in the runner's configuration | the same, in the runner's configuration |
| Select by id, overriding the default | the test's node id, with the marker expression overridden for it | a file path or a name filter, with the exclusion overridden for it | a name or tag filter that wins over the default |
| Unknown kinds are refused | strict marker registration | a conformance test over the configured patterns | a conformance test, or the runner's own strictness |
| At most one kind per test | a conformance test over the markers | a file matches one convention only | a conformance test over the declarations |
| A per-test limit override | a limit marker | the runner's per-test timeout option | the runner's per-test timeout option |

A profile that cannot provide one of the six says so explicitly, and the conformance test over the profile registry (see "Profile
parity") treats a missing capability as a defect. The rest of this document says *selector* and *marker* interchangeably and never
assumes one toolchain.

**No test is `serial`.** A test that cannot run beside others has a design fault: a shared port, path, session id, environment
variable or global. The fix is isolation, not a marker. No toolchain registers a `serial` selector, so a test that declares one is
refused (by strict registration where the runner has it, by a conformance test where it does not).

**A test that cannot run in CI is never `integration`.** The question that tells them apart is whether the test needs a value CI
cannot supply. A setting with no default (a required field of a settings type, an environment variable read with no fallback)
must come from the environment and is real configuration; a setting that has a default is not a secret and does not count. A test
marked `integration` that loads such a setting, starts a real agent, or calls a host other than loopback and the package hosts the
CI job provides is a misclassified e2e test. A guard over the integration tests finds these by reading the project's settings types
and the tests' environment reads, in the project's own language, so it follows the types and needs no list.

**One kind at most** from {unit, `integration`, `e2e`}. An e2e test carries exactly one runtime tag where a runtime applies. Each
toolchain's registration text quotes the table above.

**Every conformance test is an integration test**, whatever it checks: documents against behaviour, configuration, layout, names,
selector registrations, or the structure of the code itself (the profile registry). It reads the tree or the registry and nothing
live, so it runs in CI on every pull request and never in the unit gate unless the unit added or changed it, or changed a file it
declares. A tree-wide test that declares nothing is refused.

**Multi-project workspaces.** A project's conformance tests stay in that project and read only that project's files (standard T12a).
A check that spans projects is a *workspace conformance test* at the repository root, marked `integration`, and is the only place
that may name every project. CI runs each project's set and the root set.

## TDD as a proved loop

The build writes the tests and signatures first, commits them as `test:`, then writes the code and commits it as `feat:`. The build
checks the shape (a `test:` commit followed by a `feat:` commit of the same title, stubs that are only a raise or a constant) and
lint, format and types at the tests commit. The rest of the loop is proved at the tests commit by the red check.

**The red check runs in the build, at the tests commit, before the implementation step.** It runs the tests the commit added or
changed, by id, and accepts the commit only if every one of them fails, and fails for a reason that shows the behaviour is missing:
an assertion failure or a not-implemented signal. A passing test, or an error in collecting, setting up or compiling the test, is
rejected and the tests agent is asked again. In the stubbed build a missing name is also rejected, because the stub should have
supplied it. The pull request text says the tests were committed first and seen to fail only when the check ran.

- **By id.** Selecting by id lets a failing new case sit beside passing tests in the file for its subject, so the placement rule
  above does not fight the loop. A commit that changes only a helper or a shared fixture file, which has no test to select, runs its
  files whole.
- **Integration tests too.** The repository's default selection deselects an integration test even when it is named by id, so the
  selection overrides the default for the ids the commit added or changed. The unit's later runs add the integration tests that its
  affected selection picks, with the same override.
- **Test-only and no-code groups.** A `tests_only` group has no implementation to wait for; a `no_code` group has no test. They skip
  the check by their mode, and the pull request text says so.
- **Repeat.** After the unit's tests pass, the tests it added or changed run again, under the same workers, a configured number of
  times. A new test that fails on the second run is the unit's own failure, never excused as a flake.
- **Reorganizations** skip the check by their mode, and need no new test (see "Reorganizing code").
- **No test for a test.** A group that edits only test code needs no test of its own. A test that restates that another test is not
  flaky, or asserts another test's text, is a duplicate of the repeat check.
- **Selection is trustworthy before it is relied on.** A selection of the affected tests is a shortcut to a failure, never the proof
  of a pass: the full suite is the gate before review, and CI is the backstop. A selection that misses a test its change breaks is a
  defect in the recording of the dependencies, and the recording is itself tested for completeness.

## Reorganizing code

A reorganization changes where code lives or how it is arranged, and not what it does: a move, a rename, a split or a merge of
modules, an extraction, an inlining. Its proof is the tests that already exist. The loop above, which asks for a failing test
first, does not apply to it, and no new test is asked for.

**The existing tests pass, with only mechanical edits.** A mechanical edit changes a name or a location and nothing a test says: an
import path, a patch target named by a string, a module, function, attribute, selector or marker name renamed or moved (including
where a test asserts the name), a fixture or helper moved or renamed with the code it serves (its callers following), and a test
file moved or renamed with its module so that placement (T2) still holds. A test's arrangement, its expected values and its
assertions stay as they are. These are not mechanical: changing or deleting an assertion or an expected value, changing what a
function or fixture takes, returns or does (its parameters, its result, its behaviour), deleting a test, skipping it or marking it
expected to fail, raising a time limit, and adding a case. A reorganization that needs one of them has changed behaviour. It is
split, and the behaviour part is built tests first like any other change.

- **A `refactor` mode.** The planner declares it as a group mode, like the others. A `refactor` group may name source files, test
  files or both (a pure move of test files names tests only); source files carry a floor of `tests_and_code`, and the mode is
  accepted regardless: the comparison (T26) refuses edits that are not mechanical and review refuses added behaviour. A
  `refactor` group is one code commit that carries its mechanical test edits. It has no tests commit and no red check, and the pull
  request text says it was a reorganization and that no test was added. Without the mode, a group that names source files has a
  floor of `tests_and_code`, so the build would ask for a test commit, and a test that already passes on the old code would be
  rejected by the red check.
- **Proof before and after.** The tests that cover the moved code run on the parent commit and are green, and run again on the
  reorganization and are green, with the same ids up to the renames. Code with no covering test is first covered by a
  *characterization test*, committed on its own before the move. It passes on the old layout, so red does not apply to it, and it
  must pass unchanged after the move. That is the only case that adds a test.
- **A deterministic check before review.** A program compares each changed test file before and after. After names are normalised,
  the assertions and expected values are unchanged, the number of tests is the same, and no skip, expected failure or marker has
  been added and no limit raised. It reports a violation by standard ID (T26), so the builder fixes it in a check round. The
  reviewer is left one question the program cannot answer: whether behaviour, public surface, output and configuration are really
  unchanged.
- **Placement follows the move.** A module that moves takes its test file with it. Two modules that merge have their test files
  merged by moving cases, not by rewriting them.
- **Nothing a consumer sees changes.** The change needs no changelog bullet. Documents that cite a moved path move with the code,
  and the documents' own guards fail if they do not.

## The test standards catalogue

Every standard has an ID, a rule, the reason, and the **check** that holds it: `guard` (an automated test fails), `gate` (checked at
a commit by the red check or the push gate) or `review` (the reviewer's checklist). Most standards have a program as their primary
check and review as a second; a few are judgements only a reviewer can make. A finding reads, for example, `T7 tests/serve/test_x.py:40
fixed port`.

**Kind and placement**

- **T1 Kind.** A test has exactly one kind by the decision procedure above. Check: guard (wide scans, runtime tags, the
  CI-runnability guard); review.
- **T2 Placement.** The test lives in the file named for the module it exercises, at the path that mirrors the module (in the
  toolchain's convention). A case for an existing module joins that file; a new file exists only for a new logic file; one subject
  has one test file. Check: gate (the red check accepts a case by id); guard (a new test file for a subject that has one, mirror
  paths); review.
- **T3 Name.** A test name states one behaviour as a sentence. File names are unique across the tree. Check: guard (no two test
  files share a base name); review.
- **T4 Surface.** A test reaches a public surface and imports no private name. Check: guard; review.
- **T27 Kind folder.** An integration test lives in the project's `integration` folder and an e2e test in its `e2e` folder, and a
  unit test in neither; the folder and the test's selector agree. Check: guard (each test file's folder against its selectors);
  review.

**Determinism: the same result every time, in any order, under load**

- **T5 No wall-clock assertion.** No assertion on elapsed time; state speed as work done (a counted call, a bounded join or wait).
  Check: guard (a clock difference in an assertion); review.
- **T6 No sleep and no unbounded wait.** Wait on an event or a condition with a deadline. Check: guard.
- **T7 No fixed port and no unjoined thread.** Ephemeral ports; every thread joined or signalled. Check: guard.
- **T8 Per-test identity.** Session ids, paths and names come from fixtures, never constants shared between files. Check: guard
  (no id is defined in two files); review for paths and names.
- **T8a Isolation lives in shared fixtures, not in each test.** Temporary directories, an ephemeral port, a fake clock and an
  environment and working-directory guard come from one shared fixture set, applied to every test automatically where it fits, so a
  test adds one fixture argument and nothing else. A rule that covers every test is one guard over the tree, never a repeated check
  or repeated setup in each test. The same setup block (the same environment-patching sequence, the same temporary-tree builder, the
  same fake server) in several test files is a missing fixture or helper, and reusability is not given up to get isolation. Check:
  guard (helpers defined once, repeated setup across files); review.
- **T9 Order and worker independence.** A test passes alone, in any order and under any worker count. Check: gate (the repeat
  check); guard (a randomised-order run of a sample in CI).
- **T10 Injected clock and randomness.** A test that depends on time or randomness uses a stand-in. Code that orders by time is
  tested with a clock that stands still and one that steps back. Check: review.
- **T11 No network but loopback for a unit test, and no real agent.** An integration test adds only the package hosts its CI job
  provides. Check: guard.
- **T12 Reads only tracked files.** No test reads a path the repository ignores. Check: guard.
- **T12a Domain.** A test touches only its own domain. A project's domain is its folder; the root's shared files (CI templates, the
  root hook configuration, the workspace manifest) are a shared domain a project's test may read and never edit; a project's test
  never names a sibling project's path. Cross-project checks are root-level workspace conformance tests. Check: guard (one
  root-level test over the workspace manifest); review.
- **T13 Changing external values are read through one helper.** A value that drifts (process-table output, a file being written,
  `git`) is read until two reads agree, or rounded. Check: review.
- **T14 The environment is set, not assumed.** A test sets what it reads. Check: guard (shared fixtures clear the variables the
  suite reads); review.
- **T15 Strict warnings stay on.** A coroutine never awaited and an unraisable exception are errors, so a missing `await` fails the
  test that has it. Check: guard.

**Cost: cheap enough to run under load**

- **T16 Time budget.** A unit test fits its budget; one that needs more is a wide scan or is split. Check: guard (the time limit).
- **T17 Wide scans are integration, and scan once.** A whole-repository walk is an integration test and shares one session-scoped
  result, not one scan per test. A scan that runs at import time, while the runner collects, makes selecting its tests useless and
  must be lazy. Check: guard (every scan carries the selector; repeated scans).
- **T18 A child test run's code is a file**, not a string, where a toolchain starts child runs. Check: guard.

**Design: a test says something, once**

- **T19 One behaviour**, arranged, acted, asserted. Check: review.
- **T20 Assertions bite.** A test fails when the behaviour it names is removed. A test that passes with the guard it tests deleted
  is vacuous. Check: gate (the red check proves the new test fails for the right reason); review asks what change to the code fails
  it.
- **T21 Parametrise, do not copy; helpers are defined once.** Check: guard.
- **T22 No test of a test.** Check: review.
- **T23 Fakes satisfy the seam.** A swappable seam is typed against a Protocol; a fake is a plain class, not a mock of an internal.
  Check: review.
- **T24 Generated data is current.** Goldens and schemas are regenerated by the change that alters their generator, and a check
  fails if the committed copy is stale. Check: guard.
- **T25 A missing environment is a skip or a configuration error**, never a failure. Check: review.

**Reorganizing code**

- **T26 A reorganization changes tests only mechanically.** Names and locations change; assertions, expected values, the count of
  tests, skips, markers and limits do not. Check: gate (a before-and-after comparison of the changed test files); review asks
  whether behaviour changed.

**New tests and existing tests**

- A **new test** is held to the whole catalogue before it merges: T2 and T20 at the tests commit, the guards at the unit gate, the
  rest by the reviewer.
- An **existing test** is held to it by a *ratchet*. Every guard that does not yet pass over the whole tree starts with a baseline: a
  list of the violations present when the guard is added, which may only shrink. Nothing regresses, and old violations are removed
  one at a time. A unit that edits a test file leaves that file conformant for the standards its guards cover, in the files it
  touches and no others. A periodic audit reports counts per standard and area.
- A standard is added by a change that adds its guard and its baseline together, so the rule and the list never drift.

## How standing guidance reaches an agent

Five channels. A role gets the ones that fit how often the guidance applies, how large it is, and which runtime the step runs on.

1. **Prompt splice: always-on and compact.** Rules that apply to every run of a role and fit in a few kilobytes: the reviewer's
   checklist, the builder's table of standard IDs, the planner's group modes. A rule is said once, at the start of a session;
   continuation prompts do not repeat it. Prompt size is a cost.
2. **File read on demand: the full text.** Long reference the agent consults when a case needs it, written into the run's scratch
   folder and named in the prompt. A step can read its scratch folder under the sandbox policy on every runtime. The compact table
   must stand on its own for the rules that matter most, in case an agent does not open the file.
3. **Repository-owned guidance.** A project's own standards live in the project's agent-guidance files and in files those import.
   Every agent in its worktree reads them by normal discovery. The kit's catalogue is the universal part; a project adds its own
   standards in its own files.
4. **Skill: people and interactive sessions only.** Skills serve a person or an interactive session. The unattended pipeline does
   not use skills: its steps cannot rely on loading one. A skill generated from the catalogue is an addition for people writing
   tests by hand and never a dependency of the build.
5. **A deterministic check.** Anything a program can decide is checked before review; the guidance then only says what the check
   refuses.

By role: the planner gets channel 1; the tests and implementation agents get 1, 2, 3 and 5; the checks agent gets the failing
standard's ID (1) and 5; the reviewer gets 1 (its checklist) and the result of 5; the rework agent 1 and 2; the regression agent 1
and 2, and it cites IDs in the fix change; tracks and chat sessions 2 and 4; the restack resolver 1 only.

**Guidance follows the group mode.** The prompts of the tests node and the review node are built from the unit's group modes, and
each says only what applies to the groups in front of it. A rule that cannot apply is left out, so an agent is not told to write a
failing test for a group that has no tests, or to check implementation standards on a lone tests commit.

| Mode | The tests node is told | The review node is told |
|---|---|---|
| `tests_and_code` | the whole catalogue; the tests are committed first and must fail | the full `review`-class checklist |
| `tests_only` | the catalogue; there is no implementation, so each test must pass | the checklist for tests alone, with no implementation questions |
| `no_code` | nothing: the node does not run | documents and configuration only, with no test standards |
| `refactor` | nothing: the node does not run | T26, and whether behaviour, public surface, output and configuration are unchanged; no new-test standards |

A unit can carry groups of different modes, so a prompt is built per group where the node works one group at a time, and from the
set of modes where the review sees the whole unit; the checklist then names the group each rule is for. The deterministic standards
check and the red check key off the same mode, so the program and the prompt never disagree about what a group is held to.

**One source.** The catalogue is a machine-readable file, one record per standard: ID, rule, reason, check class, the guard or check
that enforces it, and whether it applies to new tests, existing tests or both. The reference page, the builder's table, the
full-text file and the reviewer's checklist are all generated from it, and a test fails when a rendering is stale.

**Measuring the full-text file.** How well agents use the full text is measured, not assumed: whether they open it, whether the
rules they violate are the ones only the file holds, whether they cite the IDs, and whether a build with the file does better than
one with the compact table alone. A rule that is violated only when the file is skipped moves into the compact table.

**Deterministic first, review second.** A *standards check* runs in the checks round, after the unit's tests and before the review.
It runs the guards for the `guard` and `gate` standards, scoped to the files and tests the unit added or changed, so it is cheap, and
it prints each violation by ID. A violation costs the builder a round, with the output as feedback like a lint or type failure, and
not a review round. The reviewer receives the result and never re-derives it; a finding on a `guard` standard is not accepted from a
reviewer, because the guard owns it. The reviewer's checklist holds the judgements a guard cannot make: that an assertion bites
(T20), that a test is about one behaviour (T19), that the kind is right (T1), that a clock is injected (T10), that a drifting value
is read through a helper (T13).

## Load tolerance

A loaded machine turns a correct test into a failing one when the test's budget counts elapsed time and the test is starved of CPU.
Three rules.

- **The per-test limit counts CPU time, with a wall-clock backstop.** The budget is the CPU the test's own process and its child
  processes use (a test that starts a child test run does its work in the child). A longer wall-clock backstop, a multiple of the
  budget, still ends a test that blocks or sleeps and so uses no CPU. The failure message names which clock fired, so a load failure
  is recognisable. A test starved of CPU but under its budget passes.
- **Gates share the machine.** A worker budget, the machine's CPU count by default, admits a unit's test run only when the workers
  it asks for fit, so several gates and many running units do not multiply their workers. A per-repository cap still bounds one
  run. The budget counts the runs the pipeline starts. A run a person starts by hand is not monitored and is not counted.
- **Tests are designed for a loaded machine.** The cap lowers how often a heavy load happens. It does not excuse a test that passes
  only on a quiet machine. Standards T5, T6 and T17 are what make a test load-tolerant.

## Classifying a failing test

A failing test is classified by cause, by a program, before a fix change is written. Each outcome produces something different.

| Outcome | How it is told | Produces |
|---|---|---|
| **Own failure** | fails when run alone, serially, and the unit wrote or changed the test or the code under it | the builder fixes it; the checks round |
| **Failed on base** | the unit did not write the test, and it fails alone on the unit's own base in a clean worktree | a fix change for the test, and the unit waits for it |
| **Flake** | fails in the run, passes alone on every rerun, and the host was not under load | a fix change that makes the test deterministic |
| **Load** | the failure is a limit or backstop hit, the host's recorded load was high, and the test passes alone | recorded; no fix change; listed where failures are reported |
| **Isolation** | passes alone, fails with others, and the cause is a shared resource | a fix change for the test or the shared fixture, citing the standard |
| **Storm** | more tests failed in one run than a configured count and all pass alone | one record for the run; no fix change |
| **Consequence** | an error that follows the first time-limit hit in the same worker (a worker's later tests error because the first was interrupted) | marked as a consequence, not counted as a new failure |

**Order of decisions.** An open fix already covers every failing test: wait for it. Otherwise rerun the failed ids alone and
serially, twice. If a rerun fails and the unit did not write the test, run it on the base. If the reruns pass, look at the load
recorded with the failure and at the count of failures, and decide among flake, load, storm and isolation. A deterministic
stale-data failure is never a flake; it fails every run alone, and re-running never helps it.

**Evidence.** Every failing run keeps a bundle: the output, the machine's load and memory when it ran, the worktree's state, the
command's facts. Each rerun keeps its own, and a ledger records every unit-test run, with the host's CPU count, whether it was
loaded, and the worker and limit-hit state of each failure, so "only under load" can be answered from the record and not from
memory.

**The regression agent decides and writes.** An agent works out why a test fails and writes the fix as a spec. A test-code cause
gets groups that name only test files and carry no test of their own; a source cause keeps a test that recreates the defect
deterministically (an injected clock or ordering, named in the task). The change names its test in the form the reproduction check
reads, cites the standard's ID, and lists the other tests that share the pattern, so a per-test cure becomes a pattern cure. A fix
unit checks first that its test still fails; a test that no longer fails satisfies the unit. A fix unit never depends on another
fix change.

## Profile parity

Every toolchain profile implements the same test capabilities: repeating chosen tests, selecting the affected tests, recording the
data a selection reads, reporting the facts of a run, applying the e2e selection, and listing the selectors it registers, and the
serial rerun of a failed id and the reading of failed test ids that classification needs. A profile that lacks one quietly loses
the feature behind it: no repeat check, no flake classification, no affected selection. A missing capability is therefore a defect,
and two tests keep it from being silent.

- **A conformance test over the profile registry**, an integration test like every conformance test. Each registered profile must
  satisfy every capability the framework branches on. A profile that cannot support one says why explicitly, and the list of those
  may only shrink. A new capability fails the test until every profile implements it.
- **An integration scenario suite.** A tiny fixture project per profile runs the same scenario: red by id, a passing new test
  rejected, repeat by id, a serial rerun of a failed id, failed-test parsing, affected selection after a one-file change. Every
  profile passes the same assertions, and a future profile adds one fixture and inherits the suite. It needs the toolchain and the
  network, so it is an integration test.

**Affected selection without recorded data.** A runner that can name the tests reaching a changed file from its own module graph
may use that instead of recorded data. It is an over-approximation with known gaps, so it speeds the unit's gate and never proves it,
and the full run in CI stays the backstop. A profile reports such a selection together with a conservative fallback: when the
changed paths include shared configuration, a setup file, a lock file or a workspace manifest, it runs the whole member.

## Decisions made

- **The red check is enforced in the build loop**, at the tests commit, and not only at a push gate.
- **A new test joins the existing file for its subject**; a new test file exists only for a new logic file.
- **Integration means runnable in CI.** Anything needing credentials, a live service, a model, an agent or an MCP or API call is e2e.
  Every integration test runs in CI on every pull request; a unit's gate also runs the integration tests it added or changed and
  those whose covered code it changed.
- **An integration test is wider than one file's behaviour and uses no live service.** `[integration-test]` groups carry the
  `integration` selector.
- **Whole-repository scans and conformance tests are integration tests**, and each scan runs once.
- **`integration` is a required check** on every repository that adopts this.
- **No test is serial.** A test that needs it is fixed.
- **The per-test limit counts CPU time with a wall backstop**; a load failure is not a flake.
- **Hand-run gates are outside the worker budget**, which counts only the runs the pipeline starts.
- **Every profile has every test capability**, enforced by a conformance test.
- **Standing guidance is delivered by channel, never by skill, to the unattended pipeline**, and whatever a program can decide is
  decided before review.
- **Guidance follows the group mode.** The tests and review prompts are built from the unit's group modes and leave out what cannot
  apply.
- **A project's tests touch only its own domain**; cross-project checks live at the root.
- **A test lives in the folder of its kind** (`integration`, `e2e`, or the mirrored tree for unit tests), and the folder and
  selector agree.
- **The e2e selector is named `e2e`**, for what the test is and never for how a stack is run.
- **Every conformance test is an integration test.**
- **A tree-wide integration test declares the files it reads**, and the affected selection chooses it when a declared file changes.
  A conformance test or wide scan does not always run in the gate; CI runs it on every pull request and is the backstop for what
  the declaration misses. The declaration lives where the test reads, and the selection reads the same declaration, so the two
  cannot drift. A tree walk with no declaration is refused.
- **The planner declares a reorganization as a group mode**, the way it declares `tests_only` and `no_code`.
- **A reorganization needs no new test.** The existing tests pass with only mechanical edits (T26); a characterization test is added
  only for moved code that has none; anything more is a behaviour change and is built tests first. Renaming and moving functions,
  fixtures and imports is mechanical; changing an assertion or what a function takes, returns or does is not.
- **A selection is never the proof of a pass.** The full suite runs before review, and its recording of dependencies is tested for
  completeness.
- **The full-text standards file is measured**, not assumed to be used.

## Open questions

None.
