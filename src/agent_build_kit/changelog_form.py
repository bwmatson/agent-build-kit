"""The shape a changelog must have, as a list of what is wrong with it."""

import re

CONFLICT_MARKER = re.compile(r"^(<{7}|={7}|>{7})(\s|$)")
VERSION_HEADING = re.compile(r"^## (\d+(?:\.\d+)*)\b")


def changelog_problems(text: str, name: str = "CHANGELOG.md") -> list[str]:
    """Each way `text` breaks the changelog's form, one `<name> line N: ...` per problem.

    Empty when the form holds: no conflict marker, a blank line between
    bullets, no bullet repeated, every bullet under a `##` heading, and the
    headings in order (unreleased first, then versions descending).
    """
    problems: list[str] = []
    seen: set[str] = set()
    in_section = False
    last_version: tuple[int, ...] | None = None
    unreleased_seen = False
    last_heading = 0
    bullet: list[str] = []
    bullet_start = 0

    def close_bullet() -> None:
        if not bullet:
            return
        key = " ".join(" ".join(bullet).split())
        if key in seen:
            problems.append(f"{name} line {bullet_start}: bullet repeated")
        seen.add(key)
        bullet.clear()

    lines = text.splitlines()
    for number, line in enumerate(lines, start=1):
        if CONFLICT_MARKER.match(line):
            problems.append(f"{name} line {number}: conflict marker")
        if line.startswith("## "):
            close_bullet()
            in_section = True
            heading_line, last_heading = last_heading, number
            if line.strip() == "## Unreleased":
                if unreleased_seen or last_version is not None:
                    problems.append(
                        f"{name} line {number}: `## Unreleased` must come before "
                        f"line {heading_line}"
                    )
                unreleased_seen = True
                continue
            version = VERSION_HEADING.match(line)
            if version:
                parts = tuple(int(part) for part in version[1].split("."))
                if last_version is not None and parts >= last_version:
                    problems.append(
                        f"{name} line {number}: version heading out of order, "
                        f"after line {heading_line}"
                    )
                last_version = parts
            continue
        if line.startswith("- "):
            close_bullet()
            previous = lines[number - 2] if number > 1 else ""
            if not in_section:
                problems.append(f"{name} line {number}: bullet outside any `##` section")
            elif previous.strip() and not previous.startswith("##"):
                problems.append(f"{name} line {number}: bullet not separated by a blank line")
            elif number > 2 and not previous.strip() and not lines[number - 3].strip():
                problems.append(f"{name} line {number}: more than one blank line before bullet")
            bullet.append(line)
            bullet_start = number
        elif bullet and line.startswith("  "):
            bullet.append(line)
        else:
            close_bullet()
    close_bullet()
    return problems
