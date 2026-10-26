## ADDED Requirements

### Requirement: A Needs line starts the dependent on the parent's branch

A `Needs: <change> group <n>` line SHALL add a dependency of the unit on the unit that holds that group, and
nothing more. A same-repo dependency SHALL release its dependent once it is through its build and review loop
(in review, merged or satisfied), and the dependent SHALL start on that dependency's branch, as for any
same-repo dependency. A dependency in another repository SHALL release its dependent only once it has merged,
or been satisfied with its work landed, because a stack cannot span repositories. A dependency that is planned,
running, reworked, failed or held SHALL keep its dependent from starting. A `Needs:` line SHALL be applied on
the next tick without re-planning the change.

#### Scenario: A same-repo parent in review

- **WHEN** a unit needs a same-repo unit and that unit is in review
- **THEN** the dependent may start, on the parent's branch

#### Scenario: A parent still building

- **WHEN** a unit needs a same-repo unit that is planned, running, failed or held
- **THEN** the dependent does not start

#### Scenario: A parent that goes back for rework

- **GIVEN** a unit that needs a same-repo unit, and that parent is sent back for rework
- **WHEN** the pass looks for units to start
- **THEN** the dependent is paused as any dependent of that unit is, and returns when the parent is back in review

#### Scenario: A cross-repo parent

- **WHEN** a unit needs a unit in another repository that is in review
- **THEN** the dependent does not start until that unit has merged

#### Scenario: Only a Needs line changed

- **WHEN** an edit changes a `Needs:` line and nothing else in `tasks.md`
- **THEN** no planner call is made and the dependency applies on the next tick

#### Scenario: The word merged is not a qualifier

- **WHEN** a `Needs:` line carries the word `merged` straight after the group number
- **THEN** the line means the same as without it, and `abk tags` and `abk check` warn that the word is deprecated, without failing or stopping planning

#### Scenario: A Needs on the change's own group

- **WHEN** a `Needs:` line carrying the word `merged` names a group of its own change
- **THEN** `abk tags` reports an error: the groups of one change are ordered already

#### Scenario: A stored merge gate from before

- **GIVEN** a stored unit that carries a `merge_before` from an earlier version
- **WHEN** the next tick reads the store
- **THEN** the store loads, the key is dropped, and the unit waits only for what a dependency requires

### Requirement: The graph page marks a Needs dependency

The unit graph page SHALL draw a dependency written as a `Needs:` line with a thick edge labelled `needs`, and a dependency the
planner inferred without a label or the thick style, and the legend SHALL say so, so a reader can tell a stated
dependency from an inferred one.

#### Scenario: A Needs dependency

- **WHEN** a unit has a dependency written as a `Needs:` line
- **THEN** the page draws that edge thick and labelled `needs`

#### Scenario: An inferred dependency

- **WHEN** a unit depends on another through the planner's own dependency
- **THEN** the page draws that edge without the label or the thick style

#### Scenario: The line is removed

- **WHEN** a `Needs:` line is removed and the dependency is not otherwise asked for
- **THEN** the edge is gone at the next tick

### Requirement: A Needs line added to a started unit waits for the parent to be reviewed

A `Needs:` line added to a task group after its unit has started SHALL apply on the next tick without
re-planning the change, and SHALL be an ordinary dependency. A unit that is `failed` or `held` while a
dependency is unmet SHALL NOT be resumed by `abk requeue`: it SHALL become `planned` with the cause `gated`,
keep its thread, branch and saved feedback, remember the mode it was requeued with, and be resumed in that mode by the pass
once the dependency is in review (same repo) or has merged (other repo), restacked onto the dependency's branch. A unit that is running
SHALL NOT be interrupted by the line itself; it SHALL stop at its next check through the same path as a unit whose
parent went back, and a unit in review SHALL NOT be moved until it is next sent back for rework.

#### Scenario: A failed unit is requeued before its parent is reviewed

- **GIVEN** a failed unit with a thread, and a `Needs:` line added to its group for a group that is not yet in review
- **WHEN** the operator runs `abk requeue` on it
- **THEN** the unit is `planned` with the cause `gated`, its thread and branch are kept, no agent runs, and the command names the group it waits for

