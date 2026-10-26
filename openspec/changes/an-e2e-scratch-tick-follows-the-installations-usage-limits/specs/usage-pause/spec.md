## ADDED Requirements

### Requirement: A process can run with the usage guard off, announced and never from the configuration

The per-machine setting `ABK_USAGE_GUARD` SHALL accept `on` (the default) and `off`, and any other value SHALL be refused naming the setting and both values. It SHALL NOT be a key of `abk.yaml`. In a process where it is `off`, a start decision SHALL go ahead without a usage reading and without applying a threshold, an allowance or an estimate, and no usage pause SHALL be written. `abk tick` SHALL print as its first line that the guard is off and name the setting, and `abk status` SHALL show the same line. With the setting `on`, the guard SHALL behave as before and neither line SHALL appear. The decision SHALL still be made in the usage module alone.

#### Scenario: Off, a high reading does not hold a start

- **GIVEN** `ABK_USAGE_GUARD=off` and a reading of 91 percent against a threshold of 70
- **WHEN** a unit is ready to start
- **THEN** it starts, no reading is taken, and the tick's first line says the usage guard is off

#### Scenario: On, a high reading holds a start as before

- **GIVEN** the setting unset and a reading of 91 percent against a threshold of 70
- **WHEN** a unit is ready to start
- **THEN** the start is refused naming 91 and 70, and no line about the guard being off appears

#### Scenario: The setting is not configuration

- **WHEN** `abk.yaml` carries a `usage_guard` key
- **THEN** the configuration is refused as having an unknown key

#### Scenario: A value that is neither

- **WHEN** the setting is `maybe`
- **THEN** it is refused naming the setting and the values `on` and `off`
