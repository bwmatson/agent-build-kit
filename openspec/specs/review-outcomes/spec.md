# review-outcomes Specification

## Purpose
TBD - created by archiving change units-are-triaged-by-review-tier. Update Purpose after archive.

## Requirements

### Requirement: A verdict record gains an outcome derived from the unit's history

For each unit with a final verdict record (an interim record, from a round that did not approve, has no outcome), abk SHALL derive and store an outcome: `open` while the unit is not merged, `clean` when a
person merged it with no entry in its history whose cause is `rework`, `reworked` with the count of those entries when it merged
after one or more, `reverted` when a revert of its merge is found, and `closed` when it was closed unmerged. The outcome SHALL be
derived from the history and the repository alone, so deriving it again from the same inputs gives the same result. A restack onto a
moved base SHALL NOT count as a rework. The record SHALL also say whether a revert could be checked.

#### Scenario: Merged without rework

- **GIVEN** a unit whose history has no rework entry and which a person merged
- **WHEN** its outcome is derived
- **THEN** it is `clean`

#### Scenario: Reworked twice

- **GIVEN** a merged unit whose history has two entries with the cause `rework` and one `base_changed`
- **WHEN** its outcome is derived
- **THEN** it is `reworked` with a count of two

#### Scenario: Closed

- **GIVEN** a unit whose pull request was closed unmerged
- **WHEN** its outcome is derived
- **THEN** it is `closed` and counts as no sample

#### Scenario: Deriving again

- **WHEN** the outcome is derived twice from the same history and repository
- **THEN** both results are equal

### Requirement: A revert is a trunk commit that names the unit's merge

A merged unit SHALL be `reverted` when the forge reports the commit its pull request produced and a commit reachable from the repo's
trunk, after that commit, carries a message line `This reverts commit <sha>` naming it in full, or a message line `Reverts
<owner>/<repo>#<number>` naming the unit's pull request. A commit that names another commit or another pull request SHALL NOT count.
A forge that cannot say what commit a merge produced SHALL answer empty, and a unit merged through it SHALL not be looked at for a
revert and SHALL say so in its record. A merged unit SHALL be rechecked until it has been merged for a fixed number of days, after
which its outcome SHALL be final.

#### Scenario: git revert

- **GIVEN** a unit merged as commit `abc…` and a later trunk commit whose message holds `This reverts commit abc…`
- **WHEN** its outcome is derived
- **THEN** it is `reverted`

#### Scenario: A host's revert pull request

- **GIVEN** a later trunk commit whose message holds `Reverts acme/app#42` and a unit whose pull request is #42 in `acme/app`
- **WHEN** its outcome is derived
- **THEN** it is `reverted`

#### Scenario: Another commit

- **GIVEN** a later trunk commit that reverts a different commit
- **WHEN** the unit's outcome is derived
- **THEN** it is not `reverted`

#### Scenario: A forge that cannot say

- **GIVEN** a forge that answers no merge commit
- **WHEN** the unit's outcome is derived
- **THEN** it is `clean` or `reworked` as its history says and the record says the revert was not checked

#### Scenario: Past the horizon

- **GIVEN** a unit merged for longer than the recheck horizon
- **WHEN** a trunk commit then reverts it
- **THEN** its outcome is unchanged

### Requirement: Rates are computed only over units whose pull request carried the brief

The clean-merge rate, the agreement rate and the sample counts of a class SHALL be computed only over final verdict records whose `brief`
is true. A record whose `brief` is false SHALL be kept with its outcome and SHALL be excluded from every rate, count and gate, and
the number excluded SHALL be reported. A class's samples SHALL be its included records whose outcome is `clean`, `reworked` or
`reverted`. The clean-merge rate SHALL be `clean` over samples. The agreement rate SHALL be, among the samples whose evidence tier was
`auto`, the share that are `clean`, and a class with no such samples SHALL have no agreement figure.

#### Scenario: A mixed class

- **GIVEN** a class with four `clean` records and one `reworked` record with `brief` true, and ten `clean` records with `brief`
  false
- **WHEN** its rates are computed
- **THEN** it has five samples, a clean-merge rate of 0.8, and ten records are reported as excluded

#### Scenario: Agreement

