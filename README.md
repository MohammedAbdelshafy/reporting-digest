# reporting-digest

A cron-friendly Python CLI (stdlib only, no dependencies) that turns a JSONL
event feed into an evidence-backed markdown digest: counts per category x
severity, top items per category, and an open-exceptions section. Every
number in the digest is derived from the feed; malformed lines are counted
and skipped, never crash the run.

## Install

Requires Python 3.9+ (matches `pyproject.toml`; the parser handles `Z`
suffixes itself, so no 3.11-only APIs are needed). Standard library only —
no third-party packages.

```bash
git clone https://github.com/MohammedAbdelshafy/reporting-digest.git
cd reporting-digest
python3 -m reporting_digest --help
```

To get the `reporting-digest` command on your `PATH`:

```bash
pip install .
reporting-digest --help
```

## Usage

```bash
reporting-digest --feed events.jsonl --out digest.md [--since 24h] [--title "Daily Ops Digest"]
```

(`reporting-digest` is the console script installed by `pip install .`; from
a clone, run `python3 -m reporting_digest ...` from the repo root instead.)

Try it with the bundled synthetic sample feed:

```bash
python3 -m reporting_digest --feed samples/events.jsonl --out /tmp/digest.md --since 24h --title "Sample Digest"
```

Cron example (daily at 08:00):

```cron
0 8 * * * reporting-digest --feed /var/log/events.jsonl --out /var/www/digest.md --since 24h
```

## Input

One JSON object per line, UTF-8 encoded (a leading BOM is tolerated).
Required fields:

| Field      | Type   | Notes                                            |
| ---------- | ------ | ------------------------------------------------ |
| timestamp  | string | ISO 8601 (`2026-10-06T10:30:00Z`, offsets OK)    |
| category   | string | bucket label, e.g. `deploy`, `auth`, `payments`  |
| severity   | string | one of `info`, `warning`, `critical`             |
| source     | string | where the event came from                        |
| message    | string | human-readable description                       |
| id         | string | optional; shown in the open-exceptions section   |

Extra fields are ignored. Blank lines are skipped silently. Any non-blank
line that is not valid JSON or is missing/invalid required fields counts as
one `unparseable_lines` and is skipped (a warning goes to stderr). The run
never fails because of a bad line.

## Output

A markdown file with:

- Header: window, generated-at (UTC), total events, unparseable line count.
- Counts table: per category x severity (critical / warning / info / total).
- Top items per category: most severe first, then most recent, capped at 5
  per category, each with timestamp, source, and message.
- Open exceptions: every critical and warning in the window, listed with
  its id (or `(no id)`). The feed has no resolution field, so all warnings
  and criticals are treated as open.
- Notes footer: unparseable line count.

## Exit codes

- `0` — success. Criticals in the feed do not change this; the tool is a
  reporter, not an alerter.
- `2` — unusable input or output: missing/unreadable feed file, zero
  parseable events in the selected window, an invalid `--since` value, an
  empty `--title`, `--out` identical to `--feed` (refused, to protect the
  feed), or an unwritable `--out` path.

`--out` must resolve to a different file than `--feed`; the run refuses to
overwrite its own input.

## Limits

- Single machine, single file per run; no deduplication across runs.
- No delivery: it writes a markdown file, it does not send email or
  webhooks.
- Window filtering (`--since 24h`, `--since 7d`, also `m`/`w`) is based on
  event timestamps vs. the current time.

## Sample data

`samples/events.jsonl` holds 30 synthetic sample events across four
categories (`deploy`, `auth`, `payments`, `api`) and all three severities,
clearly labeled with `"sample": true` in each record. They are fabricated
for testing and carry no real operational meaning.

## License

MIT — see [LICENSE](LICENSE).
