## From `command-output-to-files/1`

- command_policy._expand_word: expand `$ABK_OUT` one shell piece at a time, flushing at every quote boundary. Then a variable name split across quotes, such as `"$ABK"_OUT/y`, is refused, not read as the scratch folder. This only hardens the rule against a deliberate spelling; no honest redirect is misjudged today.
- src/agent_build_kit/pipeline/command_policy.py:390 — _expand_word gathers the unquoted and double-quoted pieces into one `plain` buffer and only then matches `$ABK_OUT`. A variable name split across a quote boundary is therefore read as `$ABK_OUT`, but the shell never reads it that way.
