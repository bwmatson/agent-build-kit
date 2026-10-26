## ADDED Requirements

### Requirement: A turn on the unit's session may change the worktree and nothing is committed until the user says so

A turn on a unit's own session SHALL be able to edit files in the unit's worktree and SHALL NOT be able
to commit or push. The branch head SHALL NOT move because of a turn, and changes SHALL stay in the working
tree until the user commits or discards them.

#### Scenario: The agent edits a file

- **WHEN** a turn on a unit's session changes a file
- **THEN** the file changes in the worktree, the unit shows uncommitted changes in one file, and the
  branch head is where it was

#### Scenario: The agent tries to commit

- **WHEN** such a turn's agent runs `git commit` or `git push`
- **THEN** the command is refused and nothing is committed or pushed

### Requirement: The lease tells the tick whose changes a dirty worktree holds

The lease a chat takes on a unit SHALL carry the checkouts it covers, whether they hold uncommitted changes, and a marker for a commit
made and not delivered, and SHALL be what the tick reads to tell a chat's changes from a failure's leftovers. A lease whose process has
gone and which holds no changes and no marker SHALL hold nothing, as now. For a dirty worktree the tick SHALL leave a unit with a lease
held by a live process alone, SHALL park a unit whose lease is stale and marked as holding changes without committing or continuing
them, SHALL finish the delivery of a commit marked as made and not delivered, SHALL resume over the leftovers of a killed node that
has no lease, and SHALL park any other dirty tree. Closing the page SHALL NOT release a lease marked as holding changes.

#### Scenario: A live lease

- **GIVEN** a unit whose worktree has uncommitted changes from a chat whose server is running
- **WHEN** the tick runs
- **THEN** it neither starts the unit nor fails it, and the status command lists the unit as attached
  with the number of changed files

#### Scenario: A lease whose process has gone, with changes

- **GIVEN** a lease marked as holding changes whose server has gone
- **WHEN** the tick runs
- **THEN** it does not commit or continue the changes, the unit is parked with the cause `attached`, and
  the status command says to start the server or run `abk attach release`

#### Scenario: A lease whose process has gone, with nothing held

- **GIVEN** a lease whose server has gone and which is marked as holding no changes and no commit
- **WHEN** the tick runs
- **THEN** the lease holds nothing and the unit is handled as it was before the chat

#### Scenario: A page closes with changes

- **GIVEN** a chat that left uncommitted changes
- **WHEN** its page closes
- **THEN** the lease stays, marked as holding changes

#### Scenario: A killed node's leftovers

- **GIVEN** a dirty worktree with no lease and a recorded node start naming the node being re-run
- **WHEN** the node is re-run
- **THEN** it resumes over the leftovers and its own commit includes them, as it does without the UI

#### Scenario: An unexplained dirty tree

- **GIVEN** a dirty worktree with no lease and no recorded node start
- **WHEN** a node asks for the worktree
- **THEN** the unit is parked as an unexplained dirty tree

#### Scenario: Taking a lease over a killed node's marker

- **GIVEN** a unit whose killed node's start is still recorded, and a chat that has taken its lease
- **WHEN** the user commits
- **THEN** the leftovers are committed with the chat's changes and the recorded start is cleared

### Requirement: A chat attaches only to a unit in a stable state

A chat SHALL attach to a unit only while it is in review, held or failed. A unit paused in the middle of
a node SHALL be shown read-only.

#### Scenario: A unit waiting out a usage window

- **GIVEN** a unit paused in the middle of a node
- **WHEN** its agent tab is opened
- **THEN** the history is shown and the composer is disabled with the reason

### Requirement: A lease can be released without the server

`abk attach release <unit>` SHALL release a lease by committing with `--commit "<message>"` or
discarding with `--discard`, SHALL refuse a dirty worktree without either, and the server SHALL take over
stale leases when it starts.

#### Scenario: Discarding from the command line

- **GIVEN** a stale lease with uncommitted changes
- **WHEN** `abk attach release <unit> --discard` is run
- **THEN** the tree is restored to the branch head and the lease is released

#### Scenario: Neither flag

- **WHEN** `abk attach release <unit>` is run on a dirty tree without a flag
- **THEN** it refuses and says what to choose

### Requirement: A commit lets the unit's agent fix hook failures

