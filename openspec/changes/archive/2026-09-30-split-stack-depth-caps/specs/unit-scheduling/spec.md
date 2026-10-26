# Spec Delta

## Purpose

Defines two separate caps where one field once served both purposes: how deep a stack may grow
before a new unit must wait to start, and how far a single merge will automatically cascade a
rebase before it asks a person instead.

## ADDED Requirements

### Requirement: The build cap is named for what it does

The limit on how deep a chain of open, same-repo dependencies may run before a new unit must wait to
start SHALL be configured as `stack_depth_build_cap`. Its behaviour SHALL be unchanged from the
single depth cap that preceded it.

#### Scenario: Starting a unit

- **WHEN** a planned unit's chain of open ancestors would exceed `stack_depth_build_cap`
- **THEN** it waits, exactly as the single depth cap caused it to wait before

### Requirement: A separate cap bounds how far a merge cascades a rebase

The workspace SHALL configure, separately from the build cap, the deepest a dependent's chain may run
and still be automatically rebased when the unit beneath it merges: `stack_depth_rebase_cap`. Where
an installation does not set it, it SHALL default to whatever the build cap resolves to, so that an
installation that only sets the build cap sees no change in behaviour.

#### Scenario: The default

- **WHEN** an installation sets a build cap and no rebase cap
- **THEN** the rebase cap has the same value, and nothing about restacking changes

#### Scenario: Set apart from the build cap

- **WHEN** an installation sets the rebase cap lower than the build cap
- **THEN** a stack may still grow to the build cap's depth, while a merge only cascades a rebase to
  the rebase cap's depth

### Requirement: A merge restacks a dependent only within the rebase cap

When a unit merges, each direct dependent's depth SHALL be measured against the graph with that merge
already recorded, and SHALL be restacked as today only when that depth is within the rebase cap. A
dependent beyond it SHALL NOT be restacked, and its branch SHALL be kept rather than removed as part
of that merge's cleanup.

#### Scenario: Within the cap

- **WHEN** a dependent's depth after the merge is within the rebase cap
- **THEN** it is restacked exactly as it would be with no rebase cap at all

#### Scenario: Beyond the cap

- **WHEN** a dependent's depth after the merge exceeds the rebase cap
- **THEN** it is not restacked, and the branch it depends on is not deleted as part of that merge

### Requirement: A dependent held for depth is a unit a person must act on

A dependent not restacked for exceeding the rebase cap SHALL be held, with the reason — naming the
depth and the cap — on its record, in the same sense any other held unit is one the pipeline will not
touch until a person or a later merge changes something.

#### Scenario: Reading why a unit is held

- **WHEN** a unit is held for exceeding the rebase cap
- **THEN** its record names the depth it reached and the cap it exceeded

### Requirement: A unit held for depth is reconsidered as later merges land

Because a dependent's depth only ever falls as its ancestors merge, the pipeline SHALL reconsider
every unit in the same repository currently held for exceeding the rebase cap whenever another merge
in that repository lands, and SHALL restack it automatically once its depth is again within the cap
— without a person retrying it by hand.

#### Scenario: Depth falls below the cap

- **WHEN** a unit held for exceeding the rebase cap has, after a later merge, a depth within the cap
- **THEN** it is restacked at that merge, and is no longer held

#### Scenario: Still beyond the cap

- **WHEN** a held unit's depth is still beyond the rebase cap after a later merge
- **THEN** it remains held, to be reconsidered at the next one
