# PRD — 22대 국회 통합 데이터베이스

> 본 문서는 GitHub Issue로 발행되어 `ready-for-agent`로 분류된다. AGENT-BRIEF는 슬라이스 분해 후 각 자식 issue에 별도 작성.

## Problem Statement

국회 OpenAPI는 277개에 달하지만 다수가 서로 중복되거나, 더 이상 갱신되지 않거나, 필요한 정보가 흩어져 있어 단일 의원을 키로 그 활동 전반을 조회할 수 없다.

PM(비개발자)이 의정 활동을 분석할 때마다 매번 여러 API를 직접 조합해야 해 시간 소요와 오류가 크다. 향후 검색 API/SDK를 만들려면 정규화된 통합 DB가 선행되어야 한다.

회의록은 utterance 단위로 흩어져 있고, "본회의의 안건"이 본문에서 분리되지 않아 의미 단위 검색이 곤란하다. 다양한 회의 유형(본회의·상임위·국정감사·국정조사·인사청문회·소위)을 단일 스키마로 통합하고, 가능한 회의에서는 Q&A 그룹을 자동 감지해야 한다.

## Solution

10개 핵심 테이블 + 1개 카탈로그 테이블로 구성된 Postgres 16 DB를 구축한다. 22대 임기(2024-05-30~) 데이터에 한정하며, 매일 incremental 수집(초기에는 수동, 10% 검증 후 자동화 결정).

핵심 가치:
1. **한 의원 ID로 발의·표결·발언 통합 조회** — SQL JOIN 한 줄.
2. **회의록 5종 통합 스키마** — meeting_type enum으로 출처 구분.
3. **Q&A 그룹 자동 감지** — 가능한 회의에 적용.
4. **API 카탈로그 — 우리가 쓰는 10개 OpenAPI의 작동 검증 + 메타 문서화** (HTML 스크래핑은 별도).

최종 적재 후 Supabase로 마이그레이션. 본 PRD는 마이그레이션 전 10% 데이터 검증까지를 범위로 한다.

## User Stories

### A. 데이터 수집·적재 (시스템 동작)

1. 시스템은 22대 의원 ~286명의 인적사항을 API `nwvrqwxyaytdsfvhu`에서 가져와 `members` 테이블에 적재한다.
2. 시스템은 22대 발의된 법안 ~17,000+건을 API `nzmimeepazxkubdpn`에서 페이지네이션으로 받아 `bills` 테이블에 적재한다.
3. 시스템은 각 법안의 주요내용을 API `BPMBILLSUMMARY`에서 병렬로 받아 `bills.summary`에 저장한다.
4. 시스템은 법안의 대표발의자 코드(`RST_MONA_CD`)와 공동발의자 코드(`PUBL_MONA_CD`)를 콤마로 split 하여 각각 `bill_lead_proposers`, `bill_coproposers` N:M 테이블에 row 단위로 정규화한다. 원본 텍스트는 `bills.rst_proposer`, `bills.publ_proposer`, `bills.proposer`에도 보존한다.
5. 시스템은 22대 본회의·상임위·특별위·국정감사·국정조사·인사청문회 회의록을 5개 별도 API에서 받아 `meetings`에 단일 테이블로 통합 저장한다. `meeting_type` 컬럼으로 출처를 구분한다.
6. 시스템은 본회의 표결 결과를 API `nojepdqqaweusdfbi`에서 의안 단위로 받아 `votes` 테이블에 저장한다. 표결 시점의 정당명은 `poly_nm_at_vote`에 박는다.
7. 시스템은 의안별 회의록 매핑을 API `VCONFBILLCONFLIST`로 받아 `meeting_bills` junction에 저장한다.
8. 시스템은 회의록 본문을 `record.assembly.go.kr` HTML에서 스크래핑해 utterance 단위로 `utterances` 테이블에 저장한다. 한자 이름은 한글로 정규화한다.
9. 시스템은 회의록 본문의 의장 호명 패턴을 감지해 Q&A 그룹(`session_groups`)을 자동 생성하되, **본회의와 소위원회는 적용하지 않는다**.
10. 시스템은 안건 목록(`SUB_NAME`)을 row 단위로 풀어 `agenda_items`에 적재하고, 안건이 법안일 경우 `bill_id`로 매핑한다.
11. 시스템은 모든 INSERT를 `ON CONFLICT DO UPDATE`로 idempotent 하게 처리하여 재실행 안전성을 보장한다.
12. 시스템은 모든 테이블에 `fetched_at` 컬럼을 두어 마지막 수집 시각을 기록한다.

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
26. 사용자는 한 회의의 안건 목록 전체를 `agenda_items`에서 조회할 수 있다.
27. 사용자는 한 회의의 발언 stream을 `utterances`에서 `sequence` 순으로 조회할 수 있다.
28. 사용자는 한 회의의 Q&A 그룹 목록(있다면)을 `session_groups`에서 조회할 수 있다.
29. 사용자는 위원회 단위(예: '국방위원회')로 그 위원회의 모든 회의를 `meetings.comm_name`으로 조회할 수 있다.

