#!/usr/bin/env python3
"""Tests for reporting-digest. stdlib only; run with: python3 tests/test_digest.py"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "reporting_digest.py")
SAMPLE_FEED = os.path.join(ROOT, "samples", "events.jsonl")


def now_iso(delta_hours=0):
    return (datetime.now(timezone.utc) - timedelta(hours=delta_hours)).isoformat()


def make_event(category, severity, message, hours_ago=1, event_id=None,
               source="test-svc", timestamp=None):
    event = {
        "timestamp": timestamp if timestamp is not None else now_iso(hours_ago),
        "category": category,
        "severity": severity,
        "source": source,
        "message": message,
    }
    if event_id is not None:
        event["id"] = event_id
    return event


def write_feed(path, lines):
    with open(path, "w", encoding="utf-8") as handle:
        for line in lines:
            if isinstance(line, str):
                handle.write(line + "\n")
            else:
                handle.write(json.dumps(line) + "\n")


def run_cli(*args):
    return subprocess.run([sys.executable, CLI, *args],
                          capture_output=True, text=True)


def read_digest(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class DigestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.feed = os.path.join(self.tmp.name, "events.jsonl")
        self.out = os.path.join(self.tmp.name, "digest.md")

    # --- bucketing counts -------------------------------------------------
    def test_bucketing_counts(self):
        write_feed(self.feed, [
            make_event("api", "critical", "c1"),
            make_event("api", "warning", "w1"),
            make_event("api", "warning", "w2"),
            make_event("api", "info", "i1"),
            make_event("db", "info", "i2"),
            make_event("db", "info", "i3"),
        ])
        proc = run_cli("--feed", self.feed, "--out", self.out)
        self.assertEqual(proc.returncode, 0)
        digest = read_digest(self.out)
        self.assertIn("| api | 1 | 2 | 1 | 4 |", digest)
        self.assertIn("| db | 0 | 0 | 2 | 2 |", digest)
        self.assertIn("| **Total** | **1** | **2** | **3** | **6** |", digest)
        self.assertIn("- Total events in window: 6", digest)

    # --- severity ordering ------------------------------------------------
    def test_severity_ordering_most_severe_first(self):
        write_feed(self.feed, [
            make_event("api", "info", "info-msg", hours_ago=0),
            make_event("api", "warning", "warning-msg", hours_ago=0),
            make_event("api", "critical", "critical-msg", hours_ago=0),
        ])
        proc = run_cli("--feed", self.feed, "--out", self.out)
        self.assertEqual(proc.returncode, 0)
        digest = read_digest(self.out)
        crit_pos = digest.index("critical-msg")
        warn_pos = digest.index("warning-msg")
        info_pos = digest.index("info-msg")
        self.assertLess(crit_pos, warn_pos)
        self.assertLess(warn_pos, info_pos)

    # --- --since window filtering -----------------------------------------
    def test_since_filters_old_events(self):
        write_feed(self.feed, [
            make_event("api", "critical", "recent", hours_ago=1),
            make_event("api", "warning", "old", hours_ago=100),
        ])
        proc = run_cli("--feed", self.feed, "--out", self.out, "--since", "24h")
        self.assertEqual(proc.returncode, 0)
        digest = read_digest(self.out)
        self.assertIn("recent", digest)
        self.assertNotIn("old", digest)
        self.assertIn("- Total events in window: 1", digest)
        self.assertIn("- Window: last 24h", digest)

    def test_since_7d_keeps_week_old_events(self):
        write_feed(self.feed, [
            make_event("api", "info", "six-days", hours_ago=6 * 24),
        ])
        proc = run_cli("--feed", self.feed, "--out", self.out, "--since", "7d")
        self.assertEqual(proc.returncode, 0)
        digest = read_digest(self.out)
        self.assertIn("six-days", digest)

    # --- malformed-line tolerance ------------------------------------------
    def test_malformed_lines_are_counted_and_skipped(self):
        write_feed(self.feed, [
            make_event("api", "info", "good", event_id="E1"),
            "this is not json",
            '{"timestamp": "not-a-date", "category": "api", "severity": "info", '
            '"source": "s", "message": "bad ts"}',
            '{"category": "api", "severity": "info", "source": "s", '
            '"message": "missing timestamp"}',
            '{"timestamp": "' + now_iso() + '", "category": "api", '
            '"severity": "bogus", "source": "s", "message": "bad sev"}',
            "[1, 2, 3]",
            "",
            "   ",
        ])
        proc = run_cli("--feed", self.feed, "--out", self.out)
        self.assertEqual(proc.returncode, 0)
        digest = read_digest(self.out)
        self.assertIn("- Total events in window: 1", digest)
        self.assertIn("- Unparseable lines skipped: 5", digest)
        self.assertIn("good", digest)

    # --- open exceptions ----------------------------------------------------
    def test_open_exceptions_lists_criticals_and_warnings_with_ids(self):
        write_feed(self.feed, [
            make_event("api", "critical", "disk full", event_id="INC-1"),
            make_event("db", "warning", "slow query", event_id="INC-2"),
            make_event("api", "critical", "no id event"),
            make_event("db", "info", "all fine"),
        ])
        proc = run_cli("--feed", self.feed, "--out", self.out)
        self.assertEqual(proc.returncode, 0)
        digest = read_digest(self.out)
        section = digest.split("## Open exceptions")[1].split("## Notes")[0]
        self.assertIn("INC-1", section)
        self.assertIn("INC-2", section)
        self.assertIn("(no id)", section)
        self.assertIn("critical", section)
        self.assertIn("warning", section)
        self.assertNotIn("all fine", section)
        self.assertIn("3 open exception(s): 2 critical, 1 warning.", section)

    def test_no_exceptions_section_when_none(self):
        write_feed(self.feed, [make_event("api", "info", "all fine")])
        proc = run_cli("--feed", self.feed, "--out", self.out)
        self.assertEqual(proc.returncode, 0)
        digest = read_digest(self.out)
        section = digest.split("## Open exceptions")[1].split("## Notes")[0]
        self.assertIn("None. No critical or warning events in the window.", section)

    # --- exit codes ----------------------------------------------------------
    def test_exit_0_with_criticals_present(self):
        write_feed(self.feed, [make_event("api", "critical", "boom")])
        proc = run_cli("--feed", self.feed, "--out", self.out)
        self.assertEqual(proc.returncode, 0)

    def test_exit_2_missing_file(self):
        proc = run_cli("--feed", os.path.join(self.tmp.name, "nope.jsonl"),
                       "--out", self.out)
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(os.path.exists(self.out))

    def test_exit_2_zero_parseable_lines(self):
        write_feed(self.feed, ["garbage line", "{not json"])
        proc = run_cli("--feed", self.feed, "--out", self.out)
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(os.path.exists(self.out))

    def test_exit_2_empty_file(self):
        write_feed(self.feed, [])
        proc = run_cli("--feed", self.feed, "--out", self.out)
        self.assertEqual(proc.returncode, 2)

    def test_exit_2_invalid_since(self):
        write_feed(self.feed, [make_event("api", "info", "x")])
        proc = run_cli("--feed", self.feed, "--out", self.out,
                       "--since", "yesterday")
        self.assertEqual(proc.returncode, 2)

    # --- sample feed end to end ----------------------------------------------
    def test_sample_feed_expected_counts(self):
        self.assertTrue(os.path.exists(SAMPLE_FEED), "sample feed missing")
        proc = run_cli("--feed", SAMPLE_FEED, "--out", self.out,
                       "--title", "Sample Digest")
        self.assertEqual(proc.returncode, 0)
        digest = read_digest(self.out)
        self.assertIn("# Sample Digest", digest)
        self.assertIn("| api | 0 | 2 | 4 | 6 |", digest)
        self.assertIn("| auth | 2 | 3 | 4 | 9 |", digest)
        self.assertIn("| deploy | 1 | 2 | 5 | 8 |", digest)
        self.assertIn("| payments | 1 | 1 | 5 | 7 |", digest)
        self.assertIn("| **Total** | **4** | **8** | **18** | **30** |", digest)
        self.assertIn("- Total events in window: 30", digest)
        self.assertIn("- Unparseable lines skipped: 0", digest)

    def test_custom_title(self):
        write_feed(self.feed, [make_event("api", "info", "x")])
        proc = run_cli("--feed", self.feed, "--out", self.out,
                       "--title", "Nightly Report")
        self.assertEqual(proc.returncode, 0)
        digest = read_digest(self.out)
        self.assertTrue(digest.startswith("# Nightly Report\n"))

    def test_out_parent_dirs_created(self):
        write_feed(self.feed, [make_event("api", "info", "x")])
        nested = os.path.join(self.tmp.name, "a", "b", "digest.md")
        proc = run_cli("--feed", self.feed, "--out", nested)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(os.path.exists(nested))


if __name__ == "__main__":
    unittest.main(verbosity=2)
