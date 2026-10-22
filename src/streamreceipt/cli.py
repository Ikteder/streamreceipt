"""Command line entry points."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .benchmark import write_evidence
from .core import MAX_BYTES, audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="streamreceipt")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("audit", help="Audit a captured SSE transcript")
    check.add_argument("transcript", type=Path)
    check.add_argument("--provider", choices=("openai-chat", "anthropic-messages"), required=True)
    check.add_argument("--require-usage", action="store_true")
    check.add_argument("--json", type=Path, dest="json_path")
    bench = commands.add_parser("benchmark", help="Regenerate authored fixture evidence")
    bench.add_argument("--out", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    if args.command == "benchmark":
        report = write_evidence(args.out)
        print(
            json.dumps(
                {k: report[k] for k in ("cases", "streamreceipt_correct", "parse_only_correct")}
            )
        )
        return 0 if report["streamreceipt_correct"] == report["cases"] else 1
    try:
        if args.transcript.stat().st_size > MAX_BYTES:
            parser.error("transcript exceeds 1 MiB limit")
        source = args.transcript.read_text(encoding="utf-8")
        if args.json_path and (
            args.json_path.resolve() == args.transcript.resolve()
            or (args.json_path.exists() and args.json_path.samefile(args.transcript))
        ):
            parser.error("JSON output must differ from transcript input")
    except (OSError, UnicodeError) as exc:
        parser.error(f"cannot read transcript: {exc.__class__.__name__}")
    report = audit(source, args.provider, require_usage=args.require_usage)
    output = json.dumps(report, indent=2) + "\n"
    if args.json_path:
        try:
            args.json_path.parent.mkdir(parents=True, exist_ok=True)
            args.json_path.write_text(output, encoding="utf-8")
        except OSError as exc:
            parser.error(f"cannot write JSON report: {exc.__class__.__name__}")
    else:
        sys.stdout.write(output)
    return {"dispatch_allowed": 0, "inconclusive": 2, "blocked": 3}[report["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
