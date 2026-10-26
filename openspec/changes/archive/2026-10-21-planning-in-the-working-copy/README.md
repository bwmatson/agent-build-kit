# planning-in-the-working-copy

A repository can be its own planning repo: `abk.yaml`, `openspec/`, `runs/` and the graph pages live in the repo the pipeline builds, so several
workspaces share one place for the specs, the configuration and the state. The pipeline's timers do not run in the checkout a person edits. They run in
a pipeline-owned worktree of the same repository, held at the default branch tip and synced (fetch, then a fast-forward of a detached HEAD, keeping
the pipeline's own tracked-state changes) before every tick and track, stopping with one logged reason when it cannot; the person's working copy is
never touched. A planning root that is a separate repository behaves exactly as before. The rest of the change makes the layout safe: verify and
planning commits are limited to the planning paths, unit worktrees cannot write them, `locate()` does not adopt a unit worktree's `abk.yaml`,
`planning.publish` says whether planning commits go straight to the default branch or to a branch and pull request, `abk init` has an in-repo mode,
and the repo's own hooks and CI do not treat spec-and-state commits as code.
