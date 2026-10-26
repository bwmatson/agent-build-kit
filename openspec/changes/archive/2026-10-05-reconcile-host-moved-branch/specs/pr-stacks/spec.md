## ADDED Requirements

### Requirement: A branch the host holds at the same work is adopted, not refused

When a unit's branch on the host is at a commit other than the one the pipeline
last pushed, the pipeline SHALL decide by what each carries against the unit's
base. A host branch that carries the same change as the unit's local head SHALL
be adopted as the last push, and the unit SHALL continue without a human
editing any record. The commits to carry over onto a different host head SHALL
be those the host's branch lacks by patch, not those after the last recorded
push. A host branch that carries a change the local branch lacks, or local work
that does not apply onto it, SHALL still stop the unit for a person.

#### Scenario: The host holds the same work at a rewritten commit

- **GIVEN** a unit whose approved local head carries the same change as the
  branch on the host, the host's commits having been rewritten
- **WHEN** the unit is pushed
- **THEN** the host's head is adopted as the last push and the approved head is
  pushed with a lease on it
- **AND** the unit does not fail

#### Scenario: The local branch was restacked since the last push

- **GIVEN** a local branch restacked onto a newer trunk, so the recorded last
  push is not among its ancestors, and the host holds an older form of the same
  work
- **WHEN** the unit is pushed
- **THEN** the work is recognised as the same and nothing is replayed

#### Scenario: The host holds work the pipeline does not have

- **GIVEN** a host branch with a change the local branch lacks that does not
  combine with local work
- **WHEN** the unit is pushed
- **THEN** the unit stops for a person with a message naming the host's head