Commit SHALL show the changed files and a message, proposed by the agent or typed, and SHALL commit through
the repo's hooks. When the hooks reject the commit, the unit's agent SHALL be given their output, fix it,
and the commit SHALL be tried again, up to the commit helper's bound. When it is still rejected the changes
SHALL stay uncommitted and attached with the output shown.

#### Scenario: A hook that reformats files

- **WHEN** a hook reformats the changed files and fails the first attempt
- **THEN** the commit is tried again and succeeds

#### Scenario: A hook the agent must fix

- **WHEN** a hook rejects the commit for a lint error
- **THEN** the agent is given the output and fixes it, the commit is tried again and succeeds, and the
  progress is shown in the chat

#### Scenario: Still rejected

- **WHEN** the commit is rejected after the last attempt
- **THEN** the changes remain uncommitted and attached, and the hook output is shown

### Requirement: An adopted commit goes through the normal checks and review without using a round

A successful commit SHALL, as part of the same operation, release the lease and deliver the unit to its checks, then the review loop
and the push gate, from a unit in review, held or failed, SHALL clear the recorded node start, and SHALL
carry trailers naming the unit and the session. The previous approval SHALL NOT be reused. The review that
follows SHALL NOT count against the review-round limit and SHALL NOT hold the unit as having spent its
rounds; if it asks for changes the counted rounds SHALL start at one with the rework.

#### Scenario: A unit in review

- **GIVEN** a unit in review and a chat that changed a file
- **WHEN** the user commits
- **THEN** the unit runs unit-test, a review and, once approved, the push

#### Scenario: A spent budget

- **GIVEN** a unit held for having spent its review rounds
- **WHEN** a chat's changes are committed
- **THEN** the unit is reviewed and is not held again for spent rounds

#### Scenario: The review asks for changes

- **WHEN** the review after an adopted commit asks for changes
- **THEN** the following rework is round one of the limit

#### Scenario: A failing check

- **WHEN** the unit's checks fail after the commit
- **THEN** it is sent back for rework as for any failing check

### Requirement: Committing or discarding is one operation that also ends the lease

Committing changes from a chat SHALL be one request that commits, releases the lease, delivers the adopted event and answers with the
commit, the unit's new state and whether the delivery completed, and no second request SHALL be needed to hand the unit back to the
workflow. A commit the hooks reject SHALL keep the lease and the changes. A commit that is made and not delivered SHALL leave the
lease marked committed with its hash, and the next start of the server, `abk attach release` and the tick SHALL finish that
delivery once and remove the lease. Discarding SHALL be one request that restores the worktree and releases the lease, and
`abk attach release` with `--commit` or `--discard` SHALL do the same in one command.

#### Scenario: One request commits and hands the unit back

- **GIVEN** a unit in review with a chat that changed a file
- **WHEN** the user commits in one request
- **THEN** the commit is made, the lease is released, the adopted event is delivered, the answer says the delivery completed, and
  no other request was needed

#### Scenario: The hooks reject the commit

- **WHEN** the hooks still reject the commit after the bounded fix loop
- **THEN** the answer is a conflict with the hook output, the lease is kept and the changes stay uncommitted

#### Scenario: The server stops between the commit and the delivery

- **GIVEN** a commit made and the server stopped before the adopted event was delivered
- **WHEN** the server starts, or `abk attach release` is run, or the tick runs
- **THEN** the adopted event is delivered once for that commit and the record is removed, and the changes are not taken for chat
  changes left behind

#### Scenario: The same request repeated

- **GIVEN** a commit already made and delivered
- **WHEN** the same request is repeated with the same commit
- **THEN** nothing is delivered again and the result is returned

#### Scenario: Discard is one request

- **WHEN** the user discards the changes
- **THEN** the worktree is restored and the lease released in that one request

#### Scenario: The command line

- **WHEN** `abk attach release <unit> --commit "<message>"` is run
- **THEN** it commits, releases and delivers in that one command

#### Scenario: A commit of the planning checkout

- **GIVEN** a chat that changed a change's task file
- **WHEN** the user commits the planning checkout
- **THEN** that part of the lease is released in the same request and no unit is sent anything

### Requirement: Uncommitted changes can be discarded

Discard SHALL list the files, require a confirmation, and in one operation restore the worktree to the branch head and release
the lease; cancelling SHALL change nothing, and a clean worktree SHALL be releasable directly.

#### Scenario: Discarding

- **WHEN** discard is confirmed
- **THEN** the working tree matches the branch head and the lease is released

