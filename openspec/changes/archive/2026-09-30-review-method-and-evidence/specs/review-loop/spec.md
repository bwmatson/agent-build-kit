# Spec Delta

## Purpose

Defines how a review round looks for problems, what a finding must state, and
the shape in which findings are returned, recorded and shown to the next round.

## ADDED Requirements

### Requirement: The reviewer works named angles in one pass

The review prompt SHALL direct the reviewer to read each changed hunk with its
enclosing function, to account for every behaviour a removed or replaced line
enforced, and to check every caller and callee of a changed function against
the change. The reviewer SHALL re-check each candidate finding against the code
before reporting it. The review SHALL remain a single read-only agent run per
round, with no further agent started by it.

#### Scenario: A change that alters what a return value causes

- **WHEN** a diff leaves a function's return value unchanged but changes what a
  caller does with it
- **THEN** the prompt has directed the reviewer to the callers of the functions
  the diff touches and to what each removed or replaced line enforced

#### Scenario: The reviewer's tools

- **WHEN** a review round runs
- **THEN** the reviewer's tools are read-only and do not include starting
  another agent

### Requirement: A required finding states its consequence

The reviewer SHALL be told that a required finding names its consequence: the
input or state that triggers it and the wrong result, or for a documented
convention the rule broken, or for a test the wrong behaviour it would let
through. A finding for which no consequence can be named SHALL be reported as
optional. A required finding returned without a consequence SHALL still block
approval, and SHALL be marked as such where it is shown and counted in the run
log.

#### Scenario: A preference

- **WHEN** the reviewer would change something and cannot say what goes wrong
  if it is left
- **THEN** it is reported as optional and does not block approval

#### Scenario: A required finding with the consequence left out

- **WHEN** a verdict marks a finding required and gives no consequence
- **THEN** the unit is not approved, the finding is shown marked as having no
  stated consequence, and the log records it

### Requirement: Findings are returned as a list

A verdict SHALL be able to carry its findings as a list in which each finding
has a file, an optional line, a one-sentence summary, a consequence, what done
looks like, and whether it is required. The text given to the builder, stored
on the unit and written to a pull request SHALL be rendered from that list. A
verdict carrying only prose feedback SHALL remain valid and be read as it was
before. A verdict that approves while listing a required finding SHALL be read
as not approved.

#### Scenario: A verdict with findings

- **WHEN** a reviewer returns two required findings and one optional one
- **THEN** the builder is given all three, required first, each with its
  location, consequence and what done looks like

#### Scenario: A verdict in the earlier shape

- **WHEN** a reviewer returns only `approved` and prose `feedback`
- **THEN** the round proceeds exactly as it did before this change

#### Scenario: Approval contradicted by its own findings

- **WHEN** a verdict says approved and lists a required finding
- **THEN** the unit is not approved

### Requirement: Optional findings are ranked and capped

A round SHALL keep at most five optional findings, in the order the reviewer
ranked them, and SHALL record how many were left out. Required findings SHALL
never be left out.

#### Scenario: Eight optional findings

- **WHEN** a verdict lists eight optional findings and one required
- **THEN** the builder is given the required finding and the first five
  optional ones, and the log says three were left out

### Requirement: A later round answers each earlier finding

Each required finding SHALL be given an identifier when its round is recorded.
A later round SHALL be shown every earlier required finding whole, with the
builder's answer, and never a finding cut part-way. Its verdict SHALL say of
each whether it is fixed, still open, or declined for a reason that holds; one
left unanswered SHALL be treated as still open. A round SHALL NOT approve while
an earlier required finding is still open.

#### Scenario: A long earlier round

- **WHEN** an earlier round's findings run longer than the note allows
- **THEN** whole findings are left out, those already reported fixed first, the
  note says how many, and no finding is shown truncated

#### Scenario: An earlier finding not answered

- **WHEN** a later verdict approves without answering an earlier required
  finding
- **THEN** that finding is treated as still open and the unit is not approved

#### Scenario: A round recorded before findings were listed

- **WHEN** an earlier round holds only prose
- **THEN** it is shown to the next reviewer as it was before this change

### Requirement: A later round is told which commit was judged

Each recorded round SHALL keep the commit the reviewer judged. A later round
SHALL be told that commit and that new findings come from the changes since it,
or from earlier code only with a reason they were not visible before.

#### Scenario: The second round

- **WHEN** the second round of a review begins
- **THEN** the reviewer has been given the commit the first round judged
