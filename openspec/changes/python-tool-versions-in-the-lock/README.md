# python-tool-versions-in-the-lock

The formatter, linter and type checker are pinned in the project's dependency
group, and so in `uv.lock`; the pre-commit hooks for them call the project's
copy. Versions of the Python tools have one owner, the lock, and the tools run
in the project's own environment instead of an isolated hook environment.
