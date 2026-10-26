## From `prompts-reach-the-agent-without-the-argument-size-limit/1`

- In `stream_run`, the stderr TemporaryFile is opened as `"w+"`, so it is read back with the locale's encoding while stdin and stdout are now UTF-8. On a host whose locale is not UTF-8, a non-ASCII byte in `claude`'s stderr could raise on `stderr.read()`. This was already there before this change. Opening it with `encoding="utf-8", errors="replace"` would make all three streams match.

## From `prompts-reach-the-agent-without-the-argument-size-limit/2`

- `omitted_line` in `pipeline/planner.py` always writes "units", even when there is only one ("1 merged or satisfied units of other changes ..."). The tests' `units?` regex would also accept the singular, so making it agree with the count is a one-line change.
