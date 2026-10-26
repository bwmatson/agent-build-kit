## ADDED Requirements

### Requirement: A forge can squash-merge a pull request at a given head

The `Forge` protocol SHALL have a merge operation that, given a pull request and the head commit the caller approved, squash-merges the
pull request only if its head is still that commit, and returns the commit the merge produced. A host that refuses, because the pull
request is not mergeable, a protection rule applies, the head has moved or the pull request is closed, SHALL cause the operation to
raise a refusal carrying the host's reason. A forge SHALL declare whether it merges at all.

#### Scenario: A mergeable pull request

- **GIVEN** an open pull request whose head is the approved commit
- **WHEN** the merge operation is called
- **THEN** the pull request is squash-merged and the merge commit is returned

#### Scenario: The head moved

- **GIVEN** a pull request whose head differs from the approved commit
- **WHEN** the merge operation is called
- **THEN** nothing is merged and a refusal naming the moved head is raised

#### Scenario: A host refuses

- **GIVEN** a host that answers that the pull request is not mergeable
- **WHEN** the merge operation is called
- **THEN** a refusal carrying the host's reason is raised and nothing is retried

### Requirement: GitHub merges by squash with the head as a guard

The GitHub forge SHALL merge by the squash method and SHALL send the approved head as the commit the host must still find at the head
of the pull request. A response that says the head has moved, the pull request is not mergeable or a rule blocks it SHALL be a
refusal, and any other non-success SHALL be an ordinary transport failure.

#### Scenario: Squash

- **WHEN** the GitHub forge merges a pull request
- **THEN** the request names the squash method and the approved head

#### Scenario: A blocked merge

- **GIVEN** the host answers that a rule blocks the merge
- **WHEN** the merge is attempted
- **THEN** a refusal carrying the host's message is raised

### Requirement: Azure DevOps completes a pull request by squash with the head as a guard

The Azure DevOps forge SHALL complete the pull request with the squash merge strategy and SHALL send the approved head as the last
merge source commit, and SHALL return the commit of the completed merge. When the host reports the completion refused, or the pull
request still not completed after the call, the operation SHALL raise a refusal carrying the host's reason.

#### Scenario: Completed

- **GIVEN** an active pull request whose source head is the approved commit
- **WHEN** the Azure DevOps forge merges it
- **THEN** the request completes it by squash with that head and the merge commit is returned

#### Scenario: Not completed

- **GIVEN** a host that leaves the pull request active with a reason after the call
- **WHEN** the operation returns
- **THEN** a refusal carrying the reason is raised

### Requirement: The local forge never merges

The local forge SHALL declare that it does not merge, and its merge operation SHALL raise a refusal saying a merge there is a
person's, made with git. A repo whose forge does not merge SHALL never be landed.

#### Scenario: The local forge

- **WHEN** the merge operation is called on the local forge
- **THEN** a refusal is raised and nothing in the repository changes

### Requirement: A merge is retried only after asking whether it landed

The merge operation SHALL be declared with the forge operations as a write that is repeated after a transient failure only once the
read of the commit a merged pull request produced shows the merge did not happen. When that read shows it did, the operation SHALL
return that commit and merge nothing again. A refusal SHALL NOT be repeated.

#### Scenario: Transient failure after the host merged

- **GIVEN** a merge call that fails after the host completed the merge
- **WHEN** the call is retried
- **THEN** the commit read finds the merge, that commit is returned and no second merge is attempted

#### Scenario: Transient failure before the host merged

- **GIVEN** a merge call that fails before the host did anything
- **WHEN** the call is retried
- **THEN** the merge is attempted again

#### Scenario: A refusal

- **WHEN** the host refuses a merge
- **THEN** it is raised at once with no retry

### Requirement: The merge operation is not reachable by the agent

The merge operation SHALL be called only from pipeline code. The agent's denial of every route to a merge, in the policy hook, the
command policy and the runtime's disallowed tools, SHALL be unchanged by this operation.

#### Scenario: The deny lists

- **WHEN** the deny lists of the policy hook, the command policy and each forge are compared with their contents before this change
- **THEN** they are equal

#### Scenario: A source search

- **WHEN** the source is searched for callers of the merge operation
- **THEN** the only callers are the landing step and the forges' own tests
