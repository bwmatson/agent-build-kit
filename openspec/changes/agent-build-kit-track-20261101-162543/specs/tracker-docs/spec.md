## ADDED Requirements

### Requirement: The architecture document describes the work tracker

`docs/architecture.md` SHALL have a work-tracker section covering the reconciler, the wanted
board, the mapping file by level, the Epic header and manual parent, and the claim and ownership
read that gate a unit's start. `docs/hand-off.md` SHALL NOT call the tracker hold "interim".

#### Scenario: No tracker section
- **WHEN** `docs/architecture.md` has no work-tracker heading
- **THEN** the documentation test fails

#### Scenario: Stale wording
- **WHEN** `docs/hand-off.md` calls the hold the "interim" path
- **THEN** the documentation test fails
