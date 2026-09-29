"""`abk init`: a planning repo for a set of checkouts, and `abk install-skills`.

Init is the one command that creates an installation rather than reading
one. It detects each repo, drafts abk.yaml, lays the planning repo out,
researches a recommendation document per language, and asks a model to
write each repo's first changes. Every step after the layout is skippable,
and a second run over an existing planning repo writes only what is missing.

The module attributes below are injection points: tests replace them so no
run here reaches the real OpenSpec CLI, the real `claude`, a terminal, or an
installation's own fix command.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from agent_build_kit import openspec, skills
from agent_build_kit.config import dump
from agent_build_kit.init.claude_call import RunClaude
from agent_build_kit.init.detect import RepoDetection, detect_repo, resolve_consumes
from agent_build_kit.init.propose import Kind, ProposeError, change_name, propose
from agent_build_kit.init.research import research
from agent_build_kit.init.scaffold import ScaffoldError, draft_config, write_planning_repo
from agent_build_kit.installation import Installation

RECOMMENDATIONS = Path(__file__).resolve().parent.parent / "recommendations"

# A language whose recommendations live under another's document.
LANGUAGE_ALIAS = {"typescript": "javascript"}

# --- injection points ---------------------------------------------------------------
ask: Callable[[str], str] = input
run_openspec: openspec.Run | None = None
run_claude: RunClaude | None = None
# Runs the installation's `runtimes.<name>.policy_fix`, once the operator agrees.
run_fix: Callable[..., subprocess.CompletedProcess] | None = None


class InitError(Exception):
    pass


def _parse_consumes(items: list[str] | None) -> dict[str, list[str]]:
    """`--consumes app:platform,other` -> {"app": ["platform", "other"]}."""
    overrides: dict[str, list[str]] = {}
    for item in items or []:
        consumer, sep, consumed = item.partition(":")
        if not sep or not consumer.strip():
            raise InitError(f"--consumes takes <repo>:<consumed>[,<consumed>], got {item!r}")
        overrides.setdefault(consumer.strip(), []).extend(
            name.strip() for name in consumed.split(",") if name.strip()
        )
    return overrides


def _prompt_for_repos() -> list[Path]:
    paths: list[Path] = []
    print("Enter the path of each repo to include, one per line (blank line to finish).")
    while True:
        answer = ask("repo path: ").strip()
        if not answer:
            return paths
        paths.append(Path(answer))


def _detect_all(paths: list[Path]) -> dict[str, RepoDetection]:
    detections: dict[str, RepoDetection] = {}
    for path in paths:
        if not path.expanduser().is_dir():
            raise InitError(f"{path} is not a directory")
        detection = detect_repo(path)
        if detection.name in detections:
            raise InitError(
                f"two repos are both named {detection.name!r} "
                f"({detections[detection.name].path} and {detection.path})"
            )
        detections[detection.name] = detection
    return resolve_consumes(detections)


def research_languages(detections: dict[str, RepoDetection]) -> list[str]:
    return sorted(
        {LANGUAGE_ALIAS.get(lang, lang) for d in detections.values() for lang in d.languages}
    )


def kinds_for(detection: RepoDetection) -> list[Kind]:
    return (
        ["testing-infrastructure", "code-standards"] if detection.has_code else ["code-standards"]
    )


def _recommendations_doc(planning: Path, detection: RepoDetection) -> Path:
    language = LANGUAGE_ALIAS.get(detection.languages[0], detection.languages[0])
    return planning / "docs" / "recommendations" / f"{language}.md"


def _tree_clean(planning: Path) -> bool:
    if not (planning / ".git").exists():
        return True
    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=planning, capture_output=True, text=True, check=False
    )
    return result.returncode == 0 and not result.stdout.strip()


def _commit(planning: Path, names: list[str]) -> str | None:
    """Commit everything; returns the reason it could not, if it could not."""
    add = subprocess.run(["git", "add", "-A"], cwd=planning, capture_output=True, text=True)
    if add.returncode:
        return add.stderr.strip()
    commit = subprocess.run(
        ["git", "commit", "-q", "-m", f"abk init: workspace {', '.join(names)}"],
        cwd=planning,
        capture_output=True,
        text=True,
        check=False,
    )
    return None if commit.returncode == 0 else (commit.stderr or commit.stdout).strip()


def _planned_work(
    planning: Path, detections: dict[str, RepoDetection], args: argparse.Namespace
) -> list[str]:
    lines = [f"planning repo: {planning}"]
    lines += [
        "  git init, openspec init, abk.yaml, openspec/config.yaml, runs/, .gitignore,",
        "  .env.example, CLAUDE.md, systemd/ (8 units), .claude/skills/ (3 skills)",
    ]
    if args.skip_research:
        lines.append("research: skipped")
    else:
        for language in research_languages(detections):
            seed = "built-in seed" if (RECOMMENDATIONS / f"{language}.md").exists() else "no seed"
            lines.append(f"research: docs/recommendations/{language}.md ({seed})")
    if args.skip_propose:
        lines.append("propose: skipped")
    else:
        for name, detection in detections.items():
            for kind in kinds_for(detection):
                lines.append(f"propose: openspec/changes/{change_name(name, kind)}/")
    return lines


def cmd_init(args: argparse.Namespace, _inst: Installation | None) -> int:
    planning = Path(args.planning_dir).expanduser().resolve()
    try:
        paths = [Path(p) for p in args.repo or []]
        if not paths and not args.yes:
            paths = _prompt_for_repos()
        detections = _detect_all(paths)
        config = draft_config(
            detections, planning_dir=planning, consumes_overrides=_parse_consumes(args.consumes)
        )
    except (InitError, ScaffoldError) as error:
        print(f"abk init: {error}", file=sys.stderr)
        return 2

    names = list(config.repos)
    if args.dry_run:
        print("# abk.yaml as it would be written:\n")
        print(dump(config))
        print("# what would be generated:")
        print("\n".join(_planned_work(planning, detections, args)))
        return 0

    clean_before = _tree_clean(planning)
    try:
        written = write_planning_repo(planning, config, run_openspec=run_openspec, force=args.force)
    except ScaffoldError as error:
        print(f"abk init: {error}", file=sys.stderr)
        return 1
    for path in written:
        print(f"wrote {path.relative_to(planning)}")
    if (planning / "abk.yaml") not in written:
        print("kept abk.yaml (use --force to overwrite)")

    if not args.skip_research:
        for language in research_languages(detections):
            output = planning / "docs" / "recommendations" / f"{language}.md"
            if output.exists() and not args.force:
                print(f"kept {output.relative_to(planning)}")
                continue
            seed = RECOMMENDATIONS / f"{language}.md"
            print(f"researching {language} recommendations…")
            research(
                language,
                built_in=seed.read_text() if seed.exists() else None,
                output=output,
                run_claude=run_claude,
            )
            print(f"wrote {output.relative_to(planning)}")

    failures: list[str] = []
    if not args.skip_propose:
        for name, detection in detections.items():
            if not detection.languages:
                print(f"{name}: no language detected, nothing to propose")
                continue
            for kind in kinds_for(detection):
                change = change_name(name, kind)
                if (planning / "openspec" / "changes" / change).exists() and not args.force:
                    print(f"kept openspec/changes/{change}/")
                    continue
                print(f"proposing {change}…")
                try:
                    propose(
                        name,
                        detection,
                        planning=planning,
                        recommendations=_recommendations_doc(planning, detection),
                        kind=kind,
                        run_claude=run_claude,
                        run_openspec=run_openspec,
                        repos=tuple(names),
                    )
                    print(f"wrote openspec/changes/{change}/")
                except ProposeError as error:
                    failures.append(change)
                    print(f"abk init: {error}", file=sys.stderr)

    if args.register_store:
        result = openspec.run(
            ["store", "register", "--id", args.register_store, "--yes", str(planning)],
            cwd=planning,
            run=run_openspec,
        )
        if result.returncode:
            print(f"abk init: store registration failed: {result.stderr.strip()}", file=sys.stderr)
        else:
            print(f"registered OpenSpec store {args.register_store}")

    if clean_before:
        reason = _commit(planning, names)
        if reason:
            print(f"not committed: {reason}")
        else:
            print(f"committed: abk init: workspace {', '.join(names)}")
    else:
        print("not committed: the planning repo had uncommitted changes before init ran")

    print(
        "\nNext steps:\n"
        "  1. Review abk.yaml: fill each repo's `deploy.rules[].run` lists, `description` "
        "and `relationships`;\n     replace any `todo-owner/` slug.\n"
        "  2. Set a repo-local git identity in each checkout: "
        "`git config user.email <email>` (and user.name).\n"
        "  3. Log `gh` in for every GitHub owner in abk.yaml: `gh auth login`.\n"
        "  4. Copy .env.example to .env and fill what this machine needs.\n"
        "  5. Run `abk doctor`, then install the timers from systemd/."
    )
    if failures:
        print(f"\n{len(failures)} change(s) need finishing by hand: {', '.join(failures)}")
    return 1 if failures else 0


# --- install-skills ----------------------------------------------------------------


def cmd_install_skills(args: argparse.Namespace, inst: Installation | None) -> int:
    targets: list[Path] = []
    if args.user:
        targets.append(Path.home() / ".claude" / "skills")
    targets += [Path(p).expanduser().resolve() / ".claude" / "skills" for p in args.repo or []]
    if not targets:
        if inst is None:
            print(
                "abk install-skills: no abk.yaml found; give --repo PATH or --user",
                file=sys.stderr,
            )
            return 2
        targets.append(inst.root / ".claude" / "skills")
        targets += [path / ".claude" / "skills" for path in inst.checkouts.values()]

    refused_any = False
    for target in targets:
        written, refused = skills.install(target)
        for path in written:
            print(f"wrote {path}")
        for path in refused:
            refused_any = True
            print(f"refused {path}: not written by agent-build-kit (no generatedBy header)")
    return 1 if refused_any else 0


def register(sub: argparse._SubParsersAction) -> None:
    init = sub.add_parser("init", help="create a planning repo for a set of checkouts")
    init.add_argument("planning_dir", nargs="?", default=".", help="the planning repo (default .)")
    init.add_argument("--repo", action="append", metavar="PATH", help="a checkout (repeatable)")
    init.add_argument(
        "--consumes",
        action="append",
        metavar="REPO:CONSUMED[,CONSUMED]",
        help="override what a repo consumes (repeatable)",
    )
    init.add_argument("--yes", action="store_true", help="no prompts")
    init.add_argument("--skip-research", action="store_true")
    init.add_argument("--skip-propose", action="store_true")
    init.add_argument("--force", action="store_true", help="overwrite abk.yaml and config.yaml")
    init.add_argument("--dry-run", action="store_true", help="print the config and the plan")
    init.add_argument("--register-store", metavar="ID", help="register as an OpenSpec store")
    init.set_defaults(func=cmd_init, needs_installation=False)

    install = sub.add_parser(
        "install-skills", help="copy the abk skills into a repo's .claude/skills/"
    )
    install.add_argument("--repo", action="append", metavar="PATH", help="a checkout (repeatable)")
    install.add_argument("--user", action="store_true", help="the user-level skills directory")
    install.set_defaults(func=cmd_install_skills, needs_installation="optional")
