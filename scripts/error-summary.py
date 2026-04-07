#!/usr/bin/env python3
"""
error-summary.py — Daily error digest for CoreServices Lambdas

Reads from /aws/monitoring/central-lambda-errors (the EventBridge-backed
central error log written by eventable's handleLambda wrapper).

Usage:
    python3 scripts/error-summary.py              # today
    python3 scripts/error-summary.py 2026-04-06   # specific date

Output:
    Today's Errors (YYYY-MM-DD)

    1. functionName — N errors
       - Nx ErrorType: "message"
       - Nx ErrorType: "message"

    2. ...
"""

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict, Counter
from datetime import date


LOG_GROUP = "/aws/monitoring/central-lambda-errors"


# ── AWS helpers ──────────────────────────────────────────────────────────────

def aws(*args):
    """Run an AWS CLI command and return parsed JSON output."""
    # TODO: thread --region / --profile through here when cross-account support is needed.
    # Add: parser.add_argument("--region"), parser.add_argument("--profile") in main(),
    # then prepend ["--region", region, "--profile", profile] to the cmd list below.
    cmd = ["aws"] + list(args) + ["--output", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"aws {args[0]} failed (exit {result.returncode})")
    return json.loads(result.stdout)


def get_log_events(stream_name):
    """
    Fetch ALL events from a log stream, following nextForwardToken pagination.
    Returns list of raw event dicts with 'message' key.
    """
    events = []
    next_token = None

    while True:
        # Build kwargs fresh each iteration — avoids fragile index-based mutation
        extra = ["--next-token", next_token] if next_token else ["--start-from-head"]
        try:
            data = aws(
                "logs", "get-log-events",
                "--log-group-name", LOG_GROUP,
                "--log-stream-name", stream_name,
                "--limit", "10000",
                *extra,
            )
        except RuntimeError as e:
            print(f"  [warn] Could not read stream {stream_name}: {e}", file=sys.stderr)
            break

        batch = data.get("events", [])
        events.extend(batch)

        token = data.get("nextForwardToken")
        # CloudWatch signals end-of-stream by returning the same token twice
        if not token or token == next_token:
            break

        next_token = token

    return events


# ── Message normalisation ────────────────────────────────────────────────────
# Strip tokens that make identical errors look unique: UUIDs, request IDs,
# numeric IDs, timestamps, and short hex strings.  We want "same root cause"
# to collapse into one counter bucket.

_NORM_PATTERNS = [
    # Anthropic / API request IDs  e.g. req_011CZoZQb...
    (re.compile(r'\breq_[A-Za-z0-9]{8,}\b'), 'req_…'),
    # UUIDs  e.g. 0027357c-bfa9-4357-aa4c-e7f96a011dca
    (re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.I), '<uuid>'),
    # Long hex strings (≥12 chars)  e.g. session tokens, trace IDs
    (re.compile(r'\b[0-9a-f]{12,}\b', re.I), '<hex>'),
    # ISO timestamps  e.g. 2026-04-07T19:06:23Z
    (re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?'), '<ts>'),
    # Standalone integers that look like IDs (≥4 digits)
    (re.compile(r'\b\d{4,}\b'), '<id>'),
    # Single-quoted short values  e.g. Value '3', Value '42'
    # (covers Redshift/DB precision errors where the specific value varies)
    (re.compile(r"Value\s+'[^']{1,10}'"), "Value '<val>'"),
    # Trailing JSON key-value noise after "request_id":
    (re.compile(r'"request_id"\s*:\s*"[^"]*"'), '"request_id":"…"'),
]

def normalise(message):
    """Strip instance-specific tokens so identical errors collapse."""
    for pattern, replacement in _NORM_PATTERNS:
        message = pattern.sub(replacement, message)
    # Collapse runs of whitespace / newlines introduced by substitution
    message = re.sub(r'\s+', ' ', message).strip()
    return message


# ── Parsing ──────────────────────────────────────────────────────────────────

