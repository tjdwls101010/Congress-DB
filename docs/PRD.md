# PRD — 22대 국회 통합 데이터베이스

> 본 문서는 GitHub Issue로 발행되어 `ready-for-agent`로 분류된다. AGENT-BRIEF는 슬라이스 분해 후 각 자식 issue에 별도 작성.

## Problem Statement

국회 OpenAPI는 277개에 달하지만 다수가 서로 중복되거나, 더 이상 갱신되지 않거나, 필요한 정보가 흩어져 있어 단일 의원을 키로 그 활동 전반을 조회할 수 없다.

PM(비개발자)이 의정 활동을 분석할 때마다 매번 여러 API를 직접 조합해야 해 시간 소요와 오류가 크다. 향후 검색 API/SDK를 만들려면 정규화된 통합 DB가 선행되어야 한다.

회의록은 utterance 단위로 흩어져 있고, 공식 회의 안건(`SUB_NAME`)은 정책 의제 검색 단위와 다르다. 다양한 회의 유형(본회의·상임위·국정감사·국정조사·인사청문회·소위)을 단일 스키마로 통합하고, 가능한 회의에서는 Q&A 그룹을 자동 감지해야 한다.

## Solution

9개 핵심 테이블 + 1개 카탈로그 테이블 + 수집 운영 상태 테이블로 구성된 Postgres 16 DB를 구축한다. 22대 임기(2024-05-30~) 데이터에 한정하며, 같은 적재 Module로 초기 전체 백필과 이후 증분 동기화를 모두 처리한다.

핵심 가치:
1. **한 의원 ID로 발의·표결·발언 통합 조회** — SQL JOIN 한 줄.
2. **회의록 통합 스키마** — 웹 회의록 목록을 기준으로 본회의·위원회·국정감사·국정조사·인사청문회·소위를 통합.
3. **Q&A 그룹 자동 감지** — 가능한 회의에 적용.
4. **API 카탈로그 — 우리가 쓰는 OpenAPI의 작동 검증 + 메타 문서화** (HTML 스크래핑은 별도).

향후 검색 API/SDK는 이 공식 근거 DB 위에 정책 의제/입장 레이어를 얹는다. 예: 어떤 의원의 의제가 무엇인지, 어떤 의원이 어떤 의제에 어떤 입장인지, 어떤 의제에 어떤 법안이 있고 국회에서 어떻게 논의되어 왔는지.

로컬에서 100% 백필과 검증을 완료한 뒤 Supabase로 마이그레이션한다. Supabase 전환 후에는 로컬/별도 runner가 Supabase DB에 직접 증분 upsert한다.

## User Stories

### A. 데이터 수집·적재 (시스템 동작)

1. 시스템은 22대 의원 ~286명의 인적사항을 API `nwvrqwxyaytdsfvhu`에서 가져와 `members` 테이블에 적재한다.
2. 시스템은 22대 발의된 법안 ~17,000+건을 API `nzmimeepazxkubdpn`에서 페이지네이션으로 받아 `bills` 테이블에 적재한다.
3. 시스템은 각 법안의 주요내용을 API `BPMBILLSUMMARY`에서 병렬로 받아 `bills.summary`에 저장한다.
4. 시스템은 법안의 대표발의자 코드(`RST_MONA_CD`)와 공동발의자 코드(`PUBL_MONA_CD`)를 콤마로 split 하여 각각 `bill_lead_proposers`, `bill_coproposers` N:M 테이블에 row 단위로 정규화한다. 원본 텍스트는 `bills.rst_proposer`, `bills.publ_proposer`, `bills.proposer`에도 보존한다.
5. 시스템은 `record.assembly.go.kr/assembly/mnts/total/22.do` 계열 웹 목록을 기준으로 22대 HTML 회의록 대상을 `meetings`에 저장하고, OpenAPI 회의록 endpoint는 같은 `mnts_id`로 매칭되는 메타데이터 보강에 사용한다.
6. 시스템은 본회의 표결 결과를 API `nojepdqqaweusdfbi`에서 의안 단위로 받아 `votes` 테이블에 저장한다. 표결 시점의 정당명은 `poly_nm_at_vote`에 박는다.
7. 시스템은 의안별 회의록 매핑 API `VCONFBILLCONFLIST`와 회의록 OpenAPI의 `SUB_NAME`에서 법안으로 식별 가능한 항목을 합쳐 `meeting_bills` junction에 저장한다.
8. 시스템은 회의록 본문을 `record.assembly.go.kr` HTML에서 스크래핑해 utterance 단위로 `utterances` 테이블에 저장한다. 한자 이름은 한글로 정규화한다.
9. 시스템은 회의록 본문의 의장 호명 패턴을 감지해 Q&A 그룹(`session_groups`)을 자동 생성하되, **본회의와 소위원회는 적용하지 않는다**.
10. 시스템은 공식 회의 안건 원문을 core 테이블로 보존하지 않는다. 법안 검색에 필요한 관계만 `meeting_bills`에 남긴다.
11. 시스템은 모든 INSERT를 `ON CONFLICT DO UPDATE`로 idempotent 하게 처리하여 재실행 안전성을 보장한다.
12. 시스템은 수집 대상 core 테이블에 `fetched_at` 컬럼을 두어 마지막 수집 시각을 기록한다.

