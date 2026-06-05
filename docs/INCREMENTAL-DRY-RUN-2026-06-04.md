# Incremental Dry Run - 2026-06-04

Issue: #46 - 증분 적재 정확성 재정의 + end-to-end 검증.

## Post-#49 / #54 Verification Run

- Command: `make ingest`
- Mode: `incremental`
- `ingest_runs.id`: `371`
- Started: `2026-06-04 14:27:29 UTC`
- Finished: `2026-06-04 14:31:45 UTC`
- Status: `success`
- Dead letters: `0`

| Stage | Signal | Result |
|---|---:|---:|
| `bills` | list rows re-scanned | 17,317 |
| `bills` | summary detail fetch targets | 40 |
| `bills` | summary detail fetch skipped | 17,277 |
| `votes` | voted-bill list rows re-scanned | 1,595 |
| `votes` | vote detail fetch targets | 0 |
| `votes` | vote detail fetch skipped | 1,595 |
| `meetings` | meeting rows reconciled | 2,105 |
| `meetings` | new meetings | 0 |
| `meetings` | changed meetings | 0 |
| `meetings` | `VCONFBILLCONFLIST` fetch targets | 1 |
| `meetings` | `VCONFBILLCONFLIST` fetch skipped | 15,561 |
| `utterances` | touched/missing meetings scraped | 0 |

After #49, the slow bill-by-bill meeting-link step no longer rebuilds every
known link in incremental mode. It fetched 1 bill's `VCONFBILLCONFLIST` rows
and skipped 15,561 already-linked bills, while preserving existing
`meeting_bills` and adding 1 new link. After #54, there is no `session_groups`
stage or cursor.

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

## Cursor State

After the successful run, `ingest_cursors` records source-level observation cursors only:

| Source | `cursor_kind` | `overlap_days` | `updated_run_id` |
|---|---|---:|---:|
| `members` | `full_refresh` | 0 | 190 |
| `bills` | `last_success_at` | 0 | 190 |
| `votes` | `last_success_at` | 0 | 190 |
| `meetings` | `last_success_at` | 0 | 190 |
| `utterances` | `last_success_at` | 0 | 190 |

## Observations

- The corrected `bills` path re-scanned the cheap list endpoint but fetched only 52 missing summaries instead of re-fetching every bill summary.
- The corrected `votes` path re-scanned the cheap voted-bill list but fetched 0 vote detail payloads because every voted bill already had vote rows.
- Worker benchmark documents were not regenerated during the incremental run; the official command reused calibrated worker counts.
- `meetings` remained the slowest stage because `VCONFBILLCONFLIST` still checked 15,561 bill ids to rebuild meeting-bill links. That cost was outside #46's immutable-detail skip contract and is addressed by #49.
- 28 touched meetings were re-scraped successfully. Several source HTML pages initially returned metadata mismatches or transient timeouts, but retries completed with 0 scrape errors.
