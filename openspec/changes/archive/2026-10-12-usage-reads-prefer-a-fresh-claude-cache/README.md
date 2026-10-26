# usage-reads-prefer-a-fresh-claude-cache

Before the guard asks the usage endpoint, it reads Claude Code's own usage cache (`~/.claude.json`) and uses it when its block was fetched
within the cache time, describes no window that has reset, and is fresher than the guard's own kept reading. When a person works
interactively that file is refreshed by their own use, so the guard sees consumption the pipeline cannot, without a call that the
endpoint may refuse. The reading is labelled (`claude.json, 6m old`), recorded as its own outcome and counted apart from the cache in
the call-rate line. A setting, `usage_claude_cache_minutes`, sets the window and turns the step off at 0. It extends
`usage-read-on-decision` and builds after `a-refused-usage-read-with-headroom-does-not-pause`.
