## ADDED Requirements

### Requirement: Wall time is reported by cause

The framework SHALL report, by `abk report --waits`, each unit's wall time by cause (planned blocked, planned ready, running in the agent, in checks, in other work, in review for a person, in review rounds, paused, failed), the hours the pipeline ran nothing split into a full queue and room to spare, and the estimate ratio per kind of unit when estimates exist, by unit or by day and as JSON. The causes SHALL sum to the wall time, and a figure never recorded SHALL read as absent.

#### Scenario: The recorded analysis

- **GIVEN** a recorded fixture of 72 merged units
- **WHEN** the waits report runs
- **THEN** it shows 1,343 h planned, 172 h in review, 93 h running and 11.6 h of agent calls
- **AND** it shows 47 of 87 hours with nothing running, 17 with a full queue and 30 with room

#### Scenario: Regrouping

- **WHEN** the report is grouped by unit and by day
- **THEN** both give the same total

#### Scenario: No records

- **WHEN** a unit has no wait records
- **THEN** its causes read as absent
