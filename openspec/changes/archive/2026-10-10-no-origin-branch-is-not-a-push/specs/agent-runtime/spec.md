## ADDED Requirements

### Requirement: Only the pipeline pushes a unit's branch

When a repo has an `origin`, an agent step during which the unit's branch on that remote moves to a commit
made in the step's worktree SHALL fail with `AgentPushed`, naming the branch. A move made from elsewhere,
and a head the agent only fetched, SHALL NOT fail it. A remote that cannot be read before or after the
step SHALL NOT fail it.

#### Scenario: The agent pushes with an origin

- **GIVEN** a repo with an `origin` and an agent step on a unit branch
- **WHEN** the agent commits and pushes the branch to `origin`
- **THEN** the step fails with `AgentPushed` naming the branch

#### Scenario: The message is unchanged

- **WHEN** `AgentPushed` is raised
- **THEN** its message reads that the branch on the remote moved from one short commit to another during
  an agent step, to a commit made in this worktree, and that the pipeline is the only pusher

#### Scenario: A push from elsewhere

- **WHEN** a person pushes the branch to `origin` during an agent step
- **THEN** the step does not fail

### Requirement: With no origin there is no push to guard

When the repo has no `origin` (no remotes, or none named `origin`), the pipeline SHALL NOT treat a
change to the unit's local branch during an agent step as a push. A push by the agent to a remote not
named `origin` is not detected.

#### Scenario: An agent commits with no origin

- **GIVEN** a repo with no `origin` and an agent step on a unit branch
- **WHEN** the agent commits to the branch and does not push
- **THEN** the step does not fail

#### Scenario: The pipeline's own movement of the branch

- **GIVEN** a repo with no `origin`
- **WHEN** the pipeline commits, restacks or adopts a head on the unit branch outside an agent step
- **THEN** no `AgentPushed` is raised

#### Scenario: Other readers of the branch head keep the local fallback

- **GIVEN** a repo with no `origin`
- **WHEN** the push step or the restack compares the branch with its last recorded push
- **THEN** it reads the local branch head, as before
