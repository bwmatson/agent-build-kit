## ADDED Requirements

### Requirement: A `Needs:` line has a plain kind and a merge kind

A `Needs: <change> group <n> — why` line SHALL be a plain dependency: a planned dependent in the parent's repo is released once the parent unit is in review,
merged or satisfied and builds on the parent's branch, and a dependent in another repo is released once the parent has merged. A line with the single word
`merged` straight after the group number, `Needs: <change> group <n> merged — why`, SHALL be a merge dependency. The word SHALL mean that only when it
follows the group number directly; anywhere else in the line it is part of the reason. `abk tags` and `abk check` SHALL accept a merge line without a
deprecation warning, SHALL keep refusing a `Needs:` of either kind on a group of the change's own, and SHALL keep warning of a `Needs:` that the
chain already implies only as they did. `link_needs` SHALL record the kind on the dependent unit as `merge_needs`, a subset of its `needs`, recomputed from
`tasks.md` every tick, so a removed line or a line changed back to plain removes the mark. A target named by a plain and a merge line of one group SHALL
be a merge dependency.

#### Scenario: A plain line is unchanged

- **GIVEN** a planned unit in repo A with `Needs: parent group 1 — why` and a parent unit in repo A that is `in_review`
- **WHEN** a tick plans and starts units
- **THEN** the dependent is startable on the parent's branch, with no wait, exactly as before this change

#### Scenario: A merge line is accepted without a warning

- **GIVEN** a group with `Needs: parent group 1 merged — the tick must run the fix`
- **WHEN** a person runs `abk tags` or `abk check` on the change
- **THEN** no deprecation warning is printed, the reason read is `the tick must run the fix`, and the dependent unit's `merge_needs` holds the parent unit after the next tick

#### Scenario: The word elsewhere is part of the reason

- **GIVEN** `Needs: parent group 2 — merged later`
- **WHEN** it is read
- **THEN** it is a plain dependency whose reason is `merged later`

#### Scenario: A merge line on the change's own group is an error

- **GIVEN** `Needs: this-change group 1 merged` inside group 2 of `this-change`
- **WHEN** `abk tags` runs
- **THEN** it reports the error it reports for any own-group `Needs:` and the line is not applied

#### Scenario: The mark follows the file

- **GIVEN** a unit linked with a merge dependency
- **WHEN** the word `merged` is deleted from the line and a tick runs
- **THEN** `merge_needs` no longer names the parent and the dependency is plain

### Requirement: A merge dependency holds a start until the parent is merged and its merge is in the running code

A planned unit with a merge dependency SHALL NOT start while the parent unit is not `merged`, or `satisfied` with its work landed; a parent in review,
rework, failed or held holds it. In addition, when the parent's repository is the checkout the running pipeline's code was loaded from, the unit SHALL NOT
start until that code contains the parent's merge. A tick SHALL record, as it starts and before its first round, a number, its start time and the head
commit of that checkout; the pipeline SHALL record, when a unit is first seen merged, the merge commit the code host reports and the number of the tick
that saw it. The merge SHALL be in the running code when the merge commit is an ancestor of the recorded head. When the merge commit or the head is
unknown, the merge SHALL be in the running code only when the tick is a later one than the tick that saw the merge. A parent merged before this rule
existed, with neither recorded, SHALL count as loaded. For a parent in any other repository the merge SHALL be in the running code only when the tick is a later one than the tick that saw the merge.
The dependency SHALL hold
whether or not the unit's stored dependencies reach the parent. A merge dependency SHALL gate only a start or a requeue: a unit already running or in
review is neither stopped nor sent back.

#### Scenario: The parent is only in review

- **GIVEN** a planned unit with a merge dependency on a same-repo parent that is `in_review`
- **WHEN** a tick runs
- **THEN** the unit is not started, holds no place, and is reported as waiting for the parent to merge

#### Scenario: The parent merged before the tick began and is in the loaded code

- **GIVEN** a merge dependency on a kit-code parent merged earlier, whose merge commit is an ancestor of the head recorded at the start of this tick
- **WHEN** the tick runs
- **THEN** the unit is released in this tick's first round and starts when it has a place

#### Scenario: The parent merges during the tick

- **GIVEN** a tick that started with a head that does not contain the parent's merge commit, and a poll in that tick that sees the parent merged
- **WHEN** the same tick plans and starts units
- **THEN** the dependent is not started, and it is released by a later tick whose recorded head contains the merge commit

#### Scenario: Merged, but the checkout has not been fast-forwarded

