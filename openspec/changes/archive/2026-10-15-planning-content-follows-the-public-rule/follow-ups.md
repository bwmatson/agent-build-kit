## From `planning-content-follows-the-public-rule/3`

- `append_missing_lines` now lives in `pipeline/file_lock.py` because `atomic_write_text` is there, but it takes no lock. If the module gains more text-file helpers, a small `text_file` module would be a clearer home.

## From `planning-content-follows-the-public-rule/5`

- tests/cli/test_scrub_store_cmd.py:113 — `assert "2" in rows[0]` checks for the count as a bare substring of the whole row, so a '2' anywhere in that row would satisfy it.
