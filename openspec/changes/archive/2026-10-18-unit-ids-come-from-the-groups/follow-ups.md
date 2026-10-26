## From `unit-ids-come-from-the-groups/2`

- Put a note in the PR body, which the builder could not edit: id reuse now also covers a `planned` unit that has work (the restart-requeue case). This narrows the spec's 'no branch' condition for exact-group matching, so the change's delta spec should be brought in line.
- docs/architecture.md:128 — The id-reuse sentence still covers only unstarted stored units. It leaves out the case this rework added: a `planned` unit that kept its branch after `abk requeue --restart` also keeps its id when a plan unit has exactly its groups.
