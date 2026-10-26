# external-text-contract-tests

Where the pipeline must read another tool's words (git, the agent CLIs, pytest), the
matching lives in one adapter per tool, prefers the tool's structured output where it has
one, and is tested against messages recorded from the real tool, so a change in the
tool's wording fails a test and not a run.
