## MODIFIED Requirements

### Requirement: Usage limits are a runtime capability, not an assumption

A runtime SHALL declare whether it has an account-level usage window at all.
Where it does, today's rule stands: an unknown reading pauses. Where it does
not — an agent billed on demand, with no ceiling over a time window — the
usage check SHALL be skipped entirely rather than treated as an unknown
reading, and a run SHALL be limited only by the work it has to do. A split of a repo's
tier 2 tests MAY have a gate that reads a model provider's usage (`tests.tier2_splits.<name>.gate.provider`); that window SHALL decide only whether the
split's tier 2 tests are held, SHALL NOT make any runtime one with an
account-level usage window, and SHALL NOT pause the pipeline or stop a unit
starting.

#### Scenario: A runtime with no usage window

- **WHEN** units are started under a runtime billed on demand
- **THEN** no usage reading is attempted, nothing pauses for want of one, and
  the pause threshold has no effect

#### Scenario: A runtime with a usage window

- **WHEN** a reading cannot be obtained under the current runtime
- **THEN** the pipeline pauses, as it does today

#### Scenario: A provider window does not pause the pipeline

- **GIVEN** the selected runtime is billed on demand as far as the account is concerned, and a split's gate has a provider whose usage is over its threshold
- **WHEN** units are started
- **THEN** no account-level reading is attempted, nothing pauses, and units start; the split's tier 2 tests are held instead
