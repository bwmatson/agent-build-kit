## MODIFIED Requirements

### Requirement: A call outside the unit graph is recorded under its own node

An agent call made by the framework outside a unit's graph SHALL write a ledger row with the schema every row has, under the node named for
the call: `restack` for the conflict resolver, `plan` for the planner, `track_health`, `track_improve`, `track_recommend` and `track_propose`
for a track phase, `init_research` and `init_propose` for init's runs, `policy_probe` for the policy probe, `login_refresh` for the
login refresh, `chat` for a chat turn and `chat_commit` for the attach flow's fix turn. The row SHALL be built by one helper that the unit steps also use, so
cost, its cumulative baseline, tokens, context, turns, duration, session and source are worked out in one place. `unit` SHALL be blank
where the call has none, and `change` and `repo` SHALL be filled when the caller knows them. `role` SHALL be the request's role,
`generic` where the call has none of the roles the `models` settings choose a model for, and `model` the model the request names, absent when the runtime
chooses. A figure the call does not report SHALL be absent, never zero. A call that fails SHALL write its row with outcome `failed`. A write that fails SHALL be dropped and reported
once and SHALL NOT affect the call.
The usage estimate counts a row by its `cost.incremental_usd`, with a unit or without one: a row with no cost, as the login refresh writes, and a call killed
before it delivered a result, which writes no row, add nothing to the estimate.

#### Scenario: A row for a call with no unit

- **WHEN** the planner makes a call that reports tokens and cost
- **THEN** one row exists with node `plan`, a blank unit, the reported tokens and cost, source `reported` and outcome `ok`

#### Scenario: A failed call

- **WHEN** a track phase's agent returns an error
- **THEN** its row has outcome `failed` and the figures the runtime reported

#### Scenario: A runtime that reports nothing

- **WHEN** the login refresh discards the agent's output
- **THEN** its row has source `none`, no tokens and no cost, a duration, and outcome from the exit status

#### Scenario: The unit steps are unchanged

- **GIVEN** the same results from a unit's `implement`, `review` and `fix_checks` steps
- **WHEN** they are recorded through the helper
- **THEN** the rows are identical to those written before the helper existed

#### Scenario: A secret in a free-text field

- **WHEN** a row of a new node is written
- **THEN** its identifying fields are kept as written and a secret in `outcome` or any other text field is withheld

#### Scenario: A usage estimate

- **GIVEN** rows with a blank unit, one of them a `plan` row with a cost, and a row for a unit since a reading
- **WHEN** the usage estimate and its calibration count the units that spent
- **THEN** the blank unit is not counted as a unit and the unit is, and on the `cost` basis the `plan` row's cost is counted with the unit's

#### Scenario: A row with no cost

- **GIVEN** a `login_refresh` row with a duration and no cost
- **WHEN** the usage estimate counts the cost recorded since a reading
- **THEN** the row adds nothing and does not make a unit
