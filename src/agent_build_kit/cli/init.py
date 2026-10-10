"""`abk init`: a planning repo for a set of checkouts, plus `abk install-skills`
and `abk install-timers`.

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
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from agent_build_kit import config as config_module
from agent_build_kit import openspec, runtimes, skills, timers
from agent_build_kit.config import CONFIG_FILENAME, ConfigError, WorkspaceConfig, dump
from agent_build_kit.init.claude_call import RunClaude
from agent_build_kit.init.detect import RepoDetection, detect_repo, resolve_consumes
from agent_build_kit.init.propose import Kind, ProposeError, change_name, propose
from agent_build_kit.init.research import research
from agent_build_kit.init.scaffold import (
    RULES_CHANGES,
    RULES_VERSION,
    ConventionResult,
    ScaffoldError,
    draft_config,
    fill_missing_environment,
    update_rules,
    write_code_repo_conventions,
    write_planning_repo,
)
from agent_build_kit.installation import Installation, load_config
from agent_build_kit.runtimes import AgentRuntime, PolicyReport, policy_check

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


def pr_bases(identity) -> list[str]:
    """Which branch this repo's pull requests target, asked of its own host.

    `origin/HEAD` is a pointer somebody set once, so a repo that moved its
    integration branch still answers the old one — and every unit would be
    built where the work is not. What the host says about real pull requests
    is the evidence; a host that cannot be reached simply says nothing, and
    `origin/HEAD` stands.
    """
    from agent_build_kit import forges

    forge = forges.get(identity.forge)
    return [pull.base for pull in forge.list_prs(identity)]


def _detect_all(paths: list[Path]) -> dict[str, RepoDetection]:
    detections: dict[str, RepoDetection] = {}
    for path in paths:
        if not path.expanduser().is_dir():
            raise InitError(f"{path} is not a directory")
        detection = detect_repo(path, pr_bases=pr_bases)
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
        "  .env.example, CLAUDE.md, .claude/skills/ (3 skills)",
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


_PLANNED = {
    "block": "write convention block",
    "changelog": "create changelog",
    "gitattributes": "add union merge rule",
}


def _convention_lines(
    workspace: WorkspaceConfig, results: list[ConventionResult], *, planned: bool
) -> list[str]:
    """One line per repo and action: what a dry run would do, or what a run did."""
    lines = []
    for r in results:
        root = workspace.repos[r.repo].path.expanduser()
        name = f"{r.repo}/{r.path.relative_to(root).as_posix()}"
        if r.result == "unchanged":
            what = "already current"
        elif r.result == "skipped":
            what = f"skipped: {r.note}"
        elif planned:
            what = _PLANNED[r.action]
        else:
            what = r.result
        lines.append(f"  {name}: {what}")
    return lines


def _conventions_config(
    planning: Path, drafted: WorkspaceConfig, args: argparse.Namespace
) -> WorkspaceConfig:
    """The config the code repos are written by: the planning repo's abk.yaml where
    it stands (a kept file may turn a repo's changelog off), else the drafted one."""
    path = planning / CONFIG_FILENAME
    if not path.is_file() or (args.dry_run and args.force):
        return drafted
    try:
        return load_config(path)
    except ConfigError as error:
        print(f"abk init: {error}; using the drafted config for the code repos", file=sys.stderr)
        return drafted


def _policy(
    runtime: AgentRuntime, planning: Path, *, cache: Path, fresh: bool = False
) -> PolicyReport | None:
    """The runtime's policy answer, or None when it could not be had: said,
    never kept, and init carries on without it."""
    try:
        return policy_check.checked(runtime, planning, cache=cache, fresh=fresh)
    except Exception as error:  # noqa: BLE001 - whatever the runtime raised is the finding
        print(
            f"abk init: runtime {runtime.name} policy not checked: "
            f"{type(error).__name__}: {error} (`abk doctor` checks it again)",
            file=sys.stderr,
        )
        return None


def _check_runtime_policy(planning: Path, *, prompts: bool) -> None:
    """Report what the selected runtime does not refuse, and offer the
    installation's fix: run only once the operator agrees, then checked again.
    An installation's own command is never run unasked, so `--yes` only
    prints it."""
    path = planning / CONFIG_FILENAME
    try:
        loaded = load_config(path)
        inst = Installation(loaded, planning)
    except ConfigError as error:
        print(f"abk init: runtime not checked: {error}", file=sys.stderr)
        return
    name = config_module.runtime_name(loaded)
    runtime = runtimes.get(name)
    if not runtime.implemented:
        print(f"runtime {name} is not implemented yet; `abk doctor` says more")
        return
    cache = policy_check.cache_path(inst)
    report = _policy(runtime, planning, cache=cache)
    if report is None or report.ok:
        return
    missing = ", ".join(report.unenforced)
    print(f"runtime {name} does not refuse: {missing}")
    entry = config_module.runtime_entry(loaded)
    fix = policy_check.fix_for(name, entry, report)
    if not entry.policy_fix:
        print(f"  fix: {fix}")
        return
    if not prompts:
        print(f"  fix: run `{fix}` from {planning}")
        return
    if ask(f"run `{fix}` to enforce them? [y/N] ").strip().lower() not in ("y", "yes"):
        print(f"not run; still unenforced: {missing}")
        return
    result = (run_fix or subprocess.run)(
        entry.policy_fix, cwd=planning, capture_output=True, text=True, check=False
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode:
        print(
            f"abk init: `{fix}` exited {result.returncode}: {result.stderr.strip()}",
            file=sys.stderr,
        )
    after = _policy(runtime, planning, cache=cache, fresh=True)
    if after is None:
        return
    if after.ok:
        print(f"runtime {name} now refuses every forbidden class")
    else:
        print(f"still unenforced: {', '.join(after.unenforced)}")


def _update_rules(planning: Path) -> int:
    """`abk init --update-rules`: the rules version only, nothing else rewritten."""
    config_yaml = planning / "openspec" / "config.yaml"
    if not config_yaml.is_file():
        print(f"abk init: {config_yaml} does not exist", file=sys.stderr)
        return 2
    try:
        applied = update_rules(config_yaml)
    except ScaffoldError as error:
        print(f"abk init: {error}", file=sys.stderr)
        return 2
    if not applied:
        print(f"{config_yaml} is already at rules v{RULES_VERSION}")
        return 0
    for version in applied:
        for change in RULES_CHANGES.get(version, []):
            print(f"v{version}: {change}")
    print(f"{config_yaml} is now at rules v{RULES_VERSION}; review the diff and commit it")
    return 0


def cmd_init(args: argparse.Namespace, _inst: Installation | None) -> int:
    planning = Path(args.planning_dir).expanduser().resolve()
    if args.update_rules:
        return _update_rules(planning)
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
    # An abk.yaml already there is kept and only filled, never given the empty section.
    keeps = (planning / CONFIG_FILENAME).is_file() and not args.force
    if not keeps and config.environment is not None and not config.environment.sync:
        print(
            "environment: nothing recognised in the planning repo; set `environment.sync` "
            "and `environment.check` in abk.yaml by hand"
        )
    if args.dry_run:
        if keeps:
            print("# abk.yaml is kept; what would be filled in it:\n")
            fills = fill_missing_environment(planning / CONFIG_FILENAME, config, dry_run=True)
            for what, block in fills.items():
                print(f"would fill {what} in abk.yaml:\n{block}")
            if not fills:
                print("nothing to fill")
        else:
            print("# abk.yaml as it would be written:\n")
            print(dump(config))
        print("# what would be generated:")
        print("\n".join(_planned_work(planning, detections, args)))
        workspace = _conventions_config(planning, config, args)
        planned = write_code_repo_conventions(workspace, dry_run=True)
        print("code repos:")
        print("\n".join(_convention_lines(workspace, planned, planned=True)))
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
        for what in fill_missing_environment(planning / CONFIG_FILENAME, config):
            print(f"filled {what} in abk.yaml")

    workspace = _conventions_config(planning, config, args)
    done = write_code_repo_conventions(workspace)
    print("\n".join(_convention_lines(workspace, done, planned=False)))

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

    _check_runtime_policy(planning, prompts=not args.yes)

    print(
        "\nNext steps:\n"
        "  1. Review abk.yaml: fill each repo's `deploy.rules[].run` lists, `description` "
        "and `relationships`;\n     replace any `todo-owner/` slug.\n"
        "  2. Set a repo-local git identity in each checkout: "
        "`git config user.email <email>` (and user.name).\n"
        "  3. Log `gh` in for every GitHub owner in abk.yaml: `gh auth login`.\n"
        "  4. Copy .env.example to .env and fill what this machine needs.\n"
        "  5. Run `abk doctor`, then `abk install-timers`."
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


# --- install-timers ----------------------------------------------------------------


def cmd_install_timers(args: argparse.Namespace, inst: Installation | None) -> int:
    """Put this installation's systemd units on this machine, or take them off.

    Not written at init time: a unit carries an absolute `WorkingDirectory`, so
    one rendered into the planning repo names whoever ran init, and everyone who
    cloned that repo afterwards got units aimed at someone else's home
    directory. `systemctl --user enable` takes such a unit without complaint,
    because a unit naming a directory that is not there is still a valid unit.
    """
    if inst is None:
        print(
            "abk install-timers: no abk.yaml found; run this from a planning repo",
            file=sys.stderr,
        )
        return 2

    if args.remove:
        change = timers.remove(inst.root, dry_run=args.dry_run)
        for path in change.removed:
            print(f"{'would remove' if args.dry_run else 'removed'} {path}")
        if not change.removed:
            print(f"nothing installed for {inst.root}")
        return 0

    tools = timers.tool_dirs(inst)
    change = timers.install(inst.root, enable=args.enable, dry_run=args.dry_run, tool_dirs=tools)
    if tools:
        print(f"units' PATH also carries: {', '.join(tools)}")
    for tool in timers.needed_tools(inst):
        if shutil.which(tool) is None:
            print(f"warning: {tool} is not on this shell's PATH, so no unit can find it either")
    for path in change.written:
        print(f"{'would write' if args.dry_run else 'wrote'} {path}")
    for path in change.unchanged:
        print(f"unchanged {path}")
    for path in change.removed:
        print(f"{'would remove' if args.dry_run else 'removed'} outdated {path}")
    for path in change.refused:
        print(f"refused {path}: not written by agent-build-kit (no marker)")
    for path in change.taken:
        print(
            f"refused {path}: belongs to the installation at {timers.owner_of(path)}, whose "
            "directory has the same name as this one. Unit names come from that name, so "
            "give one of the two a different name"
        )

    if not args.dry_run and (change.written or change.unchanged):
        print(f"\nunits point at {inst.root}")
        if args.enable:
            print("timers enabled; `systemctl --user list-timers` shows when each next runs")
        else:
            print("nothing is scheduled: --no-enable was given, so enable them by hand")
    return 1 if change.refused or change.taken else 0


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
    init.add_argument(
        "--update-rules",
        action="store_true",
        help="bring openspec/config.yaml up to the framework's rules version, "
        "adding what newer versions added and nothing else",
    )
    init.add_argument("--dry-run", action="store_true", help="print the config and the plan")
    init.add_argument("--register-store", metavar="ID", help="register as an OpenSpec store")
    init.set_defaults(func=cmd_init, needs_installation=False)

    install = sub.add_parser(
        "install-skills", help="copy the abk skills into a repo's .claude/skills/"
    )
    install.add_argument("--repo", action="append", metavar="PATH", help="a checkout (repeatable)")
    install.add_argument("--user", action="store_true", help="the user-level skills directory")
    install.set_defaults(func=cmd_install_skills, needs_installation="optional")

    units = sub.add_parser(
        "install-timers", help="render this installation's systemd units for the user manager"
    )
    units.add_argument(
        "--no-enable",
        dest="enable",
        action="store_false",
        help="write the units without scheduling them",
    )
    units.add_argument(
        "--remove", action="store_true", help="stop, disable and delete this installation's units"
    )
    units.add_argument("--dry-run", action="store_true", help="print what would change")
    units.set_defaults(func=cmd_install_timers, needs_installation="optional")
