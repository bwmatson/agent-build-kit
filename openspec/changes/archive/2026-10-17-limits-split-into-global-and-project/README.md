# limits-split-into-global-and-project

The `limits` block of abk.yaml mixes two kinds of setting. Three of them, `max_units_in_progress`, `max_concurrent_stacks` and
`max_concurrent_restacks`, are counted across every repo, so one backlog starves everything else: six failed units can hold six of nine
places and nothing else starts. This change makes them a limit of each project. The block becomes `global_limits` (with `limits:`
accepted for now as a deprecated alias), the three move into a new root block `project_limits` configured once and applied to each
project separately, a unit gets its project from a `[<repo>/<project>]` heading tag, units, build workers and restack lanes are counted
for each project, `abk status` names each full project, the graph page nests a subgraph for each project of a repo that has several, and
`abk config --migrate` moves an existing abk.yaml by text edit.
