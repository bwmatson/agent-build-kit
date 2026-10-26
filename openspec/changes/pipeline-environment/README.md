# pipeline-environment

Keeps the environment the pipeline itself runs in up to date, by commands and file lists in configuration
rather than knowledge of any package manager, and gives a unit that fails because of that environment its own
cause, which holds its build slot and resumes by itself once the environment is healthy. Code repositories
can declare their own environment, synced in the unit's worktree when its inputs change.
