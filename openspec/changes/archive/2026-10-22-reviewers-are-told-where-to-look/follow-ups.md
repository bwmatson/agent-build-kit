## From `reviewers-are-told-where-to-look/2`

- A unit with more than five drivers: `_drivers_lead` cuts the focus list to five but drops every driver from `skippable`. A driver past the cap therefore ends up in neither list. This does not break the spec (no place is in both lists), but a person might expect the cut-off drivers to be visible somewhere.

## From `reviewers-are-told-where-to-look/6`

- docs/unit-graph.md:355 — The `tests` row (and the matching sentence in docs/architecture.md:466) says a stubbed build's commit body holds the change's Why sentence and the group's "Done when". It does not mention the fixed sentence about what the commit holds, which still opens the body. It also does not say that a build that is not stubbed now carries a body too, built from every group's goal.
