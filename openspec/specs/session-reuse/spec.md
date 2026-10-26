# session-reuse Specification

## Purpose
TBD - created by archiving change session-reuse. Update Purpose after archive.

## Requirements

### Requirement: Every agent node records its session under a role

When an agent node completes, the pipeline SHALL record the session it ran in, with the
runtime that owns the id, the model the session started with, the round and the branch head,
under the node's role in the unit's state. The roles SHALL be `build`, for `tests`,
`implement`, `fix_checks`, `rework`, `adapt` and `restack`, and `review`, for `review`. A role's record
SHALL NOT be overwritten by a node of another role, and SHALL be kept after the node
completes. A unit's state saved before this requirement SHALL load with no recorded sessions.

#### Scenario: Two roles in one unit

- **GIVEN** a unit whose `implement` ran in one session and whose `review` ran in another
- **WHEN** both nodes have completed
- **THEN** the state holds both sessions, each under its own role

#### Scenario: A later node of the same role

- **GIVEN** a recorded `build` session from `implement`
- **WHEN** `fix_checks` completes
- **THEN** the `build` record names `fix_checks` as the last node to speak in it

#### Scenario: A unit saved before this change

- **GIVEN** a unit state with no recorded sessions
- **WHEN** it is loaded and a node runs
- **THEN** the node starts a new session and records it

#### Scenario: A conflict resolved in the build session

- **GIVEN** a unit with a recorded `build` session and reuse on
- **WHEN** a restack conflict is resolved by the restack step
- **THEN** the step continues that session, and the `build` record names `restack` as the last node to speak in it

#### Scenario: A unit whose first agent call is the restack

- **GIVEN** a unit resumed with no recorded `build` session
- **WHEN** a restack conflict is resolved by the restack step
- **THEN** the step starts the build session on the rework model, and the next build node continues it

### Requirement: Session reuse is a per-role setting, and the judge is never reused

The workspace SHALL set `session_reuse` per role, on for `build` and off for `review` by
default; a role not named SHALL be off. When a role's reuse is on, each of its nodes SHALL
continue the role's latest recorded session; when off, each node SHALL start its own. A
configuration that turns reuse on for `review` SHALL be rejected. The `review` role's
session SHALL never be resumed by a later review round or by a node of another role.

#### Scenario: Reuse on for build

- **GIVEN** `build` reuse on and a recorded build session
- **WHEN** `fix_checks` runs
- **THEN** it continues that session

#### Scenario: Reuse switched off

- **GIVEN** `build` reuse off
- **WHEN** `fix_checks` runs
- **THEN** it starts a new session, as before this change

#### Scenario: Review is configured to reuse

- **WHEN** the workspace sets reuse on for `review`
- **THEN** the configuration is rejected with a message naming the setting

#### Scenario: A second review round

- **GIVEN** a unit whose first review round ran in a session
- **WHEN** the second round runs
- **THEN** it starts a new session, and the first round's session is still recorded

### Requirement: One step chooses the session, the prompt and the model together

Before an agent node runs, the pipeline SHALL choose, in this order: the node's own
interrupted session, resumed as today; else the role's recorded session when reuse is on
and the session is usable; else a new session. A usable session is one recorded by the
runtime that will run the node, where that runtime can resume. A resumed session SHALL be
given the node's continuation prompt, which carries only what is new and not the change
path, task groups or boundary notes the session already holds; a new session SHALL be given
the node's full prompt. A resume that fails because the session cannot be continued, or
because its context overflowed, SHALL fall back to a new session with the full prompt in the
same call, and the record SHALL show the call was not resumed and why.

#### Scenario: fix_checks continues the build session

- **GIVEN** reuse on and a recorded build session
- **WHEN** the checks fail and `fix_checks` runs
- **THEN** the agent is resumed in that session with a prompt carrying the failure output
  and the instruction to run the checks, and without the change path or task groups

#### Scenario: The session is gone

- **GIVEN** a recorded session the runtime reports it cannot continue
- **WHEN** a node runs
- **THEN** it runs in a new session with its full prompt

#### Scenario: An interrupted node

- **GIVEN** a node killed mid-run whose own session id is held
- **WHEN** the unit is resumed
- **THEN** that session is continued with the interruption prompt, as before

#### Scenario: A runtime that cannot resume

- **GIVEN** a recorded session and a runtime that cannot resume
- **WHEN** a node runs
- **THEN** it starts a new session with its full prompt and no error

### Requirement: A node's first call in a unit starts the build session

`tests` SHALL start the build session when the unit has none, and the next build node SHALL
continue it. A unit that enters past `tests` (a restack, waiting feedback, a resume) SHALL
start the build session at whichever build node runs first.

#### Scenario: A new unit

- **WHEN** `tests` and then `implement` run, with reuse on
- **THEN** `implement` continues the session `tests` ran in

#### Scenario: A unit entering at adapt

- **GIVEN** a unit with no recorded build session
- **WHEN** `adapt` runs
- **THEN** it starts the build session

### Requirement: fix_checks runs on the model the build session started on

`fix_checks` SHALL run on the model the unit's build session started on, whether or not
reuse is on, and not on the rework model. That model SHALL be recorded once, by the first
build node to run, and not changed by a later node; where none is recorded, the configured
implement model SHALL be used. A resumed session SHALL run on the model it started with. Where
a runtime cannot run a resumed session on that model, the node SHALL start a new session with
the full prompt on it.

#### Scenario: Reuse on

- **GIVEN** a build session started on the implement model
- **WHEN** `fix_checks` continues it
- **THEN** the call runs on that model

#### Scenario: Reuse off

- **GIVEN** reuse off and a build session started on the implement model
- **WHEN** `fix_checks` runs
- **THEN** it starts a new session on the implement model, not the rework model

#### Scenario: No recorded model

- **GIVEN** a unit that entered the graph past the build nodes, with no recorded model
- **WHEN** `fix_checks` runs
- **THEN** it runs on the configured implement model

### Requirement: A moved branch is reported as two hashes

When a session is resumed and the worktree's head differs from the head recorded with the
session, the continuation prompt SHALL begin with a note giving the recorded head and the
current head and telling the agent to read what changed; it SHALL NOT include the log or the
diff. When the heads are equal, no note SHALL be added. A session whose recorded head can no
longer be read SHALL NOT be resumed.

#### Scenario: The agent's own commits

- **GIVEN** a session whose last node committed
- **WHEN** a later node resumes it
- **THEN** the prompt names the two heads and carries no log

#### Scenario: A rewritten branch

- **GIVEN** a unit reset onto a new base with its old work kept under a ref
- **WHEN** `adapt` resumes the build session
- **THEN** the prompt names the two heads and the ref that holds the old work

#### Scenario: Nothing moved

- **WHEN** the recorded and current heads are equal
- **THEN** the prompt has no note

#### Scenario: The recorded head is gone

- **GIVEN** a recorded head that is not reachable
- **WHEN** a node runs
- **THEN** it starts a new session with its full prompt

### Requirement: Continuation prompts keep what a node's contract needs

A continuation prompt SHALL keep anything the pipeline parses from the node's answer or
requires of it, such as `adapt`'s per-test decisions, and SHALL drop only context the
session already holds. `rework`'s continuation prompt SHALL carry the review or comment
feedback it addresses.

#### Scenario: adapt resumed

- **WHEN** `adapt` continues the build session
- **THEN** its prompt names the predecessor, the conflict, the ref holding the old work and
  the answer format for test decisions, and omits the change path and task groups

#### Scenario: rework after review

- **GIVEN** review findings asking for changes
- **WHEN** `rework` continues the build session
- **THEN** the findings are in its prompt