def parse_error_event(raw_message):
    """
    Parse one EventBridge event from the central error log.

    Expected shape:
    {
      "detail-type": "Lambda Execution Error",
      "detail": {
        "functionName": "...",
        "error": { "name": "TypeError", "message": "..." }
      }
    }

    Returns None if the message can't be parsed or isn't an error event.
    """
    try:
        event = json.loads(raw_message)
    except (json.JSONDecodeError, TypeError):
        return None

    detail = event.get("detail")
    if not isinstance(detail, dict):
        return None

    fn = detail.get("functionName")
    error = detail.get("error")
    if not fn or not isinstance(error, dict):
        return None

    return {
        "function": fn,
        "error_type": error.get("name") or "Error",
        "error_message": (error.get("message") or "").strip(),
    }


# ── Aggregation ──────────────────────────────────────────────────────────────

def aggregate(events):
    """
    Returns:
        { functionName: Counter({ "ErrorType: message" -> count }) }
    """
    by_function = defaultdict(Counter)

    for raw in events:
        parsed = parse_error_event(raw.get("message", ""))
        if not parsed:
            continue

        fn = parsed["function"]
        err_type = parsed["error_type"]
        err_msg = normalise(parsed["error_message"])

        # Truncate very long messages for display
        if len(err_msg) > 120:
            err_msg = err_msg[:117] + "..."

        key = f"{err_type}: {err_msg}" if err_msg else err_type
        by_function[fn][key] += 1

    return by_function


# ── Formatting ───────────────────────────────────────────────────────────────

def format_report(target_date, by_function):
    lines = []
    lines.append(f"Today's Errors ({target_date})")
    lines.append("")

    if not by_function:
        lines.append("  No errors recorded.")
        return "\n".join(lines)

    # Sort functions by total error count descending
    ranked = sorted(
        by_function.items(),
        key=lambda kv: sum(kv[1].values()),
        reverse=True,
    )

    for rank, (fn, counter) in enumerate(ranked, start=1):
        total = sum(counter.values())
        lines.append(f"{rank}. {fn} — {total} error{'s' if total != 1 else ''}")

        # Sort error types by count descending
        for key, count in counter.most_common():
            if ": " in key:
                err_type, msg = key.split(": ", 1)
                lines.append(f'   - {count}x {err_type}: "{msg}"')
            else:
                lines.append(f'   - {count}x {key}')

        lines.append("")

    # Remove trailing blank line
    if lines and lines[-1] == "":
        lines.pop()

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Print a daily error summary for CoreServices Lambdas.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "date",
        nargs="?",
        default=date.today().isoformat(),
        help="Date to summarise (YYYY-MM-DD). Defaults to today.",
    )
    args = parser.parse_args()

    # Validate date format (date.fromisoformat is equivalent and simpler for YYYY-MM-DD)
    try:
        date.fromisoformat(args.date)
    except ValueError:
        print(f"Error: invalid date '{args.date}' — expected YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    target_date = args.date
    stream_name = target_date  # streams are named YYYY-MM-DD

    print(f"Fetching errors for {target_date} from {LOG_GROUP} ...", file=sys.stderr)

    # Check the stream exists
    try:
        streams = aws(
            "logs", "describe-log-streams",
            "--log-group-name", LOG_GROUP,
            "--log-stream-name-prefix", stream_name,
            "--query", "logStreams[*].logStreamName",
        )
    except RuntimeError as e:
        print(f"Error: could not list log streams: {e}", file=sys.stderr)
        sys.exit(1)

    if stream_name not in streams:
        print(f"No error log stream found for {target_date}.", file=sys.stderr)
        print(f"(Stream '{stream_name}' does not exist in {LOG_GROUP})", file=sys.stderr)
        print(f"\nToday's Errors ({target_date})\n\n  No errors recorded.")
        sys.exit(0)

    print(f"Reading stream '{stream_name}' ...", file=sys.stderr)
    events = get_log_events(stream_name)
    print(f"Fetched {len(events)} raw events.", file=sys.stderr)

    by_function = aggregate(events)
    total_errors = sum(sum(c.values()) for c in by_function.values())
    print(f"Parsed {total_errors} error events across {len(by_function)} function(s).", file=sys.stderr)
    print("", file=sys.stderr)

    report = format_report(target_date, by_function)
    print(report)


if __name__ == "__main__":
    main()
