"""The cost of changes that lasted, and the health thresholds, from the pipeline's state.

Read-only.

A merged change is `pending` (merged under 30 days ago), else `fixed` (a `late_failure` cause, a
`late-fix` pull request, or a `fix-*`/`hotfix-*` unit whose `needs` names one of its units and that
began within 30 days of the merge), else `reverted` (`reverts_merge` finds a revert on the trunk
within 30 days), else `unchecked` (no merge commit, no checkout, or the search failed), else
`trusted`. Cost is `build_report(group_by="change")`'s `measured.cost_usd`: live calls, archived
summaries and plan reviews, no estimates. Hot-fixes are under-counted: fix changes rarely carry a
`needs` entry.

Run it from a planning repo (it reads that installation's state through the kit installed there):
    uv run python <kit checkout>/scripts/trusted_change_cost.py \
        [--days 30] [--top 3] [--json out.json]
It stands in for `abk report --trusted` (change `cost-per-trusted-change-and-thresholds`),
which replaces it.
Writes nothing under runs/ and never calls the forge; it runs `git log` and `git rev-list`
on the checkouts.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.installation import load_installation
from agent_build_kit.pipeline.archive import is_ready_to_archive
from agent_build_kit.pipeline.carry import carried_commit
from agent_build_kit.pipeline.review_revert import reverts_merge
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.usage_report import _all_entries, _group_key, build_report

ORDER = ("pending", "fixed", "reverted", "unchecked", "trusted")
THRESHOLDS = {  # name: (limit, correction)
    "plan_review_share": (0.5, "outline far-out work (docs/runbooks/change-maturity.md)"),
    "cost_per_trusted_change": (0.25, "read the top changes by cost; split or outline them"),
    "unit_failure_rate": (0.25, "read the failures by cause; a recurring cause becomes a change"),
}


def stamp(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def merged_stamps(unit) -> list[datetime]:
    return [t for e in unit.history if e.get("state") == "merged" and (t := stamp(e.get("at")))]


def first_line(unit) -> str:
    notes = [str(e.get("note", "")) for e in unit.history if e.get("state") == "failed"]
    return (notes[-1].splitlines() or [""])[0][:100] if notes else ""


def revert_found(inst, unit, until: datetime, now: datetime) -> tuple[bool | None, str]:
    """reverts_merge bounded by `until` (the trunk is read as the last commit before it), and why
    None when no search was made."""
    merge = carried_commit(unit)
    if not merge:
        return None, "no merge commit"
    if unit.repo not in inst.checkouts:
        return None, "no checkout"
    checkout, trunk = inst.checkouts[unit.repo], inst.repo(unit.repo).default_branch
    if until < now:
        cut = subprocess.run(
            ["git", "rev-list", "-n1", "--first-parent", f"--before={until.isoformat()}", trunk],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=False,
        )
        if cut.returncode or not cut.stdout.strip():
            return None, "trunk not found"
        trunk = cut.stdout.strip()
    found = reverts_merge(
        checkout, trunk=trunk, merge_commit=merge, repo=inst.forge_of(unit.repo)[1], pr=unit.pr or 0
    )
    return found, "" if found is not None else "merge commit not in checkout"


def judge(
    inst, units, change: str, merged: datetime, now: datetime, days: int
) -> tuple[str, list[str]]:
    window = timedelta(days=days)
    if now - merged < window:
        return "pending", []
    mine = [u for u in units if u.carries(change)]
    ids = {u.id for u in mine}
    reasons = [
        f"{u.id}: late_failure"
        for u in mine
        if any(e.get("cause") == "late_failure" for e in u.history)
    ]
    reasons += [f"{u.id}: late-fix PR" for u in mine if any(p.role == "late-fix" for p in u.pulls)]
    for fix in units:
        if fix.change.startswith(("fix-", "hotfix-")) and fix.state not in ("retired", "unplanned"):
            began = stamp(fix.history[0].get("at")) if fix.history else now
            if ids & set(fix.needs) and began and began <= merged + window:
                reasons.append(f"{fix.id}: needs {sorted(ids & set(fix.needs))[0]}")
    if reasons:
        return "fixed", reasons
    unchecked, reverted = [], []
    for unit in (u for u in mine if u.state == "merged"):
        stamps = merged_stamps(unit)
        found, why = revert_found(inst, unit, max(stamps, default=merged) + window, now)
        if found:
            reverted.append(unit.id)
        elif found is None:
            unchecked.append(f"{unit.id}: {why}")
    if reverted:
        return "reverted", [f"{u}: revert on trunk" for u in reverted]
    return ("unchecked", unchecked) if unchecked else ("trusted", [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--days", type=int, default=30, help="trusted_days: the judging window and window length"
    )
    parser.add_argument(
        "--top", type=int, default=3, help="changes named when cost per trusted change breaches"
    )
    parser.add_argument("--json", type=Path, help="write the figures here")
    args = parser.parse_args()
    now, days = datetime.now(UTC), args.days
    inst = load_installation()
    units = UnitStore(inst.state_dir / "units.json").all()
    ledger = inst.state_dir / LEDGER_NAME
    cost = {r.key: r.measured.cost_usd for r in build_report(ledger, units, group_by="change").rows}

    names = {m.change for u in units for m in u.members()} | {u.change for u in units}
    changes = []
    for name in sorted(n for n in names if is_ready_to_archive(n, units)):
        stamps = [t for u in units if u.carries(name) for t in merged_stamps(u)]
        if not stamps:
            continue  # all units satisfied: no merge time, so no age
        verdict, reasons = judge(inst, units, name, max(stamps), now, days)
        changes.append(
            dict(
                change=name,
                verdict=verdict,
                reasons=reasons,
                merged_at=max(stamps).isoformat(),
                cost_usd=cost.get(name),
            )
        )
    per = {v: [c for c in changes if c["verdict"] == v] for v in ORDER}
    costed = lambda rows: [c["cost_usd"] for c in rows if c["cost_usd"] is not None]  # noqa: E731

    windows = defaultdict(list)  # trusted changes by 30-day window of age: 1 = (now-2d, now-d]
    for c in per["trusted"]:
        windows[int((now - datetime.fromisoformat(c["merged_at"])) / timedelta(days=days))].append(
            c
        )
    window_rows = [
        dict(
            window=k,
            trusted=len(v),
            costed=len(costed(v)),
            usd=sum(costed(v)),
            per_change=sum(costed(v)) / len(costed(v)) if costed(v) else None,
        )
        for k, v in sorted(windows.items())
    ]

    spend = defaultdict(lambda: [0.0, 0.0])  # day -> [plan, all]
    for e in _all_entries(ledger, units):
        usd = e.row.measured.cost_usd
        if usd and e.at:
            day = spend[_group_key(e, "day", {})]
            day[1] += usd
            day[0] += usd if e.role == "plan" else 0.0
    started = defaultdict(lambda: [0, 0, []])  # day -> [started, failed, failed units]
    for u in units:
        if u.started_at:
            row = started[u.started_at.date().isoformat()]
            row[0] += 1
            if any(e.get("state") == "failed" for e in u.history):
                row[1] += 1
                row[2].append(u)
    merged_day = defaultdict(list)
    for c in per["trusted"]:
        merged_day[c["merged_at"][:10]].append(c)

    def day_list(n: int) -> list[str]:
        return [(now - timedelta(days=i)).date().isoformat() for i in range(n)][::-1]

    daily = [
        dict(
            day=d,
            plan_usd=spend[d][0],
            all_usd=spend[d][1],
            plan_share=spend[d][0] / spend[d][1] if spend[d][1] else None,
            started=started[d][0],
            failed=started[d][1],
            failure_rate=started[d][1] / started[d][0] if started[d][0] else None,
            trusted_merged=len(merged_day[d]),
            trusted_usd=sum(costed(merged_day[d])),
        )
        for d in day_list(days)
    ]
    breaches, seen = [], {}
    limit, fix = THRESHOLDS["plan_review_share"]
    seen["plan_review_share"] = max(
        (d["plan_share"] for d in daily[-7:] if d["plan_share"] is not None), default=None
    )
    over = [d for d in daily[-7:] if d["plan_share"] is not None and d["plan_share"] > limit]
    if over:
        breaches.append(
            dict(
                name="plan_review_share",
                limit=limit,
                correction=fix,
                observed=max(d["plan_share"] for d in over),
                evidence=[
                    f"{d['day']}: plan {d['plan_usd']:.2f} of {d['all_usd']:.2f} USD" for d in over
                ],
            )
        )
    limit, fix = THRESHOLDS["cost_per_trusted_change"]
    latest, before = (next((w for w in window_rows if w["window"] == k), None) for k in (1, 2))
    if latest and before and latest["per_change"] and before["per_change"]:
        rise = seen["cost_per_trusted_change"] = latest["per_change"] / before["per_change"] - 1
        if rise > limit:
            top = sorted(
                (c for c in windows[1] if c["cost_usd"] is not None), key=lambda c: -c["cost_usd"]
            )
            breaches.append(
                dict(
                    name="cost_per_trusted_change",
                    limit=limit,
                    correction=fix,
                    observed=rise,
                    evidence=[f"{c['change']}: {c['cost_usd']:.2f} USD" for c in top[: args.top]],
                )
            )
    limit, fix = THRESHOLDS["unit_failure_rate"]
    week = daily[-7:]
    began, failed = sum(d["started"] for d in week), sum(d["failed"] for d in week)
    seen["unit_failure_rate"] = failed / began if began else None
    if began and failed / began > limit:
        evidence = [
            f"{u.id}: {u.cause} | {first_line(u)}" for d in week for u in started[d["day"]][2]
        ]
        breaches.append(
            dict(
                name="unit_failure_rate",
                limit=limit,
                correction=fix,
                observed=failed / began,
                evidence=evidence,
            )
        )

    print(
        f"{'verdict':10} {'changes':>7} {'costed':>6} {'USD':>9}"
        f"   (judged {now:%Y-%m-%d}, {days}-day windows)"
    )
    for v in ORDER:
        print(f"{v:10} {len(per[v]):7d} {len(costed(per[v])):6d} {sum(costed(per[v])):9.2f}")
    print("\nwindow (age)    trusted  costed        USD   per change")
    for w in window_rows[:4]:
        label = f"{w['window'] * days}-{(w['window'] + 1) * days} days ago"
        per_change = f"{w['per_change']:.2f}" if w["per_change"] is not None else "-"
        print(f"{label:15} {w['trusted']:7d} {w['costed']:7d} {w['usd']:10.2f} {per_change:>11}")
    week_plan, week_all = sum(d["plan_usd"] for d in week), sum(d["all_usd"] for d in week)
    print(
        f"\nlast 7 days: plan share {week_plan / week_all if week_all else 0:.0%}"
        f" of {week_all:.0f} USD;"
        f" units started {began}, failed {failed}"
    )
    print("\nthreshold                limit  observed  breach")
    for name, (limit, fix) in THRESHOLDS.items():
        hit = next((b for b in breaches if b["name"] == name), None)
        value = seen.get(name)
        print(
            f"{name:24} {limit:5.2f}  {'n/a' if value is None else format(value, '.2f'):>8}  "
            f"{'BREACH: ' + fix if hit else 'ok'}"
        )
        for line in hit["evidence"][:12] if hit else []:
            print(f"    {line}")
    print(
        "\nNote: hot-fixes are under-counted; fix units seldom carry a `needs` entry,"
        " so a trusted change"
        " may have been hot-fixed."
    )
    if args.json:
        args.json.write_text(
            json.dumps(
                dict(
                    now=now.isoformat(),
                    days=days,
                    verdicts={
                        v: dict(
                            changes=len(per[v]), costed=len(costed(per[v])), usd=sum(costed(per[v]))
                        )
                        for v in ORDER
                    },
                    windows=window_rows,
                    daily=daily,
                    observed=seen,
                    breaches=breaches,
                    changes=changes,
                    note="hot-fixes under-counted: only fix units with a needs entry are linked",
                ),
                indent=1,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
