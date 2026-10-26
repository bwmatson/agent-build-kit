## ADDED Requirements

### Requirement: The agent that builds or reworks a unit writes its changelog entry to a stated convention

The prompts of the agents that build a unit, rework it and resolve a restack conflict
SHALL state the repository's changelog convention: where the entry goes, that a follow-up
to unreleased work edits that work's bullet, the entry's shape and content, and what must
never appear in it. On a conflict in the changelog the resolver SHALL be told to keep
both sides and fold bullets that describe one change.

#### Scenario: A follow-up to unreleased work

- **GIVEN** an unreleased bullet describing a feature
- **WHEN** a later unit corrects that feature before release
- **THEN** its prompt tells the agent to edit that bullet rather than add a second one

#### Scenario: A restack conflicts in the changelog

- **WHEN** the resolver is asked to settle a conflict in the changelog
- **THEN** it keeps both sides' bullets and folds any that describe one change

### Requirement: Tier 1 checks the changelog's form

The ordinary test suite SHALL fail when the changelog contains a conflict marker, two
bullets with no blank line between them, a duplicated bullet, a bullet outside a
section, headings out of order, or text the repository forbids naming, so the agent sees
the failure in its checks before any review.

#### Scenario: Two bullets run together

- **WHEN** a unit's change leaves two bullets with no blank line between them
- **THEN** tier 1 fails naming the file and the line

#### Scenario: A conflict marker is left behind

- **WHEN** the changelog contains a conflict marker
- **THEN** tier 1 fails

#### Scenario: A well-formed entry

- **WHEN** the entry follows the convention
- **THEN** the check passes
