## From `pr-description-says-why/1`

- src/agent_build_kit/pipeline/pr_body.py:298 — `_once_each` pairs a bare follow-up with a located optional finding by file name alone. A distinct bare point about a file that an optional finding locates is therefore left out of the description, though it stays in follow-ups.md. Pairing on overlapping wording as well as the file would stop that over-match.
- docs/architecture.md:438 — the parenthetical "(in the body only, the follow-ups file keeps every point; a bare point … is left out of the body; …)" packs three clauses into one aside. Splitting it into its own sentence, e.g. "The follow-ups file keeps every point; only the body leaves out a bare point that names a file an optional finding locates", would read more easily.

## From `pr-description-says-why/2`

- tests/pipeline/test_review_description.py:570 — When an approval's description is empty or malformed, the earlier stored description is kept and still shown. The spec's malformed-description scenario says the goal alone is shown.
- tests/pipeline/test_review_description.py:631 — Task 2.4 asks the prompt to cost no extra model call. The test checks only that the prompt asks for a description from the diff. It does not check the 'rides in the same reply; do not run anything extra' wording.
- docs/architecture.md:337 — The reflowed paragraph leaves one line ('candidate is re-checked before it is reported. Each finding carries a file, an optional line, a summary, a') much longer than the lines around it.
