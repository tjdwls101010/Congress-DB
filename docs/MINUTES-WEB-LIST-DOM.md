# Minutes Web List DOM Contract

Live inspection date: 2026-05-27. Target page: `https://record.assembly.go.kr/assembly/mnts/total/22.do`.

## Purpose

The minutes web list is the canonical source for which 22대 meetings have HTML minutes. The scraper must extract detail viewer URLs from this page family, then pass only `type=view` HTML pages into utterance parsing.

## Top-Level Classes

The page exposes six top-level list tabs:

| class_id_sch | Label | First-level nodes |
|---:|---|---|
| 1 | 국회본회의 | 회기 nodes: `.tree_list a.tit.sess` |
| 2 | 상임위원회 | 위원회 nodes: `.tree_list a.tit.cmit` |
| 4 | 예산결산특별위원회 | 회기 nodes: `.tree_list a.tit.sess` |
| 3 | 특별위원회 | 위원회 nodes: `.tree_list a.tit.cmit` |
| 5 | 국정감사 | 위원회 nodes: `.tree_list a.tit.cmit`, then year nodes |
| 6 | 국정조사 | 위원회 nodes: `.tree_list a.tit.cmit`, then 회기 nodes |

Use these canonical entry URLs:

```text
/assembly/mnts/total/22.do?class_id_sch=1&cmit_chk=all
/assembly/mnts/total/22.do?class_id_sch=2&cmit_chk=all
/assembly/mnts/total/22.do?class_id_sch=4&cmit_chk=all
/assembly/mnts/total/22.do?class_id_sch=3&cmit_chk=all
/assembly/mnts/total/22.do?class_id_sch=5&cmit_chk=all
/assembly/mnts/total/22.do?class_id_sch=6&cmit_chk=all
```

## Dynamic Loading

The page does not render all final meeting rows up front. It loads nested rows through `resources/mnts/total/list.js` and internal async endpoints:

| JS function | Endpoint | Role |
|---|---|---|
| `sessload` | `/assembly/mnts/async/sess.do` | Loads final minute rows for 본회의 and 예산결산특별위원회 회기 nodes |
| `cmitload` | `/assembly/mnts/async/sessCmit.do` | Loads 회기/year child nodes under committee-like classes |
| `subcmitload` | `/assembly/mnts/async/cmit.do` | Loads final minute rows under committee + 회기/year child nodes |
| `order_numload` | `/assembly/mnts/async/ord.do` | Loads lower detail for an already discovered minute; not needed for detail URL collection |

The scraper should reproduce these endpoint calls with a session cookie obtained from the initial page load. Direct unauthenticated calls can return an error page.

## Final Minute Row Shape

Final rows contain a title node plus a button list:

```html
<a class="tit ord_num" data-id="56654" data-class="1" data-sess="435">
  <strong><span class="temp">[임시]</span> 제2차 (2026. 05. 08.)</strong>
</a>
...
<a class="btn black" href="/assembly/viewer/minutes/xml.do?id=56654&type=view">회의록뷰어</a>
<a class="btn white" href="/assembly/viewer/minutes/xml.do?id=56654&type=summary">회의정보</a>
```

The authoritative detail URL selector is:

```css
a[href*="/assembly/viewer/minutes/xml.do"][href*="type=view"]
```

For each such link:

- `mnts_id` = `id` query parameter.
- `detail_url` = absolute URL resolved against `https://record.assembly.go.kr`.
- `title` = closest row's `.txt a.tit` or `a.tit.ord_num` text.
- `is_temporary` = title contains `[임시]` or row contains `.temp`.
- `is_appendix` = row text contains `(부록)`.

Fallback: if a final row has `a.tit.ord_num[data-id]` but no `type=view` link, build no utterance target. Record it as HTML viewer unavailable instead of trying PDF/HWP.

## Representative Verified Shapes

| Class | Expansion Path | Example `mnts_id` | Example title |
|---:|---|---:|---|
| 1 | 회기 → final rows | 56654 | `[임시] 제2차 (2026. 05. 08.)` |
| 2 | 위원회 → 회기 → final rows | 56295 | `위 제1차 (2026. 02. 23.)` |
| 4 | 회기 → final rows | 56543 | `위 [임시] 제3차 (2026. 04. 10.)` |
| 3 | 위원회 → 회기 → final rows | 56050 | `위 제8차 (2025. 12. 30.) (부록)` |
| 5 | 위원회 → year → final rows | 55735 | `대통령비서실|국가안보실|대통령경호처 (2025. 11. 06.) (부록)` |
| 6 | 위원회 → 회기 → final rows | 56213 | `위 제6차 (2026. 01. 30.)` |

## Incremental Strategy

For both initial backfill and future syncs, crawl all six class pages and all nested nodes. The 22대 list is small enough that full list reconciliation is simpler and safer than trying to infer a date window from the UI.

Each sync computes:

- `new_mnts_ids`: present in web list but absent from `meetings`.
- `changed_meetings`: same `mnts_id`, but title, `is_temporary`, `is_appendix`, date, or classification changed.
- `html_unavailable`: present in web list but no `type=view` link is exposed in the list DOM. A `type=view` link that later returns non-200 is classified by utterance ingest/dead-letter handling, not by the list crawler.
- `openapi_only`: present in OpenAPI metadata but absent from web list; kept out of core `meetings` and reported only.

Only `new_mnts_ids` and `changed_meetings` become touched meetings for utterance re-scraping and session group recalculation.

## Implementation Contract

- `congress_db.minutes_web_list.collect_minutes_web_list()` returns both HTML-ready `meetings` and `html_unavailable` rows.
- `congress_db.minutes_web_list.crawl_minutes_web_list()` is the meetings-only convenience interface.
- `congress_db.ingest_meetings.ingest_meetings()` upserts only web-list meetings into core `meetings`.
- OpenAPI meeting rows are used only to fill missing matched metadata and to derive `meeting_bills` from transient `SUB_NAME` parsing.
- OpenAPI-only IDs are returned in ingest summary during full meeting loads, but are not inserted into core `meetings`.
- Full meeting loads prune stale core `meetings` that are no longer present in the web list, after a guard confirms the crawled canonical set is not unexpectedly small.

## Non-Goals

- Do not parse PDF/HWP.
- Do not store PDF/HWP/VOD/summary links in core `meetings`.
- Do not preserve official meeting agenda text as a core table; use it transiently only to derive `meeting_bills`.
