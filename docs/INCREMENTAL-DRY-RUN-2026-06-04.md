# Incremental Dry Run - 2026-06-04

Issue: #46 - 증분 적재 정확성 재정의 + end-to-end 검증.

## Run

- Command: `make ingest`
- Mode: `incremental`
- `ingest_runs.id`: `190`
- Started: `2026-06-04 12:07:43 UTC`
- Finished: `2026-06-04 12:24:44 UTC`
- Status: `success`
- Dead letters: `0`

## Acceptance Signals

| Stage | Signal | Result |
|---|---:|---:|
| `bills` | list rows re-scanned | 17,317 |
| `bills` | summary detail fetch targets | 52 |
| `bills` | summary detail fetch skipped | 17,265 |
| `bills` | summary errors | 0 |
| `votes` | voted-bill list rows re-scanned | 1,595 |
| `votes` | vote detail fetch targets | 0 |
| `votes` | vote detail fetch skipped | 1,595 |
| `votes` | vote detail errors | 0 |
| `meetings` | meeting rows reconciled | 2,105 |
| `meetings` | new meetings | 2 |
| `meetings` | changed meetings | 26 |
| `utterances` | touched meetings scraped | 28 |
| `utterances` | scrape errors | 0 |
| `session_groups` | touched meetings regrouped | 28 |

## Cursor State

After the successful run, `ingest_cursors` records source-level observation cursors only:

| Source | `cursor_kind` | `overlap_days` | `updated_run_id` |
|---|---|---:|---:|
| `members` | `full_refresh` | 0 | 190 |
| `bills` | `last_success_at` | 0 | 190 |
| `votes` | `last_success_at` | 0 | 190 |
| `meetings` | `last_success_at` | 0 | 190 |
| `utterances` | `last_success_at` | 0 | 190 |
| `session_groups` | `last_success_at` | 0 | 190 |

## Observations

- The corrected `bills` path re-scanned the cheap list endpoint but fetched only 52 missing summaries instead of re-fetching every bill summary.
- The corrected `votes` path re-scanned the cheap voted-bill list but fetched 0 vote detail payloads because every voted bill already had vote rows.
- Worker benchmark documents were not regenerated during the incremental run; the official command reused calibrated worker counts.
- `meetings` remained the slowest stage because `VCONFBILLCONFLIST` still checks 15,561 bill ids to rebuild meeting-bill links. That cost is outside #46's immutable-detail skip contract and should be considered separately if incremental runtime becomes a problem.
- 28 touched meetings were re-scraped and re-grouped successfully. Several source HTML pages initially returned metadata mismatches or transient timeouts, but retries completed with 0 scrape errors.
