#!/usr/bin/env python3
"""reporting-digest: turn a JSONL event feed into an evidence-backed markdown digest.

Reads one JSON event per line, filters to a time window, buckets events by
category then severity, and writes a markdown digest with counts, top items
per category, and an open-exceptions section. Every number in the digest is
derived from the feed; nothing is invented.

Exit codes:
    0  success (even when criticals are present -- this is a reporter, not an alerter)
    2  unusable input (missing/unreadable feed file, zero parseable lines in window)
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEVERITIES = ("info", "warning", "critical")
SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}
TOP_ITEMS_PER_CATEGORY = 5

_SINCE_RE = re.compile(r"^(\d+)([mhdw])$", re.IGNORECASE)
_SINCE_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def fail(message):
    """Print an error and exit with code 2 (unusable input)."""
    print(f"reporting-digest: error: {message}", file=sys.stderr)
    sys.exit(2)


def parse_since(value):
    """Parse a window like '24h' or '7d' into a timedelta."""
    match = _SINCE_RE.match(value.strip())
    if not match:
        fail(f"invalid --since value {value!r}; expected like '24h' or '7d'")
    amount = int(match.group(1))
    if amount <= 0:
        fail(f"invalid --since value {value!r}; amount must be positive")
    unit = _SINCE_UNITS[match.group(2).lower()]
    return timedelta(**{unit: amount})


def parse_timestamp(value):
    """Parse an ISO 8601 timestamp; naive values are assumed UTC."""
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_events(feed_path):
    """Read the JSONL feed. Returns (events, unparseable_count, total_lines).

    Blank lines are skipped silently. Any non-blank line that is not valid
    JSON, or is missing/invalid required fields, counts as unparseable.
    Required fields: timestamp (ISO 8601), category, severity
    (info|warning|critical), source, message. Extra fields (e.g. id) are kept.
    """
    events = []
    unparseable = 0
    total_lines = 0
    with open(feed_path, "r", encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, start=1):
            total_lines += 1
            line = raw.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                unparseable += 1
                print(f"reporting-digest: skipping unparseable line {lineno}",
                      file=sys.stderr)
                continue
            if not isinstance(record, dict):
                unparseable += 1
                print(f"reporting-digest: skipping non-object line {lineno}",
                      file=sys.stderr)
                continue
            timestamp = parse_timestamp(record.get("timestamp", ""))
            severity = record.get("severity")
            category = record.get("category")
            source = record.get("source")
            message = record.get("message")
            valid = (
                timestamp is not None
                and severity in SEVERITY_RANK
                and isinstance(category, str) and category.strip()
                and isinstance(source, str) and source.strip()
                and isinstance(message, str) and message.strip()
            )
            if not valid:
                unparseable += 1
                print(f"reporting-digest: skipping invalid event on line {lineno}",
                      file=sys.stderr)
                continue
            events.append({
                "timestamp": timestamp,
                "category": category.strip(),
                "severity": severity,
                "source": source.strip(),
                "message": message.strip(),
                "id": record.get("id"),
                "lineno": lineno,
            })
    return events, unparseable, total_lines


def esc(text):
    """Make a value safe for a markdown table cell."""
    return (str(text).replace("\r", " ").replace("\n", " ")
            .replace("|", "\\|").strip())


def fmt_ts(ts):
    return ts.isoformat()


def build_digest(title, since_label, generated_at, events, unparseable):
    """Render the markdown digest from the filtered events."""
    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Window: {since_label}")
    lines.append(f"- Generated at: {fmt_ts(generated_at)} (UTC)")
    lines.append(f"- Total events in window: {len(events)}")
    lines.append(f"- Unparseable lines skipped: {unparseable}")
    lines.append("")

    categories = sorted({e["category"] for e in events})

    # Counts table: per category x severity.
    lines.append("## Counts by category x severity")
    lines.append("")
    lines.append("| Category | Critical | Warning | Info | Total |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    totals = {sev: 0 for sev in SEVERITIES}
    for category in categories:
        counts = {sev: 0 for sev in SEVERITIES}
        for event in events:
            if event["category"] == category:
                counts[event["severity"]] += 1
        for sev in SEVERITIES:
            totals[sev] += counts[sev]
        row_total = sum(counts.values())
        lines.append(f"| {esc(category)} | {counts['critical']} | "
                     f"{counts['warning']} | {counts['info']} | {row_total} |")
    grand_total = sum(totals.values())
    lines.append(f"| **Total** | **{totals['critical']}** | **{totals['warning']}** "
                 f"| **{totals['info']}** | **{grand_total}** |")
    lines.append("")

    # Top items per category: most severe first, then most recent.
    lines.append("## Top items by category")
    lines.append("")
    for category in categories:
        lines.append(f"### {esc(category)}")
        lines.append("")
        bucket = [e for e in events if e["category"] == category]
        bucket.sort(key=lambda e: (SEVERITY_RANK[e["severity"]],
                                   -e["timestamp"].timestamp()))
        for event in bucket[:TOP_ITEMS_PER_CATEGORY]:
            lines.append(f"- **[{event['severity'].upper()}]** "
                         f"{fmt_ts(event['timestamp'])} -- "
                         f"{esc(event['source'])} -- {esc(event['message'])}")
        lines.append("")

    # Open exceptions: every critical and warning in the window is open,
    # because the feed carries no resolution field.
    exceptions = [e for e in events if e["severity"] in ("critical", "warning")]
    exceptions.sort(key=lambda e: (SEVERITY_RANK[e["severity"]],
                                   -e["timestamp"].timestamp()))
    lines.append("## Open exceptions")
    lines.append("")
    if exceptions:
        lines.append("| ID | Severity | Category | Timestamp | Source | Message |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for event in exceptions:
            event_id = event["id"] if event["id"] not in (None, "") else "(no id)"
            lines.append(f"| {esc(event_id)} | {event['severity']} | "
                         f"{esc(event['category'])} | {fmt_ts(event['timestamp'])} | "
                         f"{esc(event['source'])} | {esc(event['message'])}")
        lines.append("")
        lines.append(f"{len(exceptions)} open exception(s): "
                     f"{totals['critical']} critical, {totals['warning']} warning. "
                     "The feed has no resolution field, so every warning and "
                     "critical in the window is treated as open.")
    else:
        lines.append("None. No critical or warning events in the window.")
    lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append(f"- Unparseable lines skipped: {unparseable}. "
                 "Malformed lines never stop the run; they are counted here.")
    lines.append("- Every number above is derived from the feed file; "
                 "no aggregates are invented.")
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="reporting-digest",
        description="Turn a JSONL event feed into an evidence-backed "
                    "markdown digest.")
    parser.add_argument("--feed", required=True,
                        help="path to the JSONL event feed")
    parser.add_argument("--out", required=True,
                        help="path to write the markdown digest")
    parser.add_argument("--since", default=None,
                        help="window like '24h' or '7d'; default is all events")
    parser.add_argument("--title", default="Daily Ops Digest",
                        help="digest title (default: %(default)s)")
    args = parser.parse_args(argv)

    feed_path = Path(args.feed)
    if not feed_path.is_file():
        fail(f"feed file not found: {args.feed}")

    events, unparseable, _total_lines = load_events(feed_path)

    since_label = "all events (no window)"
    if args.since:
        window = parse_since(args.since)
        cutoff = datetime.now(timezone.utc) - window
        events = [e for e in events if e["timestamp"] >= cutoff]
        since_label = f"last {args.since}"

    if not events:
        fail("zero parseable events in the selected window")

    digest = build_digest(args.title, since_label,
                          datetime.now(timezone.utc), events, unparseable)

    out_path = Path(args.out)
    if out_path.parent and str(out_path.parent) not in ("", "."):
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(digest + "\n", encoding="utf-8")

    criticals = sum(1 for e in events if e["severity"] == "critical")
    warnings = sum(1 for e in events if e["severity"] == "warning")
    print(f"digest written to {args.out}: {len(events)} events, "
          f"{criticals} critical, {warnings} warning, "
          f"{unparseable} unparseable lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
