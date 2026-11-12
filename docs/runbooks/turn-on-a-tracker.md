# Turn on a work tracker for a repo

A person's runbook: a builder cannot edit `abk.yaml`. Do it while no unit of the repo is
running, because the config guard fails a unit whose `abk.yaml` changes mid-run. The
configuration is described in `docs/trackers.md`.

1. Choose the target and the board's shape: the `levels` (for example `[change, group]` on a
   Basic board), the `types` for each, the provider block with its connection settings and
   `states`, and `epic` and `pr_links` when wanted. Validate the board's process template,
   type names and states first.
2. Create the credential and set the environment variable that holds it. Name the variable
   with `token_env` if it is not the forge's.
3. Add the section to the repo's entry in `abk.yaml`:

   ```yaml
   tracker:
     kind: azure_devops
     levels: [change, group]
     azure_devops:
       organization: example-org
       project: Example Project
       team: Example Team
       area_path: Example Project\Example Team
       iteration_path: Example Project\Sprint 1
       types:
         change: Issue
         group: Task
   ```

4. Run `abk doctor`. It reports the section's errors by key and whether the credential works.
5. Run `abk tracker sync --dry-run` and read the creates it lists. It writes nothing.
6. Let the tick do the rest. Each pass creates up to `create_cap` items until the backfill is
   done; `abk tracker status` shows what remains.

To adopt an item a person made, use `abk tracker link`; to record a change's manual parent,
`abk tracker link <change> --epic`. To turn it off, remove the section: ids are kept.
