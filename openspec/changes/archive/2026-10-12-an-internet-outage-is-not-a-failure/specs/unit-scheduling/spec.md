## MODIFIED Requirements

### Requirement: A unit whose step cannot reach the host is parked, not failed

When a step of a unit cannot complete because the code host is unavailable, the unit SHALL be
returned to planned with a host-unavailable cause, the failing step and the error text, SHALL be
readmitted by the running pass after a backoff that grows with each consecutive parking, and SHALL
resume at that step. A failure for any other reason (none of the host, the network and the model service being unavailable) SHALL fail the unit and SHALL record its error
text and step on the unit.

#### Scenario: The host is down when the pull request is opened

- **GIVEN** an approved, pushed unit whose pull request create is answered 500 on every attempt
- **WHEN** the step gives up
- **THEN** the unit is planned with the host-unavailable cause and the error text

#### Scenario: The host recovers

- **GIVEN** a parked unit whose backoff has elapsed and a host that answers
- **WHEN** the pass refreshes
- **THEN** the unit resumes at the step and the pull request opens

#### Scenario: Backoff grows

- **GIVEN** a unit parked for the third time
- **WHEN** the pass refreshes before its backoff has elapsed
- **THEN** the unit is skipped and the log says how long remains

#### Scenario: Another failure

- **WHEN** a step raises an error that is none of the host, the network and the model service being unavailable
- **THEN** the unit fails and its error text and step are on the unit

### Requirement: A failing plan names the way out

The message that a change is not planned until its `tasks.md` changes, and the status line for a failing plan, SHALL also say to run `abk replan`. A change whose attempts are used up SHALL be reported as given up with the command that plans every such change again, `abk replan --failed`, named.

#### Scenario: A change gives up

- **WHEN** a change reaches its allowed failed attempts
- **THEN** the message names `abk replan` as well as an edit of `tasks.md`

#### Scenario: The command for every given-up change

- **GIVEN** a change whose attempts are used up
- **WHEN** an operator runs `abk replan` with no selector
- **THEN** the change's line says it is given up and names `abk replan --failed`

### Requirement: A refused plan keeps its reason

A failed plan SHALL store the reason in the change's plan record, whether the planner returned a plan that was refused or the attempt raised or could not be made, and a refused plan SHALL store as well the unit ids the planner returned, not the planner's full reply. The reason SHALL be the first line of the error, at most 300 characters, with secrets removed by the same redaction as printed output, and a bare `abk replan` SHALL show the reason beside the plan state. A later successful plan SHALL clear it.

#### Scenario: The reason is shown

- **GIVEN** a plan refused because it claimed a built group
- **WHEN** `abk replan` is run with no selector
- **THEN** the change's line shows the failing state and the reason

#### Scenario: The reason is cleared

- **GIVEN** a record with a refusal reason
- **WHEN** the change is next planned successfully
- **THEN** the record has no reason

#### Scenario: A call that failed keeps its reason

- **GIVEN** a planner call that ends in an ordinary failure with a message of several lines and more than 300 characters
- **WHEN** the attempt is recorded
- **THEN** the attempt is counted and the record keeps the first line of the message cut to 300 characters

#### Scenario: A secret does not reach the record

- **GIVEN** a failure whose message contains a value the redaction set knows
- **WHEN** the attempt is recorded
- **THEN** the stored reason does not contain it

## ADDED Requirements

### Requirement: A unit whose agent run cannot reach the network is parked, not failed

When an agent run of a unit ends because the whole network is unavailable, the unit SHALL be returned to planned with a network-unavailable cause,
the failing step and the error text, SHALL keep its thread, branch and saved feedback, SHALL NOT be counted as failed and SHALL NOT be charged a
review, rework or check round, and SHALL be readmitted by the running pass after the same backoff as a unit parked for the host, resuming at that
step in the mode it was in. A failure that carries a strong sign of an outage (a name that cannot be resolved, a network that is unreachable) SHALL
park the unit on that evidence. A failure that carries a weak sign (one a reachable network can also produce) SHALL park the unit as
network-unavailable only when a bounded connectivity probe, which makes no model call, finds both the host the run called and every host of a
control group unreachable; a failure for any other reason SHALL fail the unit.

