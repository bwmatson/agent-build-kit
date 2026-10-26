# review-triage Specification

## Purpose
TBD - created by archiving change units-are-triaged-by-review-tier. Update Purpose after archive.

## Requirements

### Requirement: A pull request carries a label for its review tier

When review is enabled and a unit with a pull request has a recorded verdict, the pull request SHALL carry exactly one of the labels
`review-auto`, `review-light` and `review-full`, matching the verdict's tier, on every forge the pipeline supports. A new verdict for
the unit SHALL replace the label. The label SHALL be cosmetic: a host that keeps no labels, or a failed call, SHALL be logged and
SHALL NOT raise, change a unit, or stop a pass. The review labels SHALL stay on a finished pull request, and clearing a unit's
state labels SHALL NOT remove them.

#### Scenario: A verdict is recorded

- **GIVEN** a unit in review with a pull request and a recorded verdict of `light`
- **WHEN** the unit's labels are brought in line
- **THEN** the pull request carries `review-light` and no other review label

#### Scenario: The tier is raised

- **GIVEN** a pull request labelled `review-light`
- **WHEN** the unit is reworked and its new verdict is `full`
- **THEN** the pull request carries `review-full` and no longer `review-light`

#### Scenario: A host with no labels

- **GIVEN** a forge that keeps no labels
- **WHEN** a verdict is recorded
- **THEN** one line says so and the unit is unaffected

#### Scenario: The unit merges

- **GIVEN** a merged unit's pull request labelled `review-full`
- **WHEN** its state labels are cleared
- **THEN** `review-full` is still there

### Requirement: Units in review are shown with the highest tier first

`abk status` and the review page SHALL list units in review ordered by their recorded review tier: `full` first, then `light`, then
units with no verdict, then `auto`, and by arrival order within a tier. A unit with no verdict SHALL be shown as it is today. The
order SHALL change only what is shown and SHALL NOT change which unit the pipeline works on next. `abk status` SHALL show each unit
in review with its tier, and SHALL list a unit whose verdict is `auto` as awaiting review.

#### Scenario: A mixed queue

- **GIVEN** units A (`light`), B (`full`) and C (`light`) entered review in that order
- **WHEN** `abk status` lists them
- **THEN** B is first, then A, then C

#### Scenario: No verdict

- **GIVEN** a unit in review with no recorded verdict between a `full` and an `auto` unit
- **WHEN** the queue is listed
- **THEN** it is listed after the `full` unit and before the `auto` one, shown as before

#### Scenario: Ordering does not schedule

- **WHEN** the pipeline picks the next unit to work on
- **THEN** it picks as it did before this change, whatever the tiers

### Requirement: A card is raised only for units that need a person's attention

A card of the review kind SHALL be raised for a unit in review whose recorded tier is `light` or `full`. A unit whose recorded tier
is `auto` SHALL raise none. A unit in review with no recorded verdict SHALL raise a card as it does today. Cards for failed and held
units SHALL be unchanged, and an existing card for a unit whose tier is now `auto` SHALL be cleared by the existing reconciliation.

#### Scenario: A light unit

- **GIVEN** a unit in review with a recorded tier of `light`
- **WHEN** the desired cards are computed
- **THEN** there is a review card for it

#### Scenario: An auto unit

- **GIVEN** a unit in review with a recorded tier of `auto`
- **WHEN** the desired cards are computed
- **THEN** there is none for it

#### Scenario: No verdict

- **GIVEN** a unit in review with no recorded verdict
- **WHEN** the desired cards are computed
- **THEN** there is a review card for it

#### Scenario: A failed auto unit

- **GIVEN** a unit that failed and whose recorded tier is `auto`
- **WHEN** the desired cards are computed
- **THEN** there is a failed card for it

### Requirement: The review tab shows the tier and why beside the brief

The review tab of a unit with a recorded verdict SHALL show the verdict's tier and its reason at its head, beside the unit's stored
focus and skippable lists. The review route's answer SHALL carry the tier, the reason and those lists, and the pipeline summary SHALL
carry the tier. For a unit with no verdict both SHALL omit them and the tab SHALL look as it does today.

#### Scenario: A unit with a verdict

- **GIVEN** a unit with the recorded tier `full` and the reason "a changed path is protected"
- **WHEN** its review tab is opened
- **THEN** the tab shows `full` and the reason with the focus and skippable lists

#### Scenario: No verdict

- **GIVEN** a unit with no recorded verdict
- **WHEN** its review tab is opened
- **THEN** no tier or reason is shown and nothing else differs

### Requirement: Only display, labels, cards and the history floor read a verdict

No part of the pipeline SHALL read a recorded verdict except to set a label, to order or describe what is shown, to choose which
units raise a card, to compute the history floor of a later verdict, and to print a report. No part of it SHALL read a verdict to
decide a state, a hold, a size or a merge.

#### Scenario: A source search

- **WHEN** the source is searched for readers of the verdict file
- **THEN** every reader is one of those named above
