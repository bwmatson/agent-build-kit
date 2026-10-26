# bare-abk-tags-says-what-to-pass

`abk tags` with no change name and no `--all` stops with a one-line usage message and exit status 2 instead of a
traceback, and a change name given together with `--all` is refused the same way.
