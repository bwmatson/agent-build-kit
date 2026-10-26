# ui-review Specification

## Purpose
TBD - created by archiving change ui-review. Update Purpose after archive.

## Requirements

### Requirement: A unit's diff can be reviewed in the web UI

The UI SHALL show the diff of a unit's branch against its base, pinned to one commit, with a file
tree, and SHALL let a reviewer comment on a line or a range, reply in threads, resolve a thread, write
a summary, and choose Request changes or Approve.

#### Scenario: A stacked unit

- **GIVEN** a unit stacked on an open dependency
- **WHEN** its review tab is opened
- **THEN** the diff is against the dependency's branch and shows only the unit's own work

#### Scenario: The branch moves

- **GIVEN** a thread anchored to a commit
- **WHEN** the branch is pushed again
- **THEN** the thread is shown as outdated, at its line where the lines still match

#### Scenario: A large diff

- **GIVEN** a diff of 200 files
- **WHEN** it is opened
- **THEN** files are rendered as they scroll into view and the page stays responsive

### Requirement: A review comment reaches the unit as any review comment does

A comment, a reply or a Request changes made in the UI SHALL be delivered to the unit as feedback
from a person on the same path as a comment from the code host, once, and Approve SHALL record the
approval without merging anything.

#### Scenario: A line comment

- **WHEN** a reviewer comments on a line and chooses Request changes
- **THEN** the unit is sent back for rework with the comment as its feedback, from a person

#### Scenario: Seen once

- **GIVEN** a comment already delivered
- **WHEN** the next poll runs
- **THEN** it is not delivered again

#### Scenario: Approve

- **WHEN** a reviewer chooses Approve
- **THEN** the approval is recorded, nothing is merged, and the unit is not sent back

### Requirement: The agent is shown the code a comment is on

A review note on a line SHALL carry the diff hunk containing the line, from any source, and the
rework prompt SHALL print it beside the comment.

#### Scenario: An inline comment

- **GIVEN** a review comment on a line in the diff
- **WHEN** the rework prompt is built
- **THEN** it contains the hunk with the comment's line marked

#### Scenario: The line is gone

- **GIVEN** a comment on a line the diff no longer contains
- **WHEN** the prompt is built
- **THEN** it is handled as a stale comment as before, without a hunk

### Requirement: Lines can be highlighted for focus without commenting

A reviewer SHALL be able to select lines in the diff and have them highlighted without creating a
comment, and the highlight SHALL be removable. The same highlight SHALL be applied from outside the
diff by a link, by a finding in the reviewer's verdict, or by a thread being hovered.

#### Scenario: Selecting lines

- **WHEN** a reviewer selects a range of lines
- **THEN** the range is highlighted and no thread is created

#### Scenario: A finding

- **GIVEN** a finding in the reviewer's verdict with a file and line
- **WHEN** it is chosen
- **THEN** the diff scrolls to that line and highlights it

### Requirement: A line or range has an address

The review tab SHALL accept an address that names a unit, a file and a line or range, such as
`/units/<change>/<n>/review?file=<path>&lines=12-20`, SHALL open scrolled to it with it highlighted, and
SHALL update the address as the selection changes. Other pages, the logs tab and the agent's replies
SHALL be able to link to it.

#### Scenario: Opening an address

- **WHEN** the address of a range is opened
- **THEN** the review tab shows that file scrolled to the range with it highlighted

#### Scenario: A moved branch

- **GIVEN** an address that names a line of an earlier commit
- **WHEN** the branch has moved
- **THEN** the tab opens at the nearest matching line, or at the file with a note that the line is gone

### Requirement: Uncommitted changes are shown apart from the commit

When a unit's worktree has uncommitted changes from a chat, the review tab SHALL show them as a
separate section from the branch's diff, SHALL mark them as not yet committed, and SHALL NOT accept a
thread on them, since a thread anchors to a commit.

#### Scenario: Changes made in a chat

- **GIVEN** a unit with uncommitted changes
- **WHEN** its review tab is opened
- **THEN** the working changes appear as their own section, marked uncommitted

#### Scenario: Commenting on them

- **WHEN** a reviewer tries to comment on an uncommitted line
- **THEN** it is refused with the reason, and the lines can still be highlighted

### Requirement: A selection can be sent to the unit's agent

A selection in the diff SHALL offer to ask the unit's agent about it, which SHALL attach the file, the
lines, the hunk and the text to the next turn in the unit's agent tab.

#### Scenario: Asking about a selection

- **WHEN** a reviewer selects lines and chooses to ask the agent
- **THEN** the agent tab opens with one attachment chip for the selection ready to send