### B. 의원 (Member) 조회 시나리오

13. 사용자는 의원 이름(예: '강대식')으로 `members` 테이블에서 해당 의원의 `mona_cd`와 기본정보를 조회할 수 있다.
14. 사용자는 한 의원의 대표발의 법안 전체를 `bill_lead_proposers` 정규화 테이블 JOIN으로 조회할 수 있다.
15. 사용자는 한 의원의 공동발의 법안 전체를 `bill_coproposers` 정규화 테이블 JOIN으로 조회할 수 있다.
16. 사용자는 한 의원의 본회의 표결 이력을 `votes` 테이블 JOIN으로 조회할 수 있다.
17. 사용자는 한 의원이 발언한 모든 회의를 `utterances.speaker_mona_cd` JOIN으로 조회할 수 있다.
18. 사용자는 한 의원이 질의자인 모든 Q&A 그룹을 `session_groups.questioner_mona_cd` JOIN으로 조회할 수 있다.

### C. 법안 (Bill) 조회 시나리오

19. 사용자는 법안 이름의 부분 일치(예: '항공안전법')로 법안을 검색할 수 있다.
20. 사용자는 한 법안의 처리 과정(발의일·위원회·본회의·처리결과·처리일)을 `bills` 한 row로 조회할 수 있다.
21. 사용자는 한 법안의 공동발의자 명단을 `bill_coproposers` JOIN으로 조회할 수 있다.
22. 사용자는 한 법안의 본회의 표결 결과(286명 의원별)를 `votes` JOIN으로 조회할 수 있다.
23. 사용자는 한 법안의 표결 집계(찬·반·기·불참)를 `votes` GROUP BY로 즉시 계산할 수 있다 (별도 캐시 테이블 없이).
24. 사용자는 한 법안이 다뤄진 모든 회의를 `meeting_bills` junction JOIN으로 조회할 수 있다.

### D. 회의 (Meeting) 조회 시나리오

25. 사용자는 회의 종류·기간·위원회로 회의를 검색할 수 있다.
26. 사용자는 한 회의에서 다뤄진 법안 목록을 `meeting_bills`에서 조회할 수 있다.
27. 사용자는 한 회의의 발언 stream을 `utterances`에서 `sequence` 순으로 조회할 수 있다.
28. 사용자는 한 회의의 Q&A 그룹 목록(있다면)을 `session_groups`에서 조회할 수 있다.
29. 사용자는 위원회 단위(예: '국방위원회')로 그 위원회의 모든 회의를 `meetings.comm_name`으로 조회할 수 있다.

### E. 검색 시나리오 (한국어 키워드 검색)

30. 사용자는 발언 본문에서 키워드(예: '전세사기')를 포함한 발언과 그 회의를 검색할 수 있다.
31. 사용자는 법안 주요내용(`summary`) 본문에서 키워드를 검색할 수 있다.
32. 시스템은 10% 데이터 적재 시점에 한국어 검색 방식(`pg_trgm` vs `pgroonga` vs 기타)을 비교 후 결정한다.

### F. 운영 (Operation)