#### Scenario: The network is down during an implement step

- **GIVEN** a unit whose implement run ends on a name that could not be resolved
- **WHEN** the step gives up
- **THEN** the unit is planned with the network-unavailable cause, the step and the error text, and is not failed

#### Scenario: The whole network is down

- **GIVEN** a run that ends on a connect timeout while the probe reaches neither the API host nor any control host
- **WHEN** the step gives up
- **THEN** the unit is parked with the network-unavailable cause and not the service-unavailable one

#### Scenario: The unit resumes by itself

- **GIVEN** a parked unit whose backoff has elapsed
- **WHEN** the pass refreshes
- **THEN** the unit resumes at the step it stopped on, and a session it was continuing is continued

#### Scenario: No round is charged

- **GIVEN** a unit parked for the network at its rework step
- **WHEN** it resumes
- **THEN** its review, rework and check round counts are what they were before the step

#### Scenario: A weak sign with the API host reachable

- **GIVEN** a run that ends on a refused connection while the probe reaches the API host
- **WHEN** the step gives up
- **THEN** the unit fails with the error text and step

#### Scenario: A probe that errors does not park

- **GIVEN** a run that ends on a weak sign of an outage and a probe that raises an error
- **WHEN** the step gives up
- **THEN** the unit fails with the error text and step and is not parked

### Requirement: A unit whose agent run meets a model service that is down is parked, not failed

When an agent run of a unit ends because the model service is unavailable while the network works, the unit SHALL be returned to planned with a
service-unavailable cause, the failing step and the error text, SHALL keep its thread, branch and saved feedback, SHALL NOT be counted as failed
and SHALL NOT be charged a review, rework or check round, and SHALL be readmitted by the running pass after the same backoff as a unit parked for
the host, resuming at that step in the mode it was in. The service SHALL be taken as unavailable in two cases: a weak sign of an outage while the
connectivity probe finds the host the run called unreachable and at least one control host reachable, which parks without a cap; and a failure that
carries an HTTP status of 500 to 599, an overloaded 529 among them, after the runtime's own retries, which parks at most a configured number of times in
a row (`limits.service_unavailable_attempts`, default 5, a positive whole number checked at load) and then fails the unit with its error text and
step. A probe that cannot run SHALL count as the host being reachable. A 4xx status, a 401 or 403, a 429 usage or rate limit, a model refusal and a
permission or tool failure SHALL fail the unit as before.

#### Scenario: A provider outage with the network up

- **GIVEN** a run that ends on "Can't reach the API server" while the probe reaches no API host and reaches a control host
- **WHEN** the step gives up
- **THEN** the unit is parked with the service-unavailable cause and not the network-unavailable one, and is not failed

#### Scenario: The forge host is up and the API host down

- **GIVEN** a weak sign of an outage, an API host that does not connect and a forge host that does
- **WHEN** the step gives up
- **THEN** the unit is parked with the service-unavailable cause

#### Scenario: An overloaded service parks, bounded

- **GIVEN** a unit whose run ends on the status 529 after the runtime's own retries
- **WHEN** the step gives up
- **THEN** the unit is planned with the service-unavailable cause, the step and the error text

#### Scenario: The cap is reached

- **GIVEN** a unit that has been parked for a 5xx or 529 as many times in a row as `limits.service_unavailable_attempts` allows
- **WHEN** its next run ends on a 5xx or 529
- **THEN** the unit fails with the error text and step

#### Scenario: The attempts setting is checked

- **GIVEN** `limits.service_unavailable_attempts` set to 0, to a negative number or to a number that is not whole
- **WHEN** the configuration is loaded
- **THEN** it is refused with a message naming the key, and the default is 5

#### Scenario: A rejected key still fails

- **GIVEN** a unit whose run ends on a 401
- **WHEN** the step gives up
- **THEN** the unit fails with the error text and step

