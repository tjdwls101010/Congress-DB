# Minutes Web Coverage Check

Generated from a live check on 2026-05-27 against `https://record.assembly.go.kr/assembly/mnts/total/22.do`.

## Purpose

Validate whether the local `meetings` universe should be based on the National Assembly minutes web listing rather than the public OpenAPI meeting endpoints. This is a pre-hosted-Postgres migration quality gate because utterances are parsed from HTML viewer pages, not from PDF/HWP files.

## Method

- Loaded each `total/22.do` class tab for 22대: 본회의, 상임위원회, 예산결산특별위원회, 특별위원회, 국정감사, 국정조사.
- Followed the page's own internal async endpoints:
  - `/assembly/mnts/async/sess.do`
  - `/assembly/mnts/async/sessCmit.do`
  - `/assembly/mnts/async/cmit.do`
- Extracted `mnts_id` from `xml.do?id=...` links and `minutes{id}` tree nodes.
- Compared the web-list `mnts_id` set with local `meetings.mnts_id`.

The DOM and incremental contract are captured in [MINUTES-WEB-LIST-DOM.md](MINUTES-WEB-LIST-DOM.md).

## Result

| Metric | Count |
|---|---:|
| Web listing minutes | 2,103 |
| Web-list canonical local meetings | 2,103 |
| OpenAPI meetings missing from web listing | 1 |
| Web-only minutes added to local meetings | 23 |
| Web crawl errors | 0 |

## OpenAPI-Only Candidate

| mnts_id | Date | Type | Title | Interpretation |
|---:|---|---|---|---|
| 55355 | 2025-09-06 | 상임위 | 제22대 제429회 제99차 국회운영위원회 | Not present in `total/22.do`; removed from core `meetings` together with its stale `meeting_bills` and `minutes.html` dead-letter state. |

## Web-Only HTML Minutes

These are present in `total/22.do`, absent from local OpenAPI-derived `meetings`, and their `type=view` HTML exposes `.minutes_body` with speaker nodes. All 23 have now been loaded into `utterances`.

| mnts_id | Speaker Nodes | Web List Label |
|---:|---:|---|
| 52054 | 29 | 국정조사록-서울동부구치소 (2025. 02. 05.) |
| 52055 | 60 | 국정조사록-서울구치소 (2025. 02. 05.) |
| 52056 | 27 | 국정조사록-육군수도방위사령부 (2025. 02. 05.) |
| 52295 | 38 | 위 제10차 (2024. 12. 09.) |
| 52312 | 137 | 위 제8차 (2024. 11. 14.) |
| 52398 | 35 | 위 제9차 (2024. 12. 06.) |
| 52399 | 23 | 위 제10차 (2024. 12. 09.) |
| 52418 | 178 | 위 제10차 (2024. 11. 11.) |
| 52482 | 20 | 위 제11차 (2024. 12. 06.) |
| 52483 | 35 | 위 제12차 (2024. 12. 09.) |
| 52612 | 145 | 위 제1차 (2024. 12. 11.) |
| 52683 | 35 | 위 제1차 (2025. 01. 17.) |
| 55026 | 21 | 위 제3차 (2025. 07. 15.) |
| 55051 | 22 | 위 제4차 (2025. 07. 16.) |
| 55273 | 3 | 개회식 (2025. 09. 01.) |
| 55342 | 2,079 | 국정조사록-국무조정실 등 (2025. 09. 10.) (부록) |
| 55372 | 418 | 국정조사록-충청북도 등 (2025. 09. 15.) (부록) |
| 55781 | 208 | 위 제13차 (2025. 11. 11.) |
| 55883 | 1 | 소 예산결산기금심사소위원회 제4차 (2025. 11. 27.) |
| 56230 | 3 | [임시] 개회식 (2026. 02. 02.) |
| 56368 | 50 | 위 제2차 (2026. 03. 16.) |
| 56591 | 7 | 소 법안심사소위원회 제2차 (2026. 04. 23.) |
| 56594 | 11 | 위 [임시] 제2차 (2026. 04. 23.) |

## Existing Dead Letter Findings

| mnts_id | Web Listing | HTML Viewer | Interpretation |
|---:|---|---|---|
| 52354 | Present | `type=view` returns 400 after normal retry and final low-worker retry; `type=summary` opens but has no parseable `.minutes_body` | Known source defect. Marked `ignored` in `dead_letters`; do not recover via PDF/HWP. |
| 52713 | Present | `type=view`, `type=summary`, `type=html`, and `type=pdf` all return 400 | Known source defect. Marked `ignored` in `dead_letters`; do not recover via PDF/HWP. |
| 55355 | Absent | `type=view` opens with 0 speakers and 0 pages | OpenAPI-only non-utterance candidate; pruned from core tables. |

## Decisions

- Do not parse PDF/HWP for utterances.
- Treat `total/22.do` as the canonical meeting universe for HTML utterance collection.
- Use OpenAPI meeting endpoints only to enrich metadata and derive `meeting_bills` for matching `mnts_id` values.
- Add web-only HTML minutes to the local meetings universe before final utterance/session group generation.
- Keep OpenAPI-only rows out of core `meetings` unless they later appear in the web list with usable HTML.
- Classify web-listed-but-HTML-inaccessible rows explicitly as known source defects instead of trying PDF/HWP fallback.
- For full backfills, skip the verified HTML-unavailable `mnts_id` values `52354` and `52713` so a successful run means all parseable HTML minutes were loaded.

## Implementation Status

- Web-list crawling is implemented in `congress_db.minutes_web_list`.
- Meeting ingest now upserts core `meetings` from the web list and treats OpenAPI meeting rows as enrichment/report inputs.
- Full meeting ingest selected 50 workers for `VCONFBILLCONFLIST`, inserted 40,357 `meeting_bills`, added 23 web-only meetings, and pruned stale OpenAPI-only `55355`.
- Targeted utterance ingest for the 25 missing meetings selected 2 workers, loaded 23 meetings and 3,585 utterances, then left only the two known HTML-unavailable source defects.
- `html_unavailable_mnts_ids`, `web_only_mnts_ids`, `openapi_only_mnts_ids`, and `stale_meeting_ids` are exposed in the meeting ingest summary. The web/OpenAPI set comparison is meaningful on full meeting loads, not partial calibration runs.
