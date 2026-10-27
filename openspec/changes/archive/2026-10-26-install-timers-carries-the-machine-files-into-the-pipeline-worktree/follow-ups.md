## From `install-timers-carries-the-machine-files-into-the-pipeline-worktree/2`

- tests/docs/test_machine_files_documented.py:18 — `text_of(path)` is a local one-liner that wraps `squashed(path.read_text(...))`, and it has no type annotation on `path`.