- **GIVEN** three samples with evidence tier `auto`, two `clean` and one `reworked`, and two samples with evidence tier `light`
- **WHEN** the agreement rate is computed
- **THEN** it is two thirds over three samples

#### Scenario: No auto samples

- **GIVEN** a class whose samples all have evidence tier `light`
- **WHEN** the agreement rate is computed
- **THEN** there is no agreement figure

#### Scenario: A revert

- **GIVEN** a unit merged with no rework and later reverted
- **WHEN** the rates are computed
- **THEN** it is a sample and is not clean

### Requirement: A class clears the gates on its own record

A class SHALL clear the gates when its samples reach `review.auto_land.min_samples` and its clean-merge rate reaches
`review.auto_land.min_clean_rate`. A class that is not named in `review.classes` SHALL be shown with its figures and SHALL be marked
as not nameable. Clearing the gates SHALL change nothing but what is reported: promotion is a person's edit of abk.yaml.

#### Scenario: Enough samples

- **GIVEN** `min_samples` 20 and `min_clean_rate` 0.95 and a named class with 20 samples of which 19 are clean
- **WHEN** the gates are checked
- **THEN** the class clears them

#### Scenario: Too few samples

- **GIVEN** a class with 19 samples, all clean
- **WHEN** the gates are checked
- **THEN** it does not clear them and the report says how many more it needs

#### Scenario: A repo-and-kind class

- **GIVEN** the class `app/unit-test`, which no `review.classes` entry names, with a record that clears both gates
- **WHEN** the gates are checked
- **THEN** it is shown with its figures and marked as not nameable

### Requirement: `abk review report` and `abk status` report the record

`abk review report` SHALL be a new read-only subcommand that prints, for each class, its samples, its clean-merge rate, its agreement
rate with its own sample count, the records excluded for having no brief, and whether it clears the gates and so may be added to
`review.auto_land.classes`. `abk status` SHALL print one line per class that clears the gates when review is enabled. Neither SHALL
edit abk.yaml, a verdict record or a unit.

#### Scenario: The report

- **GIVEN** a named class that clears the gates and another that does not
- **WHEN** `abk review report` runs
- **THEN** both are listed with samples and rates, and the first is said to clear the gates and may be added to `review.auto_land.classes`

#### Scenario: Nothing recorded

- **GIVEN** no verdict records
- **WHEN** `abk review report` runs
- **THEN** it says there is nothing to report

#### Scenario: Read-only

- **WHEN** the report runs
- **THEN** abk.yaml, the verdict records and the units are unchanged

### Requirement: The verdict's history floor reads the recorded history

The verdict's history floor SHALL hold a unit's class at `light` when the class has fewer samples than `min_samples` or a clean-merge
rate below `min_clean_rate`, computed over included records only, and SHALL raise nothing otherwise. A class with no records SHALL be
held at `light` as before. The floor SHALL use the same computation as the report.

#### Scenario: A proven class

- **GIVEN** a class that clears the gates and a unit of it whose every other floor is `auto`
- **WHEN** its verdict is computed
- **THEN** its tier is `auto` and its evidence tier is `auto`

#### Scenario: An unproven class

- **GIVEN** a class with 3 included samples
- **WHEN** a unit's verdict is computed
- **THEN** its tier is `light` and the reason says the class has too few samples

#### Scenario: Records without the brief

- **GIVEN** a class with 30 clean records, all with `brief` false
- **WHEN** a unit's verdict is computed
- **THEN** the class has no samples and the tier is `light`

### Requirement: Outcomes and agreement are counted

abk SHALL count each outcome as a unit reaches it, by outcome, tier and class, and SHALL count, for each merged unit whose evidence
tier was `auto`, whether a person accepted it as it stood, by class. No count SHALL carry a unit id, and both SHALL be listed in the
metric catalogue.

#### Scenario: A unit merges clean

- **WHEN** a unit's outcome becomes `clean`
- **THEN** the outcome counter increases by one with its outcome, tier and class

#### Scenario: A revert later

- **GIVEN** a unit counted `clean`
- **WHEN** its outcome becomes `reverted`
- **THEN** the counter increases by one for `reverted` and the earlier count is not removed
