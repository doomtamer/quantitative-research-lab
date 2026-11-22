"""Verify a bounded E005 snapshot. Historical execution requires an independent verifier."""

import argparse
import csv
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

from quantlab.research.e005_backtest import DailyClose, MarketHour, Period, run_suite
from quantlab.research.e005_report import write_report
from quantlab.research.pipeline import scoped_path
from scripts.e005_authorization import freeze, require_independent_authorization, verify_frozen_request
from scripts.e005_snapshot import (
    COLUMNS, CUTOFF, DATA, ENDPOINT, EXPERIMENT, PROTOCOL_SHA256, ROOT, SPANS, check_protocol, check_values, pages,
)


RUNS = Path("reports/research_pipeline", EXPERIMENT)


def read_checked(path, digest):
    data = path.read_bytes()
    if sha256(data).hexdigest() != digest:
        raise ValueError(f"SHA-256 mismatch for {path.name}.")
    return data


def validate_rows(data, span):
    reader = csv.DictReader(StringIO(data.decode()))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise ValueError("Unexpected E005 CSV header.")
    output = []
    for expected, row in zip(span.schedule(), reader, strict=True):
        opened = datetime.fromisoformat(row["open_time_utc"])
        closed = datetime.fromisoformat(row["close_time_utc"])
        if (None in row or opened.utcoffset() != timedelta(0) or closed.utcoffset() != timedelta(0)
                or opened != expected or closed != opened + span.delta - timedelta(milliseconds=1)
                or closed >= CUTOFF):
            raise ValueError(f"Invalid, missing or out-of-scope candle in {span.name}.")
        check_values([row[key] for key in COLUMNS[2:]])
        output.append((opened, row))
    return output


def validate_provenance(requests, span):
    for expected, request in zip(pages(span), requests, strict=True):
        started = datetime.fromisoformat(request["started_utc"])
        received = datetime.fromisoformat(request["received_utc"])
        if (request["params"] != expected or request["row_count"] != expected["limit"]
                or not re.fullmatch(r"[0-9a-f]{64}", request["response_sha256"])
                or started.utcoffset() != timedelta(0) or received.utcoffset() != timedelta(0) or started > received):
            raise ValueError(f"Invalid request provenance for {span.name}.")


def verify_snapshot(root, snapshot_id, manifest_digest):
    if not re.fullmatch(r"[0-9a-f]{32}", snapshot_id) or not re.fullmatch(r"[0-9a-f]{64}", manifest_digest):
        raise ValueError("Expected a registered snapshot ID and lowercase manifest SHA-256.")
    relative = DATA / snapshot_id
    path = scoped_path(root, relative / "snapshot_manifest.json")
    manifest = json.loads(read_checked(path, manifest_digest))
    if (
        manifest.get("experiment_id") != EXPERIMENT
        or manifest.get("protocol_sha256") != PROTOCOL_SHA256
        or manifest.get("scope") != "development_and_validation_only"
        or manifest.get("exclusive_cutoff_utc") != CUTOFF.isoformat()
        or manifest.get("endpoint") != ENDPOINT or manifest.get("symbol") != "BTCUSDT"
        or manifest.get("complete") is not True
        or manifest.get("funding") != "funding_excluded"
        or manifest.get("equity_prices") != "traded_open_proxy"
        or manifest.get("historical_signal_availability_verified") is not False
        or set(manifest.get("inputs", {})) != {span.name for span in SPANS}
    ):
        raise ValueError("Manifest does not describe the complete authorized E005 data scope.")
    verified = {}
    for span in SPANS:
        item = manifest["inputs"][span.name]
        filename = f"{span.name}.csv"
        expected = len(span.schedule())
        if (item.get("file") != filename or item.get("interval") != span.interval
                or item.get("expected_start_utc") != span.start.isoformat()
                or item.get("exclusive_end_utc") != span.end.isoformat()
                or item.get("expected") != expected or item.get("verified") != expected
                or item.get("missing_utc") != [] or item.get("duplicates") != 0 or item.get("invalid_rows") != 0):
            raise ValueError(f"Unverified coverage for {span.name}.")
        validate_provenance(item["requests"], span)
        data = read_checked(scoped_path(root, relative / filename), item["sha256"])
        verified[span.name] = validate_rows(data, span)
    return verified


def _run_verified_inputs(root, verified, snapshot_id, manifest_digest, code_digest, authorization):
    """Write reports for the window validated by the independent entry point."""
    output = scoped_path(root, RUNS / uuid4().hex, directory=True)
    output.mkdir(parents=True, exist_ok=False)
    with (output / "ATTEMPT_STARTED.json").open("x", encoding="utf-8") as stream:
        json.dump({"authorization": authorization, "protocol_sha256": PROTOCOL_SHA256,
                   "snapshot_id": snapshot_id, "manifest_sha256": manifest_digest, "code_sha256": code_digest,
                   "scope": "development_and_validation_only",
                   "started_at_utc": datetime.now(timezone.utc).isoformat(),
                   "signal_availability": {"basis": "simulation_assumption",
                                           "assumed_time_utc": "00:59:59", "historically_verified": False},
                   "python_version": sys.version,
                   "funding": "funding_excluded", "execution": "traded_open_proxy"}, stream, indent=2)
    for span in SPANS[1:]:
        # Only context needed by this period is handed to the strategy.
        last_execution = (span.end - span.delta).date()
        daily = [
            DailyClose(at.date(), float(row["close"]), at + timedelta(days=1, minutes=59, seconds=59),
                       "simulation_assumption")
            for at, row in verified["daily"]
            if span.start.date() - timedelta(days=200) <= at.date() < last_execution
        ]
        hours = [MarketHour(at, float(row["open"])) for at, row in verified[span.name]]
        reports = run_suite(Period(hours[0].at, hours[-1].at), hours, daily)
        write_report(output / span.name, reports, period_name=span.name)
    with (output / "COMPLETED").open("x", encoding="utf-8") as stream:
        stream.write(datetime.now(timezone.utc).isoformat() + "\n")
    return output


def main(argv=None, *, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "freeze", "authorize", "run"))
    parser.add_argument("snapshot_id")
    parser.add_argument("manifest_sha256")
    parser.add_argument("--code-sha256")
    parser.add_argument("--approval-run-id")
    args = parser.parse_args(argv)
    try:
        check_protocol(root)
        if args.command == "freeze":
            print(json.dumps(freeze(root, args.snapshot_id, args.manifest_sha256)))
            return 0
        if args.command in {"authorize", "run"}:
            if args.code_sha256 is None:
                raise PermissionError("Run requires the exact frozen --code-sha256.")
            request = verify_frozen_request(root, args.snapshot_id, args.manifest_sha256, args.code_sha256)
            authorization = require_independent_authorization(request, args.approval_run_id)
            if args.command == "authorize":
                print(json.dumps(authorization))
                return 0
        verified = verify_snapshot(root, args.snapshot_id, args.manifest_sha256)
        if args.command == "run":
            output = _run_verified_inputs(root, verified, args.snapshot_id, args.manifest_sha256,
                                          args.code_sha256, authorization)
            print(output.relative_to(root))
        else:
            print(json.dumps({"verified_rows": {name: len(rows) for name, rows in verified.items()},
                              "authorization": "unverified", "execution_allowed": False}))
    except (OSError, ValueError, ArithmeticError, KeyError, TypeError) as error:
        print(f"E005: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