#### Scenario: The parent is in review

- **GIVEN** that gated unit
- **WHEN** the parent is in review and the pass runs
- **THEN** the unit resumes in the mode it was requeued with, on the parent's branch

#### Scenario: A running unit is not interrupted by the line

- **GIVEN** a unit with an agent step in progress
- **WHEN** a `Needs:` line is added to its group
- **THEN** the step finishes, and the tick logs once that the unit now depends on the parent

#### Scenario: A unit sent back for rework while its parent is not reviewed

- **GIVEN** an in-review unit with a `Needs:` dependency that is not in review and a review comment that sends it back
- **WHEN** the pass looks for units to readmit
- **THEN** the unit is `planned` and waits, not started, until the dependency is in review

#### Scenario: The status shows the wait

- **GIVEN** a gated unit
- **WHEN** an operator runs `abk status`
- **THEN** it is listed as waiting on the dependency group, not as failed or held

#### Scenario: A unit parked for a flaky test

- **GIVEN** a unit whose checks met a flaky test and the change written to fix it
- **WHEN** that change's unit is in review
- **THEN** the parked unit resumes, restacked onto the fix's branch

## MODIFIED Requirements

### Requirement: A replan leaves started work alone and says what changed

A replan SHALL NOT change a unit that is running, in review, failed, held, merged or satisfied: its state, branch, pull request, feedback and history
SHALL stay. A planned unit SHALL take the new plan's shape, an unstarted planned unit the plan no longer contains SHALL become `unplanned`, and a join
the plan proposed SHALL be dropped when a unit started meanwhile. The command SHALL print only what differs from the store before the replan:
dependencies added and removed, estimate and tier changes, units that became `unplanned`, joins dropped, and each started unit it
left alone. It SHALL print nothing for a unit that did not change.

#### Scenario: Started and finished units are kept

- **GIVEN** units that are running, in review, failed, held, merged and satisfied
- **WHEN** their change is planned again
- **THEN** each keeps its state, branch, pull request and history, and each started one is reported as kept

#### Scenario: A stale dependency is removed

- **GIVEN** a planned unit that depends on a unit the new plan does not ask for, and a dependency that a `Needs:` line asks for
- **WHEN** its change is planned again
- **THEN** the first dependency is gone, the second remains, and the output says which was removed

#### Scenario: A unit the plan dropped

- **GIVEN** an unstarted planned unit that the new plan does not contain
- **WHEN** its change is planned again
- **THEN** it becomes `unplanned` and is reported

#### Scenario: A join dropped

- **GIVEN** a plan that proposes a join with a unit that started while the planner ran
- **WHEN** the plan is applied
- **THEN** the join is dropped and reported

#### Scenario: Nothing changed

- **GIVEN** a change whose new plan equals the stored one
- **WHEN** it is planned again
- **THEN** the command prints that nothing changed

## REMOVED Requirements

### Requirement: A dependency can be required to merge first

**Reason**: The merge gate is unnecessary. A dependent can start on the parent's reviewed branch, so a `Needs:` line is only a dependency, and
the `merged` qualifier is deprecated and has no effect.
**Migration**: Drop the word `merged` from each `Needs:` line; the dependent then starts on the parent's branch once the parent is in review.
`abk tags` warns about each line until it is rewritten. A cross-repo dependency still waits for the merge.

### Requirement: The graph page shows a merge-gated dependency

**Reason**: There is no merge-gated dependency to show. The edge written as a `Needs:` line is drawn by "The graph page marks a Needs dependency".
**Migration**: None; the thick edge now carries the label `needs` instead of `merged`.

### Requirement: A gate added to a started unit holds it

**Reason**: The merge gate it held a started unit with no longer exists; the hold is now by the ordinary dependency, in "A Needs line added to a started unit waits for the parent to be reviewed".
**Migration**: A `merge_before` stored with a unit is dropped when the store is read; a unit that was `gated` for a merge is released as soon as its parent is in review.
