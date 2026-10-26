# review-loop Specification

## Purpose
Defines how a unit's review loop ends: what a verdict may say besides "approved"
and "not yet", what the reviewer knows about what a further round costs, and what
becomes of a unit whose rounds run out.

## Requirements

### Requirement: The reviewer knows what another round costs

Each review round SHALL tell the reviewer which round this is, how many remain,
and what happens when they run out: the work is neither merged nor kept, and the
next attempt starts from nothing. This SHALL be stated as information for the
judgement the reviewer already makes, not as pressure to approve work it would
otherwise reject.

#### Scenario: The last round

- **WHEN** the final round's review begins
- **THEN** the reviewer has been told it is the final one and what ending it
  without approval costs

### Requirement: A finding may be deferred instead of blocking

A verdict SHALL be able to approve while recording work that should still be
done, and the recorded items SHALL be written where the change's later units and
the person reviewing the pull request will see them, not only in a log. The
following SHALL NOT be deferrable, and the reviewer SHALL be told so: behaviour
that is wrong, a test that would pass whether or not the code is correct, a test
the task asked for and does not exist, and anything the command policy or the
push gate forbids.

#### Scenario: One optional observation left

- **WHEN** the only outstanding point is worth recording but not worth another
  round
- **THEN** the unit is approved and the point is recorded against the change

#### Scenario: Something that may not wait

- **WHEN** the outstanding point is a correctness problem or a test that does not
  test what it claims
- **THEN** it blocks approval and is not recordable as a follow-up

### Requirement: A problem that is a class, not an instance, goes to a person

When a round finds another instance of a kind an earlier round already raised,
and the kind is open-ended rather than a list that can be completed, the reviewer
SHALL say so and the unit SHALL be held for a person with that reasoning on its
record, rather than another round being spent on the next instance.

#### Scenario: An unbounded list

- **WHEN** successive rounds each find a further way to reach the same forbidden
  effect, and no list of them can be complete
- **THEN** the unit is held, and its record says the approach needs changing
  rather than naming only the latest instance

### Requirement: A repeated disagreement goes to a person

When the builder has declined a point with a reason and the reviewer judges that
the reason does not hold, the unit SHALL be held for a person rather than a third
exchange being spent on that point.

#### Scenario: The builder declines twice

- **WHEN** a point is raised again after the builder declined it with a stated
  reason
- **THEN** the unit is held with both positions on its record

### Requirement: Spent rounds leave work in a person's hands

When the rounds run out with blocking work outstanding, the pipeline SHALL push
the branch, make its outstanding points visible on its pull request, and hold the
unit for a person — never discard the work or leave it only in a local worktree.
Nothing SHALL be merged: only a commit review approved may merge, as before.

#### Scenario: The budget is spent

- **WHEN** the last round ends without approval and with blocking points
- **THEN** the branch is pushed, the open points appear on its pull request, and
  the unit is held rather than failed

#### Scenario: What holding does not permit

- **WHEN** a unit is held this way
- **THEN** no commit is merged and nothing is marked approved

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

### Requirement: A review after a person's comments sees those comments and the replies

When a rework was requested by a person's comments on the pull request, the
review that judges it SHALL be given, by the runner, each comment as the
rework received it and the builder's reply to it, and SHALL be asked whether the
work meets what each comment meant. A comment the review finds unmet SHALL be
reported as a required finding. Comments SHALL be presented as the reviewer's
words and SHALL carry no authority over the review's own verdict. A rework that
did not come from a person's comments SHALL add no such note.

#### Scenario: A rework answers a person's comment

- **GIVEN** a rework triggered by a person's comment, with the builder's reply
  recorded
- **WHEN** the review of that rework runs
- **THEN** its context contains the comment and the reply
- **AND** it is asked to check the work against the comment

#### Scenario: A rework from the pipeline's own review

- **GIVEN** a rework triggered by an earlier review round
- **WHEN** the review of that rework runs
- **THEN** its context carries the earlier rounds as before and no comments note

#### Scenario: A comment tries to instruct the review

- **GIVEN** a person's comment containing text that tells the review to approve
- **WHEN** the note is built
- **THEN** it is quoted as the reviewer's words and the review's verdict is its
  own

### Requirement: The review may read its pull request but never change the host

The review agent SHALL be allowed its repo's code host read commands for the
pull request under review, and no others. Any command that merges, votes,
posts, or reaches the host's raw API SHALL remain refused on every repo.

#### Scenario: A review reads the pull request

- **WHEN** the review runs on a GitHub repo
- **THEN** `gh pr view` and `gh pr diff` are allowed to it, and `az repos pr
  show` is not

#### Scenario: A review tries to comment

- **WHEN** the review agent runs a command that posts to the host
- **THEN** it is refused

### Requirement: Review does not spend a round on what unit-test checks about the changelog

A reviewer SHALL be told that the changelog's form and wording are not findings while
unit-test's changelog check passes. A changelog entry that claims something the code does
not do SHALL still be a finding.

#### Scenario: A passing check, awkward wording

- **GIVEN** an entry that passes the changelog check but is phrased awkwardly
- **WHEN** the unit is reviewed
- **THEN** the wording is not raised

#### Scenario: A false claim

- **GIVEN** an entry that describes behaviour the change does not implement
- **WHEN** the unit is reviewed
- **THEN** it is raised as a finding
