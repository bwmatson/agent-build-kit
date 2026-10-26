## ADDED Requirements

### Requirement: Issue and pull-request references are scrubbed with the home paths

`abk scrub-store` SHALL also find, count and replace issue and pull-request references in the stored text fields (a repository name, a hash sign and a number, such as `example/app#15`), replacing each with `<ref>`; the dry run SHALL count them beside the home paths without printing the text, and a second `--apply` SHALL find nothing. The text pass of `abk planning split --scrub` SHALL replace them too. The pattern SHALL be defined once and shared with the structural leak test.

#### Scenario: A note with a reference

- **GIVEN** a record whose history note holds `<redacted>/app#15 can't be closed`
- **WHEN** `abk scrub-store --apply` runs on a paused pipeline
- **THEN** the note reads `<redacted>/<ref> can't be closed`, no other field changes, and a second run writes nothing

#### Scenario: A split scrubs a reference

- **GIVEN** a moved record whose feedback holds `example/app#15`
- **WHEN** the split runs with `--scrub`
- **THEN** the moved record holds `<ref>` and the dry run counts it among the substitutions
