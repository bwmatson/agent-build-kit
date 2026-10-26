# planning-content-follows-the-public-rule

The build tool's checkout is public and its rule forbids any text that names an installation: a consumer's repo name, owner, home path or
agent command. A planning repo kept inside that checkout would hold exactly such text in its specs, its `abk.yaml` and its stored unit
records. This change makes the rule checkable on that content. `abk scrub-check` stops flagging its own root, takes its terms from the
installation's facts plus a local list, and the structural leak test also reads `openspec/` and `abk.yaml`. Consumer facts of a tracked `abk.yaml`
live in two ignored places that sit side by side: single values in `.env`, read through `from: env-file` entries, and structured per-user
configuration in an `abk.local.yaml` that the loader merges. `abk doctor` warns when a tracked `abk.yaml` names a path outside the repo, a
home path or another owner's slug. A store pass rewrites home paths in stored feedback and history text.
