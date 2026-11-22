"""Acquire and audit the bounded E005 development and validation snapshot."""

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, build_opener
from uuid import uuid4

from quantlab.research.pipeline import scoped_path


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = "E005_trend_backtest"
DATA = Path("data/research", EXPERIMENT, "development")
PROTOCOL = Path("experiments", EXPERIMENT, "PROTOCOL.md")
PROTOCOL_SHA256 = "816fee84d30a33500b69361fffa754f9b557626ef474ff2b465366c255a5a827"
ENDPOINT = "https://fapi.binance.com/fapi/v1/klines"
CUTOFF = datetime(2024, 1, 1, tzinfo=timezone.utc)
MAX_RESPONSE_BYTES = 1_000_000
COLUMNS = ("open_time_utc", "close_time_utc", "open", "high", "low", "close", "volume")


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def milliseconds(value: datetime) -> int:
    return int(value.timestamp()) * 1_000 + value.microsecond // 1_000


@dataclass(frozen=True)
class Span:
    name: str
    interval: str
    start: datetime
    end: datetime

    @property
    def delta(self):
        return {"1d": timedelta(days=1), "1h": timedelta(hours=1)}[self.interval]

    def schedule(self):
        return [self.start + index * self.delta for index in range((self.end - self.start) // self.delta)]


SPANS = (
    Span("daily", "1d", instant("2019-12-14"), instant("2023-12-31")),
    Span("development", "1h", instant("2020-07-01T01:00"), instant("2023-01-01")),
    Span("validation", "1h", instant("2023-01-01T01:00"), CUTOFF),
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_protocol(root):
    path = scoped_path(root, PROTOCOL)
    if sha256(path.read_bytes()).hexdigest() != PROTOCOL_SHA256:
        raise ValueError("E005 protocol SHA-256 does not match the frozen v1.1 bytes.")


def pages(span):
    if span.start >= span.end or span.end > CUTOFF or (span.end - span.start) % span.delta:
        raise ValueError("Invalid E005 request span.")
    start = span.start
    while start < span.end:
        end = min(start + 720 * span.delta, span.end)
        yield {"symbol": "BTCUSDT", "interval": span.interval, "startTime": milliseconds(start),
               "endTime": milliseconds(end) - 1, "limit": (end - start) // span.delta}
        start = end


def fetch(opener, params):
    start, end = params["startTime"], params["endTime"]
    if params.get("symbol") != "BTCUSDT" or not any(
        params["interval"] == span.interval and milliseconds(span.start) <= start <= end < milliseconds(span.end)
        for span in SPANS
    ):
        raise ValueError("Refusing an E005 request at or beyond the final-test boundary.")
    with opener.open(f"{ENDPOINT}?{urlencode(params)}", timeout=30) as response:
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("Oversized response.")
    return data


def check_values(values):
    if any(not isinstance(value, str) or not 0 < len(value) <= 64 or "e" in value.lower() for value in values):
        raise ValueError("Invalid E005 decimal encoding.")
    opening, high, low, close, volume = map(Decimal, values)
    if (not all(value.is_finite() for value in (opening, high, low, close, volume))
            or not 0 < low <= min(opening, close) <= max(opening, close) <= high or volume < 0):
        raise ValueError("Inconsistent E005 OHLCV.")


def read_page(data, params, span, records):
    rows = json.loads(data)
    if not isinstance(rows, list) or len(rows) > params["limit"]:
        raise ValueError("Unexpected E005 kline page shape.")
    step = span.delta // timedelta(milliseconds=1)
    for row in rows:
        if not isinstance(row, list) or len(row) != 12:
            raise ValueError("Unexpected E005 kline row shape.")
        opened, closed = row[0], row[6]
        if (type(opened) is not int or type(closed) is not int or opened % step
                or closed != opened + step - 1
                or not params["startTime"] <= opened <= closed <= params["endTime"]
                or not milliseconds(span.start) <= opened <= closed < min(milliseconds(span.end), milliseconds(CUTOFF))):
            raise ValueError("Response contained a candle outside bounded E005 UTC scope.")
        timestamp = datetime.fromtimestamp(opened / 1_000, timezone.utc)
        if timestamp in records:
            raise ValueError(f"Duplicate E005 candle at {timestamp.isoformat()}.")
        if any(not isinstance(value, str) for value in row[1:6]):
            raise ValueError("Unexpected E005 price encoding.")
        check_values(row[1:6])
        records[timestamp] = row[1:6]
    return len(rows)


def store_span(directory, span, records, requests):
    filename = f"{span.name}.csv"
    text = StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerows(
        (at.isoformat(), (at + span.delta - timedelta(milliseconds=1)).isoformat(), *values)
        for at, values in sorted(records.items())
    )
    data = text.getvalue().encode()
    with (directory / filename).open("xb") as stream:
        stream.write(data)
    missing = [at.isoformat() for at in span.schedule() if at not in records]
    return {
        "file": filename, "sha256": sha256(data).hexdigest(), "interval": span.interval,
        "expected_start_utc": span.start.isoformat(), "exclusive_end_utc": span.end.isoformat(),
        "observed_from_utc": min(records).isoformat() if records else None,
        "observed_through_utc": max(records).isoformat() if records else None,
        "expected": len(span.schedule()), "verified": len(records), "missing_utc": missing,
        "duplicates": 0, "invalid_rows": 0, "requests": requests,
    }


def download(root=ROOT):
    check_protocol(root)
    directory = scoped_path(root, DATA / uuid4().hex, directory=True)
    # Create no output before all network responses have passed scope checks.
    opener = build_opener(NoRedirect())
    collections = {}
    for span in SPANS:
        records, requests = {}, []
        for params in pages(span):
            started = datetime.now(timezone.utc).isoformat()
            response = fetch(opener, params)
            received = datetime.now(timezone.utc).isoformat()
            count = read_page(response, params, span, records)
            requests.append({"params": params, "started_utc": started, "received_utc": received,
                             "row_count": count, "response_sha256": sha256(response).hexdigest()})
        collections[span.name] = (records, requests)

    directory.mkdir(parents=True, exist_ok=False)
    inputs = {span.name: store_span(directory, span, *collections[span.name]) for span in SPANS}
    manifest = {
        "experiment_id": EXPERIMENT, "protocol_sha256": PROTOCOL_SHA256,
        "scope": "development_and_validation_only", "exclusive_cutoff_utc": CUTOFF.isoformat(),
        "endpoint": ENDPOINT, "symbol": "BTCUSDT", "inputs": inputs,
        "downloader_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "complete": not any(item["missing_utc"] for item in inputs.values()),
        "funding": "funding_excluded", "equity_prices": "traded_open_proxy",
        "historical_signal_availability_verified": False,
        "limitations": [
            "Historical OHLCV timestamps do not prove final 1D candle availability before 01:00 UTC.",
            "Traded 1h opens do not establish attainable execution or point-in-time mark prices.",
            "Funding events and mark prices are not included. No independent historical settlement calendar was verified.",
        ],
    }
    path = directory / "snapshot_manifest.json"
    payload = (json.dumps(manifest, indent=2, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(payload)
    return {"snapshot_id": directory.name, "manifest_sha256": sha256(payload).hexdigest(),
            "complete": manifest["complete"], "inputs": inputs}


if __name__ == "__main__":
    try:
        result = download()
    except HTTPError as error:
        print(f"Binance request failed (HTTP {error.code}).", file=sys.stderr)
        sys.exit(2)
    except (OSError, ValueError, ArithmeticError) as error:
        print(f"E005 snapshot stopped: {error}", file=sys.stderr)
        sys.exit(2)
    result["inputs"] = {name: {key: value for key, value in summary.items() if key != "requests"}
                        for name, summary in result["inputs"].items()}
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["complete"] else 2)