33. 시스템은 PRD에 명시된 사용 확정 OpenAPI(아래 "외부 API 사용 목록" 표 중 회의록 본문 HTML 행 제외)의 작동을 1회 검증하여 `api_catalog` 테이블에 작동 여부, 22대 데이터 보유 여부, 응답 row 수, `used_in_pipeline=TRUE`, `usage_note`를 기록한다. 미사용 API의 메타는 `.Seongjin/legacy_congress/국회 api.db`(SQLite)에 그대로 보존되어 향후 새 API 발견이 필요할 때 직접 조회한다. 회의록 본문 HTML은 OpenAPI가 아니라 별도 슬라이스(#8)에서 스크래핑 워커가 다룬다.
34. 시스템은 검증 결과를 `docs/API-CATALOG.md`로 자동 생성한다 (사람이 읽기용).
35. 시스템은 PM/운영자 관점의 공식 수집 명령 하나를 제공한다. 이 명령은 같은 적재 Module로 `backfill`과 `incremental` 실행 mode를 선택하고, 사용자가 의원/법안/표결/회의록 stage를 직접 조합하지 않아도 전체 수집을 끝낸다.
36. 시스템은 재실행 안전성을 보장한다. 이미 DB에 있는 의원, 법안, 표결, 회의, 회의-법안 연결, 회의록 발언, session_group은 중복 row를 만들지 않고 upsert 또는 대상 범위 재계산으로 갱신한다.
37. `backfill`은 2024-05-30부터 현재까지 전체 범위를 적재하고, `incremental`은 source별 cursor와 30일 overlap window로 신규/변경 가능 구간을 다시 upsert한다.
38. 시스템은 `members`를 매 run 전체 갱신한다. 의원 수가 작아 별도 cursor를 두지 않는다.
39. 시스템은 source별 cursor를 분리한다: `bills`는 `propose_dt`/`proc_dt`, `votes`는 `vote_date`, `meetings`는 `conf_date`, `utterances`와 `session_groups`는 touched `meeting_id` 목록을 기준으로 실행한다.
40. 시스템은 매 run 시작 시 unresolved dead letter를 먼저 재처리한다. 성공하면 `resolved`로 상태 변경하고 삭제하지 않는다.
41. 시스템은 API 호출 실패와 회의록 스크래핑 실패를 지수 backoff로 재시도하고, 지속 실패 시 `dead_letters`에 source, item key, payload, error, attempt 정보를 저장한다.
42. 시스템은 실패 item이 일부 있어도 성공한 데이터는 반영하고 run 상태를 `degraded_success`로 기록한다. 핵심 stage가 중단되면 `failed`, dead letter 누적이 임계값을 넘으면 `blocked`로 기록한다.
43. 시스템은 백필 완료를 단순한 스크립트 종료가 아니라 `dead_letters=0`, `validate-session-groups` integrity error 0, S1~S7 sanity 결과 review 가능, data-completeness 잔여 공백 expected/accepted 상태로 판단한다.
44. 시스템은 Supabase migration 후 초기 incremental runner를 로컬/별도 runner에서 실행해 Supabase DB에 직접 upsert한다.
45. 시스템은 병렬 워커 수를 5·20·50·100·200으로 변화시키며 측정해서 최적값을 결정한다. rate limit이 알려지지 않은 외부 API이므로, 에러율 1% 미만 후보 중 최고 처리량의 95% 이상을 내는 가장 낮은 워커 수를 선택한다. 측정 결과는 별도 문서로 보존한다.

### G. 인프라

46. 시스템은 Postgres 16을 OrbStack의 Docker 컨테이너로 로컬 실행한다.
47. 로컬 100% 백필 검증 완료 후 Supabase에 마이그레이션한다 (별도 슬라이스).
48. 모든 수집 코드는 Python(`psycopg`)로 작성한다. 레거시 SQLite 코드는 SQL 로직만 참조하고, DB 접근은 모두 새로 작성한다.

## Implementation Decisions

### 스키마 (상세는 `docs/ERD.md`)

- **9개 핵심 테이블**: `members`, `bills`, `bill_lead_proposers`, `bill_coproposers`, `votes`, `meetings`, `meeting_bills`, `utterances`, `session_groups` + 1개 카탈로그 `api_catalog`.
- **수집 운영 테이블**: `ingest_runs`, `ingest_cursors`, `dead_letters`.
- **자연키 우선**: `members.mona_cd`, `bills.bill_id`, `meetings.mnts_id`를 PK로 사용.
- **시점 데이터**: 의원의 시점 정당은 `votes.poly_nm_at_vote`, 시점 위원회는 `meetings.comm_name`. 별도 history 테이블 X.
- **junction 테이블**: `bill_lead_proposers` (대표발의), `bill_coproposers` (공동발의), `meeting_bills` (회의↔법안).
- **검색 지향 core schema**: PDF/VOD/요약 팝업 링크, upstream source 추적 필드, 공식 회의 안건 테이블은 core에서 제외한다.
- **soft delete 정책**: 첫 10% 로드 후 결정.

### 외부 API 사용 목록 (확정)

| 용도 | API | 비고 |
|---|---|---|
| 의원 인적사항 | `nwvrqwxyaytdsfvhu` | 286명 |
| 의원 위원회 경력 | (보류) | 위원회 이력 테이블 안 만듦 |
| 법안 목록 | `nzmimeepazxkubdpn` | DAE=22, ~17,000+ |
| 법안 주요내용 | `BPMBILLSUMMARY` | BILL_NO로 1:1 |
| 본회의 회의록 메타데이터 | `nzbyfwhwaoanttzje` | 웹 목록 `mnts_id`와 매칭되는 경우만 보강 |
| 위원회 회의록 메타데이터 | `ncwgseseafwbuheph` | 웹 목록 `mnts_id`와 매칭되는 경우만 보강 |
| 국정감사 회의록 메타데이터 | `VCONFAPIGCONFLIST` | 웹 목록 `mnts_id`와 매칭되는 경우만 보강 |
| 국정조사 회의록 메타데이터 | `VCONFPIPCONFLIST` | 웹 목록 `mnts_id`와 매칭되는 경우만 보강 |
| 인사청문회 회의록 메타데이터 | `VCONFCFRMCONFLIST` | 웹 목록 `mnts_id`와 매칭되는 경우만 보강 |
| 본회의 표결 | `nojepdqqaweusdfbi` | BILL_ID 단위 |
| 의안별 표결현황 | `ncocpgfiaoituanbr` | 표결된 BILL_ID 목록 |
| 의안별 회의록 목록 | `VCONFBILLCONFLIST` | BILL_ID 단위 |
| 회의록 웹 목록 | `record.assembly.go.kr/assembly/mnts/total/22.do` | HTML 회의록 대상의 canonical source |
| 회의록 본문 HTML | `record.assembly.go.kr/.../xml.do` | 웹 목록에서 얻은 mnts_id 단위 스크래핑 |

### API 호출 정책

- **User-Agent 필수** (없으면 Bad Request).
- **모든 API 호출은 wrapper 모듈을 거친다**: 대수 파라미터 형식 차이(`DAE_NUM=22` / `AGE=22` / `ERACO=제22대`)를 한 곳에서 흡수.
- **rate limit / backoff**: 지수 backoff (1→4→16초), 지속 실패 시 `dead_letters`에 저장.

### 수집 orchestration

- **동일 Module 재사용**: 2년치 백필 전용 코드와 증분 전용 코드를 따로 만들지 않는다. 기존 `ingest_*` Module을 재사용하고 실행 mode와 범위만 다르게 지정한다.
- **공식 진입점**: PM/운영자가 기억해야 하는 명령은 하나다. 이 명령은 백필인지 증분인지, 어떤 회의의 utterance/session_group을 다시 계산해야 하는지, 어떤 dead letter를 먼저 재시도해야 하는지를 내부에서 결정한다.
- **백필**: members → bills 100% → votes 100% → 웹 목록 기준 meetings 전체 + OpenAPI 메타데이터 보강 → meeting_bills → utterances 전체 → session_groups 전체 → validation/sanity/data-completeness 순으로 실행한다.
- **증분 동기화**: run 시작 시 dead_letters 재처리 → members 전체 갱신 → source별 cursor + 30일 overlap으로 bills/votes upsert → 웹 목록 기준 신규/변경 meetings 감지 + OpenAPI 메타데이터 보강 → touched meetings만 utterances 재스크래핑 → touched meetings만 session_groups 재계산.
- **불필요한 재스크래핑 방지**: 이미 발언이 적재된 기존 회의는 변경 감지 또는 명시적 재처리 대상이 아닌 한 utterance/session_group을 다시 긁지 않는다.
- **상태 기록**: 모든 실행은 `ingest_runs`에 기록하고, 성공한 source별 기준점은 `ingest_cursors`에 갱신한다.
- **실패 정책**: 일부 item 실패는 `degraded_success`로 기록하고 dead letter를 남긴다. 실패 item은 run 시작 시 우선 재처리한다.
- **회의록 canonical source**: OpenAPI 회의록 목록만으로 HTML 회의록 universe를 확정하지 않는다. `total/22.do` 웹 목록을 `meetings` 대상 기준으로 삼고, OpenAPI-only 회의는 core `meetings` 적재 대상이 아니라 coverage report에 남긴다.

### Q&A 그룹 알고리즘

- 레거시 `_find_nominations_mem` 기반: 의장이 의원을 호명 → 그 의원이 다음 발언자가 되는 패턴 감지.
- 적용 대상: 상임위/특별위 일반, 국정감사, 국정조사, 인사청문회.
- 제외 대상: 본회의, 소위원회.
- **10% 적재 시점에 알고리즘 정확도 검증** (별도 슬라이스).

### 회의록 식별자 통합

- 웹 목록과 HTML viewer URL의 `id` 파라미터 = `mnts_id` (정수).
- 본회의/위원회 API의 `CONFER_NUM`은 `mnts_id`와 매칭되는 경우 메타데이터 보강에 사용한다.
- 국감/국조/청문회 API의 `CONF_ID` (`N0xxxxx`)는 core 검색에는 쓰지 않는 원천 보조키로 간주한다.
- PDF/HWP는 utterance 추출에 사용하지 않고, core schema에 원본 링크도 보존하지 않는다.

## Testing Decisions

- **단위 테스트는 비즈니스 로직에만**: API 호출 wrapper, 웹 목록 파서, `SUB_NAME`에서 `meeting_bills` 후보를 추출하는 로직, 한자→한글 변환, session_group 감지 알고리즘.
- **integration test**: 실제 API 호출 → DB 적재 → 쿼리 시나리오(S1~S7) 검증.
- **회의록 DOM 검증**: 본문 스크래핑 전 회의 유형별 recent/old 샘플을 다층 검증하고, selector 계수·parse failure·HTTP 오류를 `docs/MINUTES-DOM-VALIDATION.md`에 남긴다.
- **회의록 웹 목록 DOM 계약**: `docs/MINUTES-WEB-LIST-DOM.md`에 6개 class 탭, 내부 async endpoint, 최종 `type=view` 링크 selector, 증분 재대조 전략을 남긴다.
- **회의록 웹 목록 coverage 검증**: `docs/MINUTES-WEB-COVERAGE.md`에 웹 목록 기준 `meetings` 적재 상태와 OpenAPI-only 후보를 남긴다. 웹 목록에 있지만 core `meetings` 또는 HTML utterances에 반영되지 않은 회의록은 migration blocker다.
- **회의록 session_group 검증 슬라이스**: 5종 회의 각 5~10건 샘플링, 자동 감지 결과를 수동 검토와 비교, precision/recall 측정. 임계값 미만이면 알고리즘 보강.
- **캘리브레이션 검증**: 초기 10% 적재는 산출물 목표가 아니라 전체 적재 전 병렬 수집 파라미터를 실측하는 단계다. 의원 286명 / 법안 1,700+건 / 회의 ~500건 / 표결 ~50,000건 / 발언 ~500,000건(실측 501,243건)을 먼저 적재해 S1~S7 쿼리, rate limit, worker별 처리량, 오버헤드 증가 지점을 확인한 뒤 100% 적재로 확장한다.
- **idempotent 재실행 테스트**: 같은 데이터를 두 번 적재해도 row 수가 변하지 않음 (ON CONFLICT 동작).
- **orchestration 테스트**: backfill/incremental planner가 같은 적재 Module을 호출하고, source별 cursor/30일 overlap/touched meeting/dead letter 상태 전이를 public interface로 검증한다.

## Out of Scope

- **위원회 단계 표결** (API에 없음, 회의록 추출은 정밀도 낮음)
- **22대 이전 데이터** (의원의 21대 이력은 텍스트로만 — `members.units`)
- **본회의·소위 Q&A 그룹** (안건 분해 불가, 자유 토론 형식)
- **공식 회의 안건 원문 테이블** (`agenda_items`) — 법안 연결은 `meeting_bills`, 정책 주제는 향후 의미 레이어에서 다룸
- **회의록 raw HTML 저장** (utterance만 저장, 재 fetch 가능)
- **PDF/HWP·영상 다운로드 및 파싱**
- **PDF/VOD/요약 팝업 링크의 core schema 보존**
- **검색 API/SDK 구현** (별도 세션. 본 PRD는 DB 적재까지)
- **Supabase 마이그레이션 실행** (로컬 100% 백필 readiness 승인 후 별도 슬라이스)
- **member_committees·member_terms 테이블** (PM 결정)
- **vote_summaries 캐시 테이블** (PM 결정, GROUP BY 즉시 계산)
- **263개 미사용 API 검증** (ROI 낮음, [docs/adr/0001-api-catalog-scope.md](docs/adr/0001-api-catalog-scope.md) 참고)
- **매일 일괄 검증 스크립트**
- **개인정보 마스킹** (의원의 공개 정보만 다루므로 불요)

## Further Notes

- **레거시 참조**: `.Seongjin/legacy_congress/`의 `fetch_bills.py`, `fetch_meetings.py`, `scrape_minutes.py`의 **SQL 로직만** 참조. DB 접근은 새로 작성 (SQLite → Postgres dialect 변환).
- **언어**: Python 3.11+, `psycopg[binary,pool]`, `requests`, `beautifulsoup4`, `hanja`.
- **개발 환경**: OrbStack의 Postgres 16 컨테이너 (`postgres:16-alpine`).
- **마지막 의사결정 정리는 `CONTEXT.md`, `docs/ERD.md`, `docs/IA.md`에 분산.**
