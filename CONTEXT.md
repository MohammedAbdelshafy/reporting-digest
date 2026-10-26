---
type: repository
status: active
owner_repo: MohammedAbdelshafy/reporting-digest
product_name: Reporting Digest
source_of_truth: https://github.com/MohammedAbdelshafy/reporting-digest
---

# Reporting Digest CONTEXT

One job: turn an event file into a readable summary that helps a person spot activity and open exceptions.

## Inputs
- Format and commands: [README](README.md)
- Implementation: [reporting_digest.py](reporting_digest.py)
- Tests: [tests](tests/)
- Sample data: [samples](samples/)

## Process
1. Read JSONL records from the configured input file.
2. Group events by category and severity within the requested time window.
3. Count malformed lines and skip them with a warning.
4. Write a Markdown report or the supported JSON output.
5. Verify the report uses only values present in the feed.

## Output
A summary file showing the reporting window, counts, important items, and open exceptions.

## Check
Run the repository tests and a synthetic feed with valid and malformed lines. The report must not invent events or totals.
