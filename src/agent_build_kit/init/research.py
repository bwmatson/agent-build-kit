"""The research step of `abk init`: a per-language recommendation document.

The framework ships a seed for the languages it knows
(`recommendations/<language>.md`). A seed is a starting position written on
one day; the proposals for a repo are written from a document a model with
web access has checked against current practice on the day init runs —
each item kept, amended or dropped with a source, and gaps filled. For a
language with no seed the model produces a document in the same structure.

The model reads and searches only (`Read Grep Glob WebSearch WebFetch`);
the output is its text, written here with a dated header, and a Sources
section appended if it left one out.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from agent_build_kit.init.claude_call import RunClaude, runtime_for, succeeded
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.base import AgentRuntime

ALLOWED_TOOLS = "Read Grep Glob WebSearch WebFetch"

SECTIONS = (
    "Formatting",
    "Linting",
    "Types",
    "Test layout & tiers",
    "Packaging & workspaces",
    "Configuration & types conventions",
    "Pre-commit",
    "CI",
)

_STRUCTURE = (
    "The document has one `## <section>` per section, in this order: "
    + ", ".join(SECTIONS)
    + ". Under each, every item states the rule, the tool and its version floor, "
    "the rationale, and how to verify a repo follows it. It ends with a "
    "`## Sources` section listing every page consulted, with its URL."
)

PROMPT_WITH_SEED = """\
Below is a set of tooling recommendations for {language} repos, written as a \
seed. Validate each item against current practice as of {today}: keep, amend \
or drop it, saying which and citing a source for anything amended or dropped. \
Add what is missing — a tool that has become standard, a version floor that \
has moved, a practice the seed does not cover. Settle every item marked "to be \
decided by research" with a choice and the reason. Keep this structure.

{structure}

Respond with the finished document only, as Markdown, starting at its first \
`##` section — no preamble, no title line.

Seed:

{seed}
"""

PROMPT_WITHOUT_SEED = """\
Produce a set of tooling recommendations for {language} repos, validated \
against current practice as of {today}, with a source for every tool and \
version floor. Produce a set with the same structure as the framework's \
other languages:

{structure}

Respond with the finished document only, as Markdown, starting at its first \
`##` section — no preamble, no title line.
"""


def build_prompt(language: str, *, built_in: str | None, today: date) -> str:
    if built_in is None:
        return PROMPT_WITHOUT_SEED.format(
            language=language, today=today.isoformat(), structure=_STRUCTURE
        )
    return PROMPT_WITH_SEED.format(
        language=language, today=today.isoformat(), structure=_STRUCTURE, seed=built_in
    )


def _has_sources(text: str) -> bool:
    return any(
        line.strip().lstrip("#").strip().lower() == "sources"
        for line in text.splitlines()
        if line.startswith("#")
    )


def render(language: str, body: str, *, today: date, seeded: bool) -> str:
    origin = (
        "from the framework's built-in seed, validated"
        if seeded
        else "with no built-in seed for this language, researched"
    )
    header = (
        f"# {language.capitalize()}: tooling recommendations\n\n"
        f"Written by `abk init` on {today.isoformat()} {origin} against current "
        "practice by a model with web access. Each repo's proposals are written "
        "from this file; edit it where a rule does not fit this workspace, and "
        "re-run the research to refresh it.\n\n"
    )
    body = body.strip() + "\n"
    if not _has_sources(body):
        body += (
            "\n## Sources\n\nThe model did not list its sources. Treat every version "
            "floor above as unverified until one is added here.\n"
        )
    return header + body


def research(
    language: str,
    *,
    built_in: str | None,
    output: Path,
    run_claude: RunClaude | None = None,
    today: date | None = None,
    runtime: AgentRuntime | None = None,
) -> Path:
    """Write `output` (`docs/recommendations/<language>.md`) and return it."""
    day = today or date.today()
    request = AgentRequest(
        prompt=build_prompt(language, built_in=built_in, today=day),
        allowed_tools=ALLOWED_TOOLS,
        permission_mode="allowed_tools_only",
    )
    text = succeeded(runtime_for(run_claude, runtime).run(request))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(language, text, today=day, seeded=built_in is not None))
    return output
