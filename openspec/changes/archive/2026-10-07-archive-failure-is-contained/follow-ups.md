## From `archive-failure-is-contained/1`

- `_not_archived_reason` in src/agent_build_kit/cli/pipeline.py works out the reason again after the archive has run, and it repeats the order of checks in `archive_ready_changes`. If `archive_ready_changes` returned or logged its own skip reason for each change, the two could not drift apart. It also imports the private `_already_archived` from the archive module. That import was already there before this change, but a public name for it would be cleaner.
