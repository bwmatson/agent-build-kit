## From `build-prompts-name-the-profiles-test-and-lint-commands/1`

- tests/config/test_agent_commands_config.py: the new unknown-profile test catches ConfigError and does nothing with it. It could instead assert the outcome the code now has: the file loads, the same as one without `agent_commands`. That would also catch a later change that quietly turns this case into a refusal.
