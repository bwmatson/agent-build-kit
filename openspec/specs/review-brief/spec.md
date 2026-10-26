# review-brief Specification

## Purpose
TBD - created by archiving change reviewers-are-told-where-to-look. Update Purpose after archive.

## Requirements

### Requirement: The reviewer ranks what a person should read first

An approving review reply MAY carry, within its description, a `focus` list: entries ranked most important first, each naming a place
(a file, or a file and a group) and the reason a person should read it. A reason SHALL be one of four kinds: a boundary another system
depends on, a behaviour change, something hard to undo, or thin test coverage; an entry whose reason is none of them SHALL be kept
with its reason as written. At most five entries SHALL be kept, each cut to a fixed length, and blank entries SHALL be dropped.
When the unit's recorded classification carries drivers, the focus list SHALL begin with them in their recorded order, and no place
SHALL be listed twice. A reply with no focus list, or a malformed one, SHALL read as an empty list, and parsing SHALL still never
raise.

#### Scenario: Ranked entries

- **GIVEN** an approving reply whose focus list holds an entry for a changed event payload (a boundary) and one for a renamed helper
  (behaviour change)
- **WHEN** the reply is read
- **THEN** both are kept in that order, each with its place and reason kind

#### Scenario: Drivers lead

- **GIVEN** a unit whose recorded classification names `src/events.py` as a driver and a reply whose focus list names it second
- **WHEN** the focus list is built
- **THEN** `src/events.py` comes first, once, with the reason the reviewer gave

#### Scenario: Too many entries

- **WHEN** a reply lists eight focus entries
- **THEN** the first five are kept

#### Scenario: A malformed list

- **WHEN** the reply's `focus` is not a list
- **THEN** it reads as empty, the reply's other fields read as before, and nothing is raised

### Requirement: The reviewer says what is safe to skip

An approving review reply MAY carry a `skippable` list: mechanical moves, renames, generated or formatting-only changes, each with
the reason it is safe to skip. An entry SHALL be kept only with both a place and a reason. At most five entries SHALL be kept, each
cut to a fixed length. A place SHALL NOT appear in both lists; when it does, the focus list SHALL win and the skippable entry SHALL
be dropped.

#### Scenario: A rename

- **GIVEN** a reply whose skippable list names `src/old_name.py` with the reason "moved with no change to its contents"
- **WHEN** the reply is read
- **THEN** the entry is kept with its place and reason

#### Scenario: An entry with no reason

- **WHEN** a skippable entry names a place and no reason
- **THEN** it is dropped

#### Scenario: A place in both lists

- **GIVEN** a place named in the focus list and in the skippable list
- **WHEN** the lists are built
- **THEN** it appears in the focus list only

### Requirement: The pipeline lists what it already verified

The pipeline SHALL compose a verified list for a unit from its recorded results and not from the reviewer's reply: the red-first run,
the unit-test result, the e2e-test result for a unit of that kind, and the number of review rounds. A result that is not recorded
SHALL be listed as not recorded and SHALL NOT be left out. The list SHALL be the same whatever the reviewer wrote.

#### Scenario: All results recorded

- **GIVEN** a unit with a recorded red run, a passing unit-test result and two review rounds
- **WHEN** the verified list is composed
- **THEN** it says the tests were seen to fail first, that the unit tests passed, and that review took two rounds

#### Scenario: A missing result

- **GIVEN** a unit of the e2e-test kind with no recorded e2e-test result
- **WHEN** the verified list is composed
- **THEN** it lists the e2e-test result as not recorded

#### Scenario: The reviewer claims a result

- **WHEN** a reply says the tests passed and the unit has no recorded unit-test result
- **THEN** the verified list does not say they passed

### Requirement: The pull request body opens with a "Start here" section

When `review.brief` is true, a unit's pull request body SHALL open with a "Start here" section holding the focus list, the skippable
list and the verified list, ahead of "Why". When review is enabled and the unit has a recorded verdict, the body SHALL follow it with
the verdict's review tier and its reason, also ahead of "Why". An empty focus or skippable list SHALL be omitted from the section, and
the verified list SHALL always be present. The section SHALL be a fixed part of the body's size fitting: it SHALL NOT be shrunk or
dropped to fit a host's limit, and no other section SHALL be able to push it out. A unit held for a person SHALL carry the same
section.

#### Scenario: Opened with the brief

- **GIVEN** an approved unit with a focus list, a skippable list and a recorded verdict of `light`
- **WHEN** its pull request body is built
- **THEN** the body begins with the three lists, then the tier `light` with its reason, and "Why" follows

#### Scenario: Review is not enabled

- **GIVEN** `review.enabled` is false
- **WHEN** the body is built
- **THEN** the section holds the lists and no tier line

#### Scenario: The host's limit is tight

- **GIVEN** a unit whose verification output and description are far over the smallest host limit
- **WHEN** the body is built to that limit
- **THEN** the "Start here" section is whole and the other sections shrink

#### Scenario: A unit held for a person

- **GIVEN** a unit whose review rounds ran out with a finding outstanding
- **WHEN** its body is built
- **THEN** it carries the "Start here" section and the "Held for a person" section

#### Scenario: Nothing from the reviewer

- **GIVEN** an approval with no focus or skippable list
- **WHEN** the body is built
- **THEN** the section holds the verified list alone

### Requirement: A setting turns the brief off

The `review` section of abk.yaml SHALL accept `brief`, a boolean defaulting to true. With `brief` false, the pull request body SHALL
be built exactly as it was before this change, the review prompt SHALL NOT ask for the two lists, and no verdict record SHALL be
changed because of the brief.

#### Scenario: Off

- **GIVEN** `review.brief: false`
- **WHEN** a unit's body is built
- **THEN** it has no "Start here" section and is identical to the body built before this change

#### Scenario: The default

- **WHEN** a workspace sets no `brief`
- **THEN** it loads with `brief` true

#### Scenario: A wrong type

- **GIVEN** `review.brief: "sometimes"`
- **WHEN** the configuration is loaded
- **THEN** loading fails naming the key

### Requirement: A verdict record says whether its pull request carried the brief

When a unit's pull request body that carries the "Start here" section is opened or updated, the unit's verdict record SHALL have its
`brief` field set to true. A body without the section SHALL leave it false. Failing to read or write the record SHALL be logged and
SHALL NOT stop or delay the body being written. A later approval of the unit SHALL write the record with `brief` false until the
body is next updated.

#### Scenario: The body carries the section

- **GIVEN** a unit with a verdict record whose `brief` is false
- **WHEN** its pull request body is opened with the section
- **THEN** the record's `brief` is true

#### Scenario: The setting is off

- **GIVEN** `review.brief: false`
- **WHEN** the body is opened
- **THEN** the record's `brief` stays false

#### Scenario: The record cannot be written

- **GIVEN** the state directory refuses the write
- **WHEN** the body is opened
- **THEN** the failure is logged and the pull request is opened as it would have been