#### Scenario: A model refusal still fails

- **GIVEN** a unit whose run ends on a model refusal
- **WHEN** the step gives up
- **THEN** the unit fails with the error text and step

#### Scenario: A probe that errors does not park

- **GIVEN** a run that ends on a weak sign of an outage and a probe that raises an error
- **WHEN** the step gives up
- **THEN** the unit fails and is not parked as service-unavailable

#### Scenario: A provider outage does not stop other work

- **GIVEN** a unit parked with the service-unavailable cause
- **WHEN** a tick runs
- **THEN** no network pause is written for it and the tick starts ready units as usual

### Requirement: The two outage causes are shown differently

The status, the unit graph and the unit page SHALL show a unit parked with the network-unavailable cause as waiting for the network and a unit parked
with the service-unavailable cause as waiting for the model service, each with the step and the time remaining, and neither as failed.

#### Scenario: Waiting for the network

- **GIVEN** a unit parked with the network-unavailable cause and its backoff running
- **WHEN** an operator runs `abk status`
- **THEN** it is listed as waiting for the network, with its step and the time remaining, not as failed

#### Scenario: Waiting for the model service

- **GIVEN** a unit parked with the service-unavailable cause and its backoff running
- **WHEN** an operator runs `abk status`
- **THEN** it is listed as waiting for the model service, with its step and the time remaining, not as failed and not as waiting for the network

### Requirement: An outage of the whole network stops new agent runs until it is back

When a unit is parked with the network-unavailable cause, the pipeline SHALL pause the starting of agent runs with a network pause that is visible in
the status and the run log. While it stands, a tick SHALL start no agent run, and SHALL end it on the first tick whose connectivity probe finds a
control host reachable, whatever time the pause was given. A unit parked with the service-unavailable cause SHALL NOT write or extend this pause.
Usage and rate-limit pauses SHALL behave as before.

#### Scenario: The probe still fails

- **GIVEN** a network pause and a probe that finds no control host reachable
- **WHEN** a tick runs
- **THEN** no agent run starts and the log says it is waiting for the network

#### Scenario: The network is back

- **GIVEN** a network pause and a probe that reaches a control host
- **WHEN** a tick runs
- **THEN** the pause is cleared and ready units start as usual

#### Scenario: A failure of the unit's own

- **GIVEN** a unit that runs and fails for a reason with no sign of an outage
- **WHEN** the step gives up
- **THEN** the unit fails, whether or not a network pause stood before it ran

### Requirement: A planning attempt is not spent on an outage

When the planner's model call of a change ends because the whole network is unavailable, or because the model service is unavailable, the pipeline SHALL NOT count it as a failed attempt. The change's plan record SHALL keep the attempt count it had, SHALL say it is waiting for the network or for the model service with the time it began waiting and the time of the next try, and SHALL keep the reason. The next try SHALL be after the same backoff steps as a parked unit (1, 2, 5, 10, then 30 minutes by consecutive waits), and a wait for the network SHALL end, whatever the time, on the first tick whose connectivity probe finds a control host reachable. A sign of an outage SHALL be told by the same rules as for a unit's agent run: a strong sign or an HTTP status is taken as it is, a weak sign only by the connectivity probe, and a probe that errors counts as no outage. A wait for the model service by HTTP status SHALL be bounded by `limits.service_unavailable_attempts` consecutive waits, after which the next such failure SHALL count as an ordinary failed attempt. A failure of any other kind SHALL count as before and end a wait. A tick under a network pause SHALL plan no change and make no model call for planning. An edit of `tasks.md`, a successful plan and `abk replan --forget` SHALL end a wait.

#### Scenario: A planner call fails with a network outage

- **GIVEN** a change with one failed attempt and a planner call that ends on a name that could not be resolved
- **WHEN** the tick plans it
- **THEN** its attempts are still one, it is recorded as waiting for the network with the time of the next try, and no unit is stored

#### Scenario: Three outage failures in a row