### E. 검색 시나리오 (FTS)

30. 사용자는 발언 본문에서 키워드(예: '전세사기')를 포함한 발언과 그 회의를 검색할 수 있다.
31. 사용자는 법안 주요내용(`summary`) 본문에서 키워드를 검색할 수 있다.
32. 시스템은 10% 데이터 적재 시점에 한국어 FTS 방식(`pg_trgm` vs `pgroonga` vs 기타)을 비교 후 결정한다.

### F. 운영 (Operation)

33. 시스템은 PRD에 명시된 10개 사용 확정 OpenAPI(아래 "외부 API 사용 목록" 표 중 회의록 본문 HTML 행 제외)의 작동을 1회 검증하여 `api_catalog` 테이블에 작동 여부, 22대 데이터 보유 여부, 응답 row 수, `used_in_pipeline=TRUE`, `usage_note`를 기록한다. 나머지 약 267개 미사용 API의 메타는 `.Seongjin/legacy_congress/국회 api.db`(SQLite)에 그대로 보존되어 향후 새 API 발견이 필요할 때 직접 조회한다. 회의록 본문 HTML은 OpenAPI가 아니라 별도 슬라이스(#8)에서 스크래핑 워커가 다룬다.
34. 시스템은 검증 결과를 `docs/API-CATALOG.md`로 자동 생성한다 (사람이 읽기용).
35. 시스템은 매일 신규/변경 데이터를 incremental 수집한다 (초기에는 수동 트리거, 10% 검증 후 자동화 결정).
36. 시스템은 API 호출 실패 시 지수 backoff로 재시도하고 (1→4→16초), 3회 실패 시 `dead_letter` 테이블로 이동시킨다 (10% 검증 후 정책 확정).
37. 시스템은 병렬 워커 수를 5·20·50·100·200으로 변화시키며 측정해서 최적값을 결정한다. rate limit이 알려지지 않은 외부 API이므로, 에러율 1% 미만 후보 중 최고 처리량의 95% 이상을 내는 가장 낮은 워커 수를 선택한다. 측정 결과는 별도 문서로 보존한다.

### G. 인프라

38. 시스템은 Postgres 16을 OrbStack의 Docker 컨테이너로 로컬 실행한다.
39. 10% 데이터 검증 완료 후 Supabase에 마이그레이션한다 (별도 슬라이스).
40. 모든 수집 코드는 Python(`psycopg`)로 작성한다. 레거시 SQLite 코드는 SQL 로직만 참조하고, DB 접근은 모두 새로 작성한다.

## Implementation Decisions

### 스키마 (상세는 `docs/ERD.md`)

- **10개 핵심 테이블**: `members`, `bills`, `bill_lead_proposers`, `bill_coproposers`, `votes`, `meetings`, `agenda_items`, `meeting_bills`, `utterances`, `session_groups` + 1개 카탈로그 `api_catalog`.
- **자연키 우선**: `members.mona_cd`, `bills.bill_id`, `meetings.mnts_id`를 PK로 사용.
- **시점 데이터**: 의원의 시점 정당은 `votes.poly_nm_at_vote`, 시점 위원회는 `meetings.comm_name`. 별도 history 테이블 X.
- **junction 테이블**: `bill_lead_proposers` (대표발의), `bill_coproposers` (공동발의), `meeting_bills` (회의↔법안).
- **soft delete 정책**: 첫 10% 로드 후 결정.

### 외부 API 사용 목록 (확정)

| 용도 | API | 비고 |
|---|---|---|
| 의원 인적사항 | `nwvrqwxyaytdsfvhu` | 286명 |
| 의원 위원회 경력 | (보류) | 위원회 이력 테이블 안 만듦 |
| 법안 목록 | `nzmimeepazxkubdpn` | DAE=22, ~17,000+ |
| 법안 주요내용 | `BPMBILLSUMMARY` | BILL_NO로 1:1 |
| 본회의 회의록 | `nzbyfwhwaoanttzje` | DAE_NUM=22, CONF_DATE 연도별 |
| 위원회 회의록 | `ncwgseseafwbuheph` | DAE_NUM=22, CONF_DATE 연도별 |
| 국정감사 회의록 | `VCONFAPIGCONFLIST` | ERACO=제22대 |
| 국정조사 회의록 | `VCONFPIPCONFLIST` | ERACO=제22대 |
| 인사청문회 회의록 | `VCONFCFRMCONFLIST` | ERACO=제22대 |
| 본회의 표결 | `nojepdqqaweusdfbi` | BILL_ID 단위 |
| 의안별 회의록 목록 | `VCONFBILLCONFLIST` | BILL_ID 단위 |
| 회의록 본문 HTML | `record.assembly.go.kr/.../xml.do` | mnts_id 단위, 스크래핑 |

### API 호출 정책

- **User-Agent 필수** (없으면 Bad Request).
- **모든 API 호출은 wrapper 모듈을 거친다**: 대수 파라미터 형식 차이(`DAE_NUM=22` / `AGE=22` / `ERACO=제22대`)를 한 곳에서 흡수.
- **rate limit / backoff**: 지수 backoff (1→4→16초), 3회 실패 시 dead_letter.

### Q&A 그룹 알고리즘

- 레거시 `_find_nominations_mem` 기반: 의장이 의원을 호명 → 그 의원이 다음 발언자가 되는 패턴 감지.
- 적용 대상: 상임위/특별위 일반, 국정감사, 국정조사, 인사청문회.
- 제외 대상: 본회의, 소위원회.
- **10% 적재 시점에 알고리즘 정확도 검증** (별도 슬라이스).

### 회의록 식별자 통합

- 본회의/위원회 API의 `CONFER_NUM` = 회의록 PDF URL의 id = `mnts_id` (정수).
- 국감/국조/청문회 API의 `CONF_ID` (`N0xxxxx`) = 별도 식별자 (nullable 컬럼으로 보존).
- 모든 출처를 `mnts_id`로 통합 (PDF URL에서 추출).

## Testing Decisions

- **단위 테스트는 비즈니스 로직에만**: API 호출 wrapper, 한자→한글 변환, agenda_items의 bill_no 추출, session_group 감지 알고리즘.
- **integration test**: 실제 API 호출 → DB 적재 → 쿼리 시나리오(S1~S7) 검증.
- **회의록 session_group 검증 슬라이스**: 5종 회의 각 5~10건 샘플링, 자동 감지 결과를 수동 검토와 비교, precision/recall 측정. 임계값 미만이면 알고리즘 보강.
- **10% 검증**: 의원 286명 / 법안 1,700+건 / 회의 ~500건 / 표결 ~50,000건 / 발언 ~300,000건 적재 후 S1~S7 쿼리가 정상 동작 + 시각적 sanity check.
- **idempotent 재실행 테스트**: 같은 데이터를 두 번 적재해도 row 수가 변하지 않음 (ON CONFLICT 동작).

## Out of Scope

- **위원회 단계 표결** (API에 없음, 회의록 추출은 정밀도 낮음)
- **22대 이전 데이터** (의원의 21대 이력은 텍스트로만 — `members.units`)
- **본회의·소위 Q&A 그룹** (안건 분해 불가, 자유 토론 형식)
- **회의록 raw HTML 저장** (utterance만 저장, 재 fetch 가능)
- **PDF·영상 다운로드** (URL만 메타데이터로 보존)
- **검색 API/SDK 구현** (별도 세션. 본 PRD는 DB 적재까지)
- **Supabase 마이그레이션** (10% 검증 완료 후 별도 슬라이스)
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
