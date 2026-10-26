## ADDED Requirements

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