- **GIVEN** a change that has never been planned and three planner calls in a row, each after its wait, that end on a network outage
- **WHEN** the third is recorded
- **THEN** its attempts are still what they were before the first, and it is not given up

#### Scenario: An ordinary planner failure still counts

- **GIVEN** a planner call that ends in a failure with no sign of an outage
- **WHEN** the attempt is recorded
- **THEN** the attempts rise by one, the reason is kept and no wait is recorded

#### Scenario: An ordinary failure ends a wait

- **GIVEN** a change recorded as waiting for the network and a next planner call that fails for another reason
- **WHEN** it is recorded
- **THEN** the wait is gone, the attempts rise by one and the reason is kept

#### Scenario: A weak sign with the API host reachable

- **GIVEN** a planner call that ends on a refused connection while the probe reaches the host it called
- **WHEN** the attempt is recorded
- **THEN** it counts as an ordinary failed attempt and no wait is recorded

#### Scenario: The network is back

- **GIVEN** a change waiting for the network with its next try still ahead, and a network pause that a tick clears because a control host connects
- **WHEN** the tick plans
- **THEN** the change is planned on that tick and the wait is gone from its record

#### Scenario: The backoff elapses

- **GIVEN** a change waiting for the model service whose next try has passed
- **WHEN** a tick plans
- **THEN** the change is planned again, and a success removes the wait and keeps the attempts it had

#### Scenario: A change that waits is not asked about

- **GIVEN** a change waiting with its next try ahead and no other change to plan
- **WHEN** a tick decides whether to ask the usage guard
- **THEN** planning is not counted as work to do and no model call is made for it

#### Scenario: A tick under the network pause plans nothing

- **GIVEN** a network pause and a probe that reaches no control host, and a change that has never been planned
- **WHEN** a tick runs
- **THEN** no planner call is made and no wait or attempt is recorded

#### Scenario: A service outage is bounded

- **GIVEN** `limits.service_unavailable_attempts` of 3 and a change whose planner call ended on a 529 three times in a row
- **WHEN** a fourth call ends on a 529
- **THEN** it counts as a failed attempt with its reason and the wait ends

#### Scenario: A rate limit keeps its own path

- **GIVEN** a planner call that ends on a 429 usage or rate limit
- **WHEN** the attempt is recorded
- **THEN** it is treated as before and is not recorded as a wait

### Requirement: A change waiting on an outage is shown as waiting

A bare `abk replan` and `abk status` SHALL show a change whose plan waits for the network as waiting for the network and one whose plan waits for the model service as waiting for the model service, each with the time it began and the time of the next try and the attempts as they stand, and neither as failing or given up. `abk replan` of such a change SHALL plan it at once, whatever the wait, and when the outage is still on SHALL say it is waiting for the network or for the model service, that no attempt was used and when the next try is, and not say the plan failed. `abk replan --failed` SHALL select it. A record spent before this requirement SHALL still read as given up.

#### Scenario: The listing says waiting

- **GIVEN** a change whose plan waits for the network
- **WHEN** an operator runs `abk replan` with no selector
- **THEN** its line says it is waiting for the network, with the time of the next try and its attempts, and not `failing` or `given up`

#### Scenario: The status says waiting

- **GIVEN** a change whose plan waits for the model service
- **WHEN** an operator runs `abk status`
- **THEN** it is listed as waiting for the model service with the next try, not as failing and not as waiting for the network

#### Scenario: Replan of a change waiting on the network

- **GIVEN** a change whose plan waits for the network and an outage that is still on
- **WHEN** an operator runs `abk replan` for it
- **THEN** one planner call is made, the output says the change is waiting for the network and that no attempt was used, and it does not say the plan failed

#### Scenario: Replan after the outage

- **GIVEN** a change whose plan waits for the network and a network that is back
- **WHEN** an operator runs `abk replan` for it
- **THEN** the change is planned and its record no longer waits

#### Scenario: A spent plan from before

- **GIVEN** a record with its attempts used up and no wait
- **WHEN** an operator runs `abk replan` with no selector
- **THEN** its line says it is given up and `abk replan --failed` plans it again
