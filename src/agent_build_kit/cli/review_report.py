"""`abk review report`: the rates and the gates of each class, read-only."""

from __future__ import annotations

import argparse
import sys

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import audit_record, spans
from agent_build_kit.pipeline.review_rates import ClassGate, recorded_gates
from agent_build_kit.pipeline.verdict_record import VERDICTS


def _rate(rate: float | None) -> str:
    return "none" if rate is None else f"{rate:.2f}"


def _line(name: str, gate: ClassGate) -> str:
    rates = gate.rates
    if not gate.nameable:
        verdict = "not nameable: no review.classes entry names it"
    elif gate.clears:
        verdict = "clears the gates, may be added to review.auto_land.classes"
    else:
        verdict = f"does not pass the gates, needs {gate.more_samples} more samples"
    return (
        f"{name}: {rates.samples} samples, clean-merge rate {_rate(rates.clean_rate)}, "
        f"agreement {_rate(rates.agreement)} of {rates.agreement_samples} samples, "
        f"{rates.excluded} excluded (no brief) — {verdict}"
    )


def cmd_review_report(args: argparse.Namespace, inst: Installation) -> int:
    gates = recorded_gates(
        inst.state_dir / VERDICTS, inst.config.review, inst.state_dir / audit_record.AUDITS
    )
    if not gates:
        print("nothing to report: no verdict records")
        return 0
    for name, gate in sorted(gates.items()):
        print(_line(name, gate))
    return 0


def cmd_review_audit(args: argparse.Namespace, inst: Installation) -> int:
    path = inst.state_dir / audit_record.AUDITS
    try:
        audit_record.record_result(path, unit=args.unit, result=args.result, at=spans.clock.now())
    except (audit_record.NotAwaitingAudit, audit_record.UnreadableAudits) as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 1
    print(f"{args.unit}: audit recorded {args.result}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("review", help="the review record")
    commands = parser.add_subparsers(dest="review_command", required=True)
    report = commands.add_parser(
        "report", help="print each class's rates and whether it clears the gates"
    )
    report.set_defaults(func=cmd_review_report)
    audit = commands.add_parser("audit", help="record the result of auditing a landed unit")
    audit.add_argument("unit")
    audit.add_argument("result", choices=("ok", "wrong"))
    audit.set_defaults(func=cmd_review_audit)
