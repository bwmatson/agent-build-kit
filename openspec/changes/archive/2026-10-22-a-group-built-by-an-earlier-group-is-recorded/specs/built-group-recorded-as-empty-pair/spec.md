## ADDED Requirements

### Requirement: A group already built is recorded with an empty, marked pair

In a stubbed build (`builders.per_group_commits` on, the repo's profile supporting stubs), when the tests and implementation steps of a group leave nothing
to commit (the head has not moved since the group began and the commit step staged nothing), the branch holds neither commit of the group and holds at
least one commit of its own, the build SHALL check the tree and, when the check passes, record the group with two commits made with `git commit --allow-empty`:
`test: <group title>` and then `feat: <group title>`. Each SHALL carry the group's usual body, the trailer `Unit: <unit id>` and the trailer
`Already-built: yes`, with the trailers last. The body of the `feat:` commit SHALL also hold the implementation agent's last message, redacted of secrets
and cut to 2,000 characters, as the reason. Position and title matching, resume, restack and the push gate SHALL treat the pair as any other group's.

#### Scenario: Group 4 already built after group 3's pair

- **GIVEN** a stubbed unit of groups 3 and 4 whose group 3 made a real `test:` and `feat:` pair and whose group 4 agents commit nothing, with the unit tests passing
- **WHEN** group 4 is built
- **THEN** the branch ends with `test: <group 4 title>` and `feat: <group 4 title>` holding no file, each with `Unit:` and `Already-built: yes`, the `feat:` body holds the agent's account, the pair count passes and the unit goes on to checks and review

#### Scenario: A group that committed is unchanged

- **GIVEN** a stubbed unit whose every group's agents commit their pair
- **WHEN** it is built
- **THEN** no commit carries `Already-built` and no whole-repository test run is made for a group

#### Scenario: The unit has no commit yet

- **GIVEN** a stubbed unit whose branch holds no commit of its own after a group whose agents commit nothing
- **WHEN** the group ends
- **THEN** nothing is recorded; the existing rule applies, and if no later group commits either, the unit ends `satisfied`

#### Scenario: The account is the reason

- **GIVEN** a group recorded as built whose implementation agent said "Nothing needed changing. The four tests already pass"
- **WHEN** the commit list is read
- **THEN** the `feat:` commit's body holds that sentence and a reader finds `Already-built: yes` in its trailers

#### Scenario: A test-only group already built

- **GIVEN** a stubbed unit with commits whose `[e2e-test]` group's tests agent commits nothing and whose tests pass
- **WHEN** the group is built
- **THEN** one empty `test:` commit with the marker is recorded, no `feat:` commit is, and the group counts as done

### Requirement: The group's tests are checked before the pair is recorded

The build SHALL record an already-built group only when the whole-repository unit tests pass on the tree. When they do not pass, it SHALL record nothing, save
the output as feedback with the source `unit-test` and stop the unit with "the branch holds no tests and implementation pair for group <n> (<title>)". A
broken environment SHALL block the unit as the unit-test step does and SHALL NOT stop it with that message. A group whose `test:` commit holds files and
whose `feat:` commit is absent SHALL NOT be recorded.

#### Scenario: The tests fail on the tree

- **GIVEN** a stubbed unit with commits whose group 4 agents commit nothing and whose group 4 tests fail
- **WHEN** group 4 is built
- **THEN** no empty commit is made, the unit stops with the pair message for group 4, and the failing output is saved as `unit-test` feedback

#### Scenario: Stubs and tests with no implementation

- **GIVEN** a group whose tests agent wrote stub and test files that were committed and whose implementation agent commits nothing
- **WHEN** the pairs are counted
- **THEN** the unit stops with the pair message, as before, and nothing is recorded

### Requirement: A killed run resumes between the two empty commits

When the tip of the branch is a marked empty `test:` commit with the title of the group the branch says is next, a resumed stubbed build SHALL run that
group's implementation step as for any part-built group and, after the same check passes, record only its empty `feat:` commit.

#### Scenario: Killed between the empty commits

- **GIVEN** a stubbed unit killed after the empty `test:` of group 4 and before its `feat:`
- **WHEN** it is resumed
- **THEN** it resumes at the implementation step of group 4, records the empty `feat:` and goes on, with one pair for group 4 on the branch

### Requirement: The push gate and a restack accept a recorded group

The push gate SHALL accept a branch holding a recorded group: the empty commits are neither tests nor code to the commit-order check, the empty `test:` is not
lint-checked or run red, and the unit's groups are read from the `Unit:` trailer of the empty `feat:` tip. A restack onto a moved base SHALL keep the empty
pair with its subjects and trailers. In the squash merge the empty commits SHALL NOT reach the main branch.

#### Scenario: The gate accepts the empty pair

- **GIVEN** a branch of a real `test:` and `feat:` pair followed by an empty marked pair, over a temporary repository
- **WHEN** the push gate checks it
- **THEN** it reports no problem and makes no clean or red run for the empty `test:` commit

#### Scenario: A restack keeps the pair

- **GIVEN** the same branch and a base that has moved
- **WHEN** the branch is moved onto the new base
- **THEN** all four commits are on the branch with their subjects and trailers, and the pair count still finds every group

#### Scenario: A branch of only empty commits

- **GIVEN** a branch whose commits are all empty
- **WHEN** the push gate checks it
- **THEN** it reports "the branch changes no tests and no code"

### Requirement: Every group built keeps the zero-commit route and the old build

A stubbed unit whose every group is already built and whose branch holds no commit SHALL end `satisfied` by the existing route, with no commit made. A build with the
setting off SHALL be unchanged.

#### Scenario: Every group already built

- **GIVEN** a stubbed unit of three groups whose agents commit nothing for any group
- **WHEN** it is built
- **THEN** it ends `satisfied` with no commit and no empty pair

#### Scenario: The setting off

- **GIVEN** `builders.per_group_commits` off and a unit whose implementation agent commits nothing after a real tests commit
- **WHEN** it is built
- **THEN** the build is as before this change and no commit carries `Already-built`