#### Scenario: Releasing with changes present

- **WHEN** release is chosen while changes exist
- **THEN** it is refused and commit and discard are offered

### Requirement: The unit's own session is told its change and flags a conflict before editing

A chat turn on the unit's own session SHALL carry the unit's proposal, design, spec deltas and task groups as
read-only context and an instruction that tests and code change together. When a request contradicts them the
agent SHALL reply first with a flag naming the requirement or task and SHALL make no edit until the user
confirms, and the UI SHALL show the flag as a highlighted callout with the choices to proceed, to change the
spec instead, or to cancel.

#### Scenario: A request against a requirement

- **GIVEN** a request that contradicts a requirement of the unit's change
- **WHEN** the turn runs
- **THEN** the reply is a flag naming the requirement, no file changes, and the callout offers the three choices

#### Scenario: Proceeding anyway

- **WHEN** the user chooses to proceed
- **THEN** the agent makes the change

#### Scenario: Changing the spec instead

- **WHEN** the user chooses to change the spec
- **THEN** a free session on the planning repo opens with the flag as its first message

### Requirement: A review comment against the spec is answered with the flag

The rework prompt SHALL tell the unit's build session that a review comment which contradicts the unit's
change is to be answered in its thread with the flag and not acted on until the reviewer confirms.

#### Scenario: A conflicting comment

- **GIVEN** a review comment that contradicts a requirement
- **WHEN** the unit is reworked
- **THEN** the agent's reply in the comment's thread names the requirement and the code is not changed for that comment

### Requirement: A free session has no guidance or constraints beyond the manual commit

A session that is not the unit's build session, whether started in the UI or elsewhere and continued here,
SHALL be given no pipeline guidance and no constraint on what it edits, SHALL be able to change code and
specs in the same session, and SHALL NOT have its changes committed until the user commits them.

#### Scenario: Code and a spec in one session

- **WHEN** a free session changes a source file and a change's task file
- **THEN** both stay uncommitted until the user commits, and no guidance is added to its prompts

#### Scenario: Turns run by the server

- **WHEN** a free session's turn runs through the server
- **THEN** `git commit` and `git push` are refused for it

### Requirement: A commit is made per checkout and the planning checkout is gated by the change checks

Commit SHALL be made separately for the unit worktree and for the planning checkout. The unit worktree's
commit SHALL be adopted as above. The planning checkout's commit SHALL be gated by `abk check` and
`abk tags` of the change, with the agent given any failures to fix and the commit tried again, SHALL be
delivered to no unit, and SHALL be followed by a list of its consequences for units that have started.

#### Scenario: A spec commit that fails validation

- **WHEN** `abk check` rejects a spec edit
- **THEN** the agent is given the output, fixes it and the commit is tried again

#### Scenario: A Needs line edit

- **WHEN** the commit only changes a `Needs:` line of a started unit
- **THEN** the consequences list says the gate applies on the next tick

#### Scenario: A plan change

- **WHEN** the commit changes the plan of a change with built units
- **THEN** the list says the change is re-planned on the next tick and built units keep their state

#### Scenario: A spec that no longer matches a branch

- **WHEN** the commit changes a requirement a started unit built to
- **THEN** the unit is flagged for a rework or a requeue and nothing about it is changed automatically

### Requirement: A commit by another session is identified to the unit's build session

A commit made to a unit's branch by a session that is not its build session SHALL carry that session in an
adopted-from trailer, and the unit's next rework, check-fix and review prompts SHALL list the commits made
outside the session with their hash, subject, files and session, as authoritative and not to be reverted. A
commit made by the build session itself, and review comments and other non-chat interactions, SHALL add
nothing.

#### Scenario: A free session commits

- **GIVEN** a free session's commit on a unit's branch
- **WHEN** the unit is next reworked
- **THEN** the prompt lists the commit and says it is authoritative and not to be reverted

#### Scenario: The build session commits

- **GIVEN** a commit adopted from the unit's own session
- **WHEN** the unit is next reworked
- **THEN** the prompt adds no outside-commit part

#### Scenario: A review comment

- **WHEN** a review comment sends the unit back
- **THEN** the build session resolves it with no additional context

#### Scenario: Tests an outside commit changed

- **GIVEN** an outside commit that changed a test
- **WHEN** the agent changes that test
- **THEN** it states whether it keeps, adapts or retires it