- **GIVEN** a merged kit-code parent and a tick that starts without its merge commit in the checkout's head
- **WHEN** that tick runs
- **THEN** the dependent still waits, and nothing is consumed, failed or requeued

#### Scenario: The head or the merge commit is unknown

- **GIVEN** a merge dependency whose parent has no recorded merge commit, seen merged by tick 12
- **WHEN** tick 12 runs, and then tick 13
- **THEN** the dependent waits in tick 12 and is released in tick 13

#### Scenario: A parent merged before this change

- **GIVEN** a merged parent whose record has no merge commit and no tick number
- **WHEN** a tick runs
- **THEN** its merge dependency counts as met

#### Scenario: A parent in another repository

- **GIVEN** a merge dependency on a parent in another repository, merged during this tick
- **WHEN** the same tick plans units
- **THEN** the dependent waits; a later tick releases it (the tick rule, since the sha test is only for the kit's own repository)

#### Scenario: A cross-repo plain `Needs:` is read as a merge dependency

- **GIVEN** a plain `Needs: other-change group 1 — why` where that group is in another repository, and the parent in review
- **WHEN** `abk tags` runs and then a tick links the line
- **THEN** `abk tags` prints an info note that the line waits for the merge, `link_needs` stores the dependency in `merge_needs`, the dependent waits for the merge and then for the next tick, and a failed dependent's wait ends the same way

#### Scenario: The chain already implies the dependency

- **GIVEN** a merge `Needs:` whose target the unit already reaches through its dependencies, so no edge is linked
- **WHEN** the target is in review
- **THEN** the unit still waits for it to merge

#### Scenario: A unit already running

- **GIVEN** a running unit whose group gains a merge `Needs:` on a parent in review
- **WHEN** a tick runs
- **THEN** the unit is not stopped and is not sent back

### Requirement: A dependency edge is a merge edge for three reasons only

A dependency edge SHALL be `merge` when it crosses repositories, when the author wrote `merged` on the `Needs:` line, or when its dependent is a failed
unit waiting on the parent (a `failed` unit, or one a person requeued while it waited and that is parked `planned` with a gated requeue); otherwise it SHALL
be `review`. A plain `Needs:` to a group of another repository SHALL be read as a merge dependency, with an info note from `abk tags` and `abk check`, and
`link_needs` SHALL store it in `merge_needs`. An author's merge kind SHALL be binding: the planner, which returns plain `depends_on` edges only, SHALL NOT
be able to loosen it, and a replan SHALL NOT clear it for any unit, started or not. No other circumstance (the parent being in the kit's own repository,
or the dependent being an e2e-test unit) SHALL make an edge `merge`.

#### Scenario: A cross-repo plain `Needs:` is read as merge

- **GIVEN** a plain `Needs:` to a group in another repository
- **WHEN** `abk tags` runs and a tick links it
- **THEN** an info note says it waits for the merge and `merge_needs` holds the parent

#### Scenario: The planner cannot loosen an author's merge

- **GIVEN** a `Needs: parent group 1 merged — why` and a plan that lists the parent in `depends_on` like any other edge
- **WHEN** the plan is stored, the change is replanned and `link_needs` runs
- **THEN** the edge is `merge` after each, and a started unit keeps its `merge_needs`

#### Scenario: A planned dependent on a plain same-repo Needs

- **GIVEN** a planned unit with a plain same-repo `Needs:` and a parent in review
- **WHEN** a tick runs
- **THEN** it starts on the parent's branch

#### Scenario: A kit-code parent is not forced

- **GIVEN** a plain same-repo `Needs:` from another change on a parent in the kit's own repository, parent in review
- **WHEN** a tick runs
- **THEN** the dependent starts on the parent's branch; only an author's `merged` would hold it

#### Scenario: An e2e-test unit with no dev stack is not forced

- **GIVEN** an `e2e-test` unit in a repo with no `dev_stack` on a plain same-repo `Needs:`, parent in review
- **WHEN** a tick runs
- **THEN** it is not held for the merge

#### Scenario: A failed unit's wait is a merge wait, whatever the kind

- **GIVEN** a failed unit with a plain same-repo `Needs:` on a parent that is in review
- **WHEN** a tick runs
- **THEN** it stays failed with `waiting for <parent> to merge`, and it is requeued only by a tick after the merge is loaded

#### Scenario: A requeue by a person keeps the merge wait

- **GIVEN** a failed unit with a plain same-repo `Needs:` on a parent in review, which a person requeues
- **WHEN** it is parked `planned`/`gated` and a tick runs
- **THEN** it is not released while the parent is only in review

#### Scenario: A planner-chosen merge kind does not exist

- **GIVEN** a plan with an extra field naming a kind for an edge
- **WHEN** it is parsed
- **THEN** the field has no effect on the edge's kind

### Requirement: A failed unit that waits on a merge dependency resumes after the merge and the next tick

A failed unit that waits on a parent SHALL stay failed while the dependency is unmet, shown as `failed, waiting on <unit>` with the reason of
the wait. Its wait SHALL end, and it SHALL be requeued once as the wait-end rule requires, only when its dependency is met as a merge dependency is above: the parent is
merged and the requeueing tick's code contains the merge. A parent that is only in review SHALL NOT end the wait, and a merge seen by the tick that is
running SHALL defer the requeue to the next tick. The history note of the requeue SHALL say the merge was loaded and by which tick. The kind of the `Needs:` SHALL NOT matter and neither SHALL the parent's repository; a failed unit that waits on a fix change needs no `merged` line.

#### Scenario: The fix is in review

- **GIVEN** a failed unit waiting on a merge `Needs:` whose parent just entered review
- **WHEN** the tick runs
- **THEN** the unit is not requeued and still shows `failed, waiting on <parent>: waiting for <parent> to merge`

#### Scenario: The fix merges in the tick

- **GIVEN** the same unit and a tick that sees the parent merged
- **WHEN** the tick runs to the end
- **THEN** the unit is not requeued in this tick, and its line reads `waiting for the next tick to load <parent>'s merge`

#### Scenario: The next tick loads the merge

- **GIVEN** a failed unit whose merge parent merged during the previous tick, and a tick whose recorded head contains the merge
- **WHEN** it runs
- **THEN** the unit is requeued once, in the mode the wait-end rule gives, and its history says its wait ended and the merge was loaded by that tick

#### Scenario: A plain `Needs:` waits for the merge too

- **GIVEN** a failed unit waiting on a plain same-repo `Needs:` whose parent enters review
- **WHEN** the tick runs
- **THEN** it is not requeued; once the parent merges and a later tick has it, it is requeued once

#### Scenario: A requeue by a person while the merge is unmet

- **GIVEN** a failed unit with an unmet merge dependency
- **WHEN** a person runs `abk requeue` on it
- **THEN** it is parked `planned` with cause `gated` and is released only when the dependency is met

### Requirement: The status names what a merge wait is for

A wait on a dependency SHALL be worded by what is missing: `waiting for <change> group <n> to merge` while the parent is not merged;
`waiting for the next tick to load <change> group <n>'s merge` when the parent is merged, the last tick's code lacks the merge and the checkout's current
head contains it; and `waiting for the kit checkout to include <change> group <n>'s merge` when neither has it. The wording SHALL be the same in
`abk status`, the pipeline log and the graph, and `abk status` SHALL change nothing.

#### Scenario: The three texts

- **GIVEN** three planned units with a merge dependency on a parent in review, a parent merged and not in the last tick's head but in the checkout's, and a parent merged and in neither
- **WHEN** `abk status` runs
- **THEN** it prints the three wordings above, one for each

### Requirement: The graph draws a merge dependency differently

The unit graph SHALL draw a dependency in a unit's `merge_needs` as a thick edge labelled `needs, merge`, and a plain `Needs:` dependency as the thick
edge labelled `needs`, as now. The legend and `docs/unit-graph.md` SHALL say so.

#### Scenario: Two kinds of edge

- **GIVEN** a unit with one plain and one merge `Needs:` dependency
- **WHEN** the graph is generated
- **THEN** it has one `==>|needs|` edge and one `==>|needs, merge|` edge

### Requirement: Existing `merged` lines delay no unit

The first tick that reads a merge dependency SHALL print, for each dependent that is planned, failed or held and whose parent is not merged, one line
`<unit>: now waits for <parent> to merge (Needs: ... merged in tasks.md)`, and SHALL change and requeue nothing. A change whose archived tasks files hold
`merged` lines SHALL NOT be read.

#### Scenario: Every parent has merged

- **GIVEN** the `merged` lines in the planning repo's live changes when this ships, and the unit store with their parents and dependents merged
- **WHEN** a tick runs
- **THEN** no unit gains a wait and no line is printed

#### Scenario: A started dependent with a merge line and an unmerged parent

- **GIVEN** a planned unit whose group has a merge `Needs:` on a parent in review
- **WHEN** the first tick after this ships runs
- **THEN** it prints the one line and the unit waits; a running unit with the same line prints nothing
