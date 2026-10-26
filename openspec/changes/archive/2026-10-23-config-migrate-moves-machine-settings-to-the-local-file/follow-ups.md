## From `config-migrate-moves-machine-settings-to-the-local-file/1`

- When this merges, `abk doctor`'s fix text tells people to run `abk config --migrate --include-defaults`. That flag does not exist yet, and `--migrate` does not move machine settings until the later units (groups 2-4) land. Order those units so the change is not left half-merged for long.

## From `config-migrate-moves-machine-settings-to-the-local-file/3`

- src/agent_build_kit/config_migrate_write.py:104 — The local file's staging mode is still worked out inline (`local.stat().st_mode if local_before is not None else mode`) even though `local_mode` now holds exactly that value, computed a few lines above.

## From `config-migrate-moves-machine-settings-to-the-local-file/2`

- src/agent_build_kit/config_migrate_machine.py:257 — The new `_ending` helper is used only for the tracked text. The local-text branch writes the same expression out inline: `("\r\n" if "\r\n" in own else "\n")`.

## From `config-migrate-moves-machine-settings-to-the-local-file/7`

- CHANGELOG.md:77 — The new bullet stands beside the `machine keys` bullet that unit 1 of this same change added, and that bullet already names `abk config --migrate` and `--include-defaults`. The convention is one change, one bullet.
- tests/test_config_migrate_ignore_preview.py:37 — `test_the_lines_a_text_lacks_are_added_once_after_a_missing_newline` tests `pipeline/file_lock.with_missing_lines`, but it sits in a file named for config_migrate_write, and the trailing `capsys.readouterr()` in the first test does nothing.

## From `config-migrate-moves-machine-settings-to-the-local-file/6`

- docs/configuration.md:72 — The paragraph just above the new one still lists only the older machine keys that doctor warns about. It leaves out a repo path outside the checkout, a deploy SSH key, the worktree root and a home-directory path in a verify.env entry, which the changelog bullet says the check now reports. The new sentence 'everything the check warns about' depends on that list, so it inherits the gap.
- tests/docs/test_machine_move_documented.py:14 — The local `section(text, heading, level)` helper is yet another copy of a heading-bounded section reader. Copies already exist in tests/docs/test_test_only_group_documented.py:22, tests/docs/test_collects_path_text.py:17 and tests/test_public_rule_documented.py:26, and tests/doc_text.py, the shared doc-test helper module, has none.
