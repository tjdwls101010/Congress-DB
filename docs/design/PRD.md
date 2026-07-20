# PRD — 22대 국회 통합 데이터베이스

> 본 문서는 GitHub Issue로 발행되어 `ready-for-agent`로 분류된다. AGENT-BRIEF는 슬라이스 분해 후 각 자식 issue에 별도 작성.

## Problem Statement

국회 OpenAPI는 277개에 달하지만 다수가 서로 중복되거나, 더 이상 갱신되지 않거나, 필요한 정보가 흩어져 있어 단일 의원을 키로 그 활동 전반을 조회할 수 없다.

PM(비개발자)이 의정 활동을 분석할 때마다 매번 여러 API를 직접 조합해야 해 시간 소요와 오류가 크다. 향후 스킬, AI agent, 개발자가 안전하게 직접 SQL을 쓰려면 정규화되고 자기설명적인 통합 DB가 선행되어야 한다.

> 회의·발언(회의록 utterance) 도메인은 2026-06-28 마이그레이션(031)으로 제거됐다. 발언 본문의 "누가 무엇을 말했나" 심층 분석은 websearch로 이관하고, 심의 진행·상태는 구조화 테이블(`bills.proc_result`·`bill_lineage`·`bill_final_outcomes`)로 답한다. 상세는 [DECISIONS.md](DECISIONS.md)(2026-06-28).

## Solution

핵심 fact 테이블, N:M junction, 검색 함수, 수집 운영 상태 테이블로 구성된 Postgres 16 DB를 구축한다. 22대 임기(2024-05-30~) 데이터에 한정하며, 같은 적재 Module로 초기 전체 백필과 이후 증분 동기화를 모두 처리한다.

핵심 가치:
1. **한 의원 ID로 발의·표결 통합 조회** — SQL JOIN 한 줄.
4. **API 카탈로그 — 우리가 쓰는 OpenAPI의 작동 검증 + 메타 문서화** (HTML 스크래핑은 별도).

향후 스킬/분석 도구는 이 공식 근거 DB 위에 정책 의제/입장 레이어를 얹는다. 예: 어떤 의원의 의제가 무엇인지, 어떤 의원이 어떤 의제에 어떤 입장인지, 어떤 의제에 어떤 법안이 있고 국회에서 어떻게 논의되어 왔는지.

로컬에서 100% 백필과 검증을 완료한 뒤 hosted Postgres로 마이그레이션한다. 현재 1차 타깃은 Neon이며, 전환 후에는 로컬/별도 runner가 hosted Postgres DB에 직접 증분 upsert한다.

## User Stories

### A. 데이터 수집·적재 (시스템 동작)

1. 시스템은 22대 의원 ~286명의 인적사항을 API `nwvrqwxyaytdsfvhu`에서 가져와 `members` 테이블에 적재한다.
2. 시스템은 22대 발의된 법안 ~17,000+건을 API `nzmimeepazxkubdpn`에서 페이지네이션으로 받아 `bills` 테이블에 적재한다.
3. 시스템은 각 법안의 주요내용을 API `BPMBILLSUMMARY`에서 병렬로 받아 `bills.summary`에 저장한다.
4. 시스템은 법안의 대표발의자 코드(`RST_MONA_CD`)와 공동발의자 코드(`PUBL_MONA_CD`)를 콤마로 split 하여 각각 `bill_lead_proposers`, `bill_coproposers` N:M 테이블에 row 단위로 정규화한다. 대표/공동발의자 정본은 이 두 junction 테이블이며, 원천 제안자 문구 중 join으로 복원할 수 없는 정보는 `bills.proposer_raw` raw 텍스트로 보존한다.
6. 시스템은 본회의 표결 결과를 API `nojepdqqaweusdfbi`에서 의안 단위로 받아 `votes` 테이블에 저장한다. 표결 시점의 정당명은 `poly_nm_at_vote`에 박는다.
11. 시스템은 모든 INSERT를 `ON CONFLICT DO UPDATE`로 idempotent 하게 처리하여 재실행 안전성을 보장한다.
12. 시스템은 수집 대상 core 테이블에 `fetched_at` 컬럼을 두어 마지막 수집 시각을 기록한다.

### B. 의원 (Member) 조회 시나리오

13. 사용자는 의원 이름(예: '강대식')으로 `members` 테이블에서 해당 의원의 `mona_cd`와 기본정보를 조회할 수 있다.
14. 사용자는 한 의원의 대표발의 법안 전체를 `bill_lead_proposers` 정규화 테이블 JOIN으로 조회할 수 있다.
15. 사용자는 한 의원의 공동발의 법안 전체를 `bill_coproposers` 정규화 테이블 JOIN으로 조회할 수 있다.
16. 사용자는 한 의원의 본회의 표결 이력을 `votes` 테이블 JOIN으로 조회할 수 있다.

### C. 법안 (Bill) 조회 시나리오

19. 사용자는 법안 이름의 부분 일치(예: '항공안전법')로 법안을 검색할 수 있다.
20. 사용자는 한 법안의 처리 과정(발의일·위원회·본회의·처리결과·처리일)을 `bills` 한 row로 조회할 수 있다.
21. 사용자는 한 법안의 공동발의자 명단을 `bill_coproposers` JOIN으로 조회할 수 있다.
22. 사용자는 한 법안의 본회의 표결 결과(표결당 ~285~300명, 의원별)를 `votes` JOIN으로 조회할 수 있다.
23. 사용자는 한 법안의 표결 집계(찬·반·기·불참)를 `votes` GROUP BY로 즉시 계산할 수 있다 (별도 캐시 테이블 없이).

### E. 검색 시나리오 (한국어 키워드 검색)

31. 사용자는 법안 주요내용(`summary`) 본문에서 키워드를 검색할 수 있다.
32. 시스템은 10% 데이터 적재 시점에 한국어 검색 방식(`pg_trgm` vs `pgroonga` vs 기타)을 비교 후 결정한다.

### F. 운영 (Operation)

33. 시스템은 PRD에 명시된 사용 확정 OpenAPI(아래 "외부 API 사용 목록" 표)를 `congress_db/core/endpoints.py` 상수와 endpoint별 수집 Module에 보존한다. `api_catalog` 테이블은 삭제됐고, 미사용 API의 메타는 repo에 보존하지 않는다. 향후 새 API가 필요해지는 시점에 국회 OpenAPI 목록에서 수동 조회·검증해 코드 상수와 문서를 갱신한다.
34. 시스템은 현재 파이프라인 endpoint 목록을 `docs/ops/API-CATALOG.md`로 자동 생성한다 (사람이 읽기용).
35. 시스템은 PM/운영자 관점의 공식 수집 명령 하나를 제공한다. 이 명령은 같은 적재 Module로 `backfill`과 `incremental` 실행 mode를 선택하고, 사용자가 의원/법안/표결 stage를 직접 조합하지 않아도 전체 수집을 끝낸다.
36. 시스템은 재실행 안전성을 보장한다. 이미 DB에 있는 의원, 법안, 표결은 중복 row를 만들지 않고 upsert 또는 대상 범위 재계산으로 갱신한다.
37. `backfill`은 2024-05-30부터 현재까지 전체 범위를 적재하고, `incremental`은 싼 목록 endpoint를 매번 전체 재스캔해 신규·뒤늦은 변경(처리결과·정정 포함)을 upsert하되, 한 번 확정되면 안 바뀌는 항목(법안 summary·표결 상세)은 이미 있으면 다시 받지 않는다. *(이전 'source별 cursor + 30일 overlap window' 설계 폐기 — DECISIONS 2026-06-04 / 이슈 #46.)*
38. 시스템은 `members`를 매 run 전체 갱신한다. 의원 수가 작아 별도 cursor를 두지 않는다.
39. 시스템은 source별 cursor를 분리하되 fetch 범위 결정에는 쓰지 않는다. `bills`, `votes` cursor는 각 source의 마지막 성공 시점을 관찰·감사하기 위한 `last_success_at` 기준점이다. *(개정 2026-06-04 — 이슈 #46/#54.)*
40. 시스템은 매 run 시작 시 unresolved dead letter를 먼저 재처리한다. 성공하면 `resolved`로 상태 변경하고 삭제하지 않는다.
41. 시스템은 API 호출 실패를 지수 backoff로 재시도하고, 지속 실패 시 `dead_letters`에 source, item key, payload, error, attempt 정보를 저장한다.
42. 시스템은 실패 item이 일부 있어도 성공한 데이터는 반영하고 run 상태를 `degraded_success`로 기록한다. 핵심 stage가 중단되면 `failed`, dead letter 누적이 임계값을 넘으면 `blocked`로 기록한다.
43. 시스템은 백필 완료를 단순한 스크립트 종료가 아니라 `dead_letters=0`, S1~S7 sanity 결과 review 가능, data-completeness 잔여 공백 expected/accepted 상태로 판단한다.
44. 시스템은 hosted Postgres migration 전 깨끗한 로컬 DB에서 100% 백필을 실행하고 CLI progress, stage duration, retry, row count, dead letter, generated report를 관찰해 비정상 신호를 고친 뒤 idempotency 재실행까지 통과해야 한다.
45. 시스템은 hosted Postgres migration 후 초기 incremental runner를 로컬/별도 runner에서 실행해 hosted Postgres DB에 직접 upsert한다.
46. 시스템은 병렬 워커 수를 5·20·50·100·200으로 변화시키며 측정해서 최적값을 결정한다. rate limit이 알려지지 않은 외부 API이므로, 에러율 1% 미만 후보 중 최고 처리량의 95% 이상을 내는 가장 낮은 워커 수를 선택한다. 측정 결과는 별도 문서로 보존한다.

### G. 인프라

47. 시스템은 Postgres 16을 OrbStack의 Docker 컨테이너로 로컬 실행한다.
48. 로컬 100% 백필 hardening gate 완료 후 Neon hosted Postgres에 staging 마이그레이션한다 (별도 슬라이스).
49. 모든 수집 코드는 Python(`psycopg`)로 작성한다. 레거시 SQLite 코드는 SQL 로직만 참조하고, DB 접근은 모두 새로 작성한다.

### H. 정제 확장 (M2 — 적재 신뢰도 심화)

> 진단(2026-06-05) 반영. 이 DB가 "사실의 출처"를 넘어 "법안 제안의 근거"로 쓰이려면 닫아야 하는 결함. 하이브리드 진행(M0/M1 후 직접 SQL 소비 준비와 병행). 상세 DECISIONS 2026-06-05. 소스 API·매핑은 각 슬라이스 그릴링에서 확정한다.

50. 시스템은 *대안반영폐기*(3,676건)·*수정안반영폐기*(39건)된 원안과 그 내용을 흡수한 **대안/수정안** source key의 연결을 `bill_relations`(absorbed_bill_id → alternative_bill_id, relation_type)에 적재한다. 이 관계는 국회 OpenAPI에 필드로 없어(발의·ALLBILL·위원회안대안 API 직접 확인) 의안정보시스템(likms) `billDetail.do`의 `selRefBillId` 숨은 필드를 스크래핑해 ~100% 권위 적재한다 (DECISIONS 2026-06-06; 표본 10/10 정확). `absorbed_bill_id`는 기존 `bills` FK로 강제하지만, `alternative_bill_id`는 일부 위원회 대안이 `bills`에 없고 수정안 source key는 상세페이지가 없는 것으로 확인되어 FK로 강제하지 않는다(DECISIONS 2026-06-06). 소비자 표면은 **`bill_lineage` 뷰**다 — raw `bill_relations`·`bill_source_aliases`는 `congress_ro`에서 REVOKE(ETL-internal)하고 뷰가 direct+alias 해소와 `relation_type` 파생을 캡슐화한다(`relation_type` 물리 컬럼은 ETL 사용으로 KEEP; #125, DECISIONS 2026-06-14).
51. 시스템은 요약이 비어 있는 법안(현재 1,068건, 그중 통과 (대안) 741건)의 제안이유·주요내용을 `BPMBILLSUMMARY`(BILL_NO 단위)로 백필한다. 표결 경로로 적재돼 발의-목록 기반 요약 호출에서 누락된 것으로, API가 이들 요약을 정상 반환함을 확인.

### I. 호스팅 연속운영 (M1 — Neon 위 지속 동기화)

> "여러 사람이 계속 갱신되는 DB를 조회"하려면 필요한 운영 견고성. 로컬 1회 적재엔 불필요했던 부분.

54. 시스템은 외부 API의 rate limit(HTTP 429)을 인식·존중하고 전역 동시성 상한을 둔다 (현재 429 미처리, sleep=0, 워커 100~200).
55. 시스템은 읽기 트래픽용 커넥션 풀링을 둔다 (Neon -pooler, psycopg pool; 현재 호출마다 연결 생성·종료).
56. 증분 동기화는 원본에서 삭제·철회된 행을 정리하고(현재 backfill에서만 정리), dead letter 자동 재처리를 전 source로 확장한다.
57. 시스템은 의원 인적사항 API(현직 명부)에 등장하면 `members.is_incumbent=TRUE`, 없으면 FALSE로 매 동기화 때 자동 갱신한다. 사퇴·상실 등으로 떠난 의원의 행과 기록은 삭제하지 않는다(`ON DELETE RESTRICT`).
58. 사용자는 `is_incumbent`로 현직/비현직 의원을 구분해 조회할 수 있다(예: 현직 의원만 검색).

### J. 소비 적합성·연결 표면 (M3 — 입법전문가 스킬 직접-SQL 소비 준비)

> 4-페르소나 분석(2026-06-11, demand/connect/source/critic, 라이브 Neon)에서 도출. 핵심 원칙: #82~86 이후 DB는 '사실 결핍'보다 '소비 포장·과잉주장 방지'가 갭이며, 추가 [1] 작업은 추측이 아니라 4-시나리오 regression pack + 스킬 프로토타입의 실제 쿼리 실패가 정한다(DECISIONS 2026-06-11). 모든 항목은 경계 태그 [1 congress-db]/[3 법제처]/[4 스킬 레이어]로 분리하며, 아래는 [1]만 담는다. 큰 [1]은 prototype-gated.

59. **[gate]** 시스템은 4개 앵커 시나리오(전세사기·의대정원·AI 기본법·채상병 특검)에 대해 스킬이 던질 핵심 질의의 회수 기준(canonical bill_no, 통과/공포 수, 역할 분포, 알려진 [3]/[4] 한계)을 schema 변경 없이 읽기전용 SQL regression/ops 리포트로 고정한다. 이후 모든 DB 변경은 이 pack의 기준에 정박한다.
60. 시스템은 법률안 vs 비-법률 의안(감사요구안·수사요구안·규칙안·결의안·동의안·승인안) 구분을 **쿼리가이드 caveat + 파생 뷰**로 제공한다(`bill_name`에 법률안·특별법안·특별조치법안·전부개정법률안 등이 들어가면 법률안). 원천에 의안종류 필드가 없어 이름 기반 파생이며, **저장 컬럼 `bill_kind`로의 승격은 스킬 프로토타입이 반복 오도출을 입증한 뒤로 미룬다**(소비자가 이름을 읽어 스스로 판단 가능 → materialize 아닌 inform). 〔2026-06-11 소비-원칙 감사〕
61. 시스템은 공포 bridge 완전성의 *사실*(공포일 있으나 `prom_law_nm` 결측 66건=`공포O+법률명X`, 비-법률 의안의 공포 부재=`비대상`, 미처리=`pending`)을 **파생 뷰 + 쿼리가이드 caveat**로 노출해 "공포 없음=정상 vs 결측"을 구분한다. 관계에서 파생되는 사실이라 denormalized 저장 원장 컬럼으로 굳히지 않는다. 법률명 이름-유도는 source 아닌 candidate로만. 〔2026-06-11 소비-원칙 감사〕
63. 시스템은 원안→대안→공포 lifecycle과 법률군 계보(lineage)를 우선 query-guide 레시피 + regression 단언으로 고정하고, materialized view 승격은 스킬 프로토타입이 반복·오류나는 join임을 입증한 뒤로 미룬다(prototype-gated, blocked by #59).
65. 시스템은 bill-side 위원회/소관 기관 연결을 `committees(committee_id, committee_name)` dimension으로 정규화한다. `bills.committee_id`가 이미 존재하고, 2026-06-13 Neon main 감사에서 31개 `committee_id -> committee` pair가 1:1(충돌 0)로 확인되어 #120에서 `committees`를 backfill하고 `bills.committee_id` FK를 건 뒤 중복 display column인 `bills.committee`를 제거했다. membership(누가 어느 위원)은 명부 API(`nktulghcadyhmiqxi`) 전체·안정 회수를 검증하는 슬라이스가 통과한 뒤에만 적재하며, 검증 시 `member_committees` 제외 결정을 공식 재검토한다. 〔2026-06-13 #117 결정으로 2026-06-11 '새 canonical 테이블 없음' 판단 supersede〕
66. **[prototype-gated — 2026-06-12 적재 후 demand 미입증으로 되돌림; DECISIONS 2026-06-12]** 시스템은 법안 문서 inventory(`bill_documents`)를 `BILLRCPV2`의 `BILL_ID` 키 원문(`BOOK_*`)/비용추계(`COST_*`) URL로 둔다. URL만 저장하고 HWP/PDF 본문 파싱은 하지 않는다(out-of-scope 유지). **스킬 프로토타입이 문서 링크 수요를 입증하기 전까지는 적재하지 않는다**(신규 소스=Tier C는 demand-gated).
67. ~~OpenAPI 후보 카탈로그를 source-discovery 원장으로 복원~~ — **소비 라운드에서 제외(ops 백로그로 이관)**. `api_catalog`는 입법전문가 스킬이 SQL로 조회하지 않는 ingestion/ops 메타데이터이고, 2026-05-26 'lazy 카탈로그 성장' 결정과 충돌한다. source-discovery가 필요하면 별도 PM-facing ops 작업으로 다룬다. 〔2026-06-11 소비-원칙 감사〕
68. **[prototype-gated]** 시스템은 청원 접수·심사 사실(`petitions`, 22대 302건, `PTT_ID` 키)을 둔다 — 스킬 프로토타입이 청원 데이터 수요를 입증한 뒤 적재(story 63과 동일 규율). 가능한 경우 `BILL_NO`와 연결하되 청원은 별개 엔터티로 유지하고, `CITZN_AGM_CNT`를 여론 대표성으로 단정하지 않는다(해석은 [4]). 〔2026-06-11 소비-원칙 감사〕
70. **[prototype-gated]** 시스템은 입법예고 메타(`bill_legislative_notices`, `BILL_NO` 키, `notice_status`·`notice_end_dt`·`committee`·`link_url`)를 얇게 둔다(종료 17,708 + 진행중) — 스킬 프로토타입이 수요를 입증한 뒤. 제출 의견 본문은 API 확인 전까지 범위 밖이다. 〔2026-06-11 소비-원칙 감사〕

### K. 스키마 정리 2차 (M3 cleanup — 삭제·숨김 후보 구현)

> 2026-06-13 감사 반영. PM 결정: 실제로 불필요한 schema surface는 숨기지 말고 삭제한다. 단, 수집 운영에는 필요하지만 스킬 소비에는 노이즈인 필드는 권한/view로 숨긴다.

71. 시스템은 대표발의 정본을 `bill_lead_proposers`로 일원화하고, 단일 대표발의에서만 맞고 다중 대표발의에서는 NULL인 `bills.rst_mona_cd`와 그 전용 인덱스를 제거한다.
72. 시스템은 본회의 표결 row identity를 현재 grain인 `(bill_id, mona_cd)`로 고정하고, 별도 public 의미가 없는 `votes.id` surrogate key를 제거한다. 같은 법안에 여러 표결 이벤트를 저장해야 한다는 실제 source 요구가 발견되면 이 작업은 중단하고 별도 `vote_events` 설계로 분리한다.
73. 시스템은 `congress_ro` 권한을 broad grant가 아니라 consumer surface allowlist로 고정한다. 운영 테이블(`ingest_runs`, `ingest_cursors`, `dead_letters`)은 물리 유지하되, role script를 재실행해도 스킬 계정에 노출되지 않아야 한다.
75. 시스템은 `bill_final_outcomes.bill_no -> bills.bill_no`처럼 실제 관계가 있지만 FK로 드러나지 않은 관계를 보강하고, 소비자에게 보이는 컬럼 중 COMMENT가 없는 고위험 필드에 의미/함정 설명을 추가한다.
76. 시스템은 `fetched_at`, `proc_result`, `cmt_proc_result`, `law_proc_dt`, `bill_source_aliases`를 이번 삭제 범위에서 제외한다. `bills.committee`는 #120에서 `committees` dimension으로 정규화 후 제거했고, 과거 `bills.proposer` 컬럼명은 #121에서 `bills.proposer_raw`로 rename했다.
77. 시스템은 `bills.committee`를 바로 삭제하지 않고, `committees` dimension을 먼저 만들고 current `bills.committee_id + bills.committee` 값을 보존한 뒤 삭제한다(#120 구현). migration은 id/name 충돌이 있으면 중단해야 하며, `committees`는 committee membership/history가 아니라 bill-side 소관 위원회/기관 이름 정본임을 COMMENT로 알려야 한다.
78. 시스템은 원천 제안자 문구를 삭제하지 않고, 과거 `bills.proposer` 컬럼명을 `bills.proposer_raw`로 rename한다(#121). `bill_lead_proposers` / `bill_coproposers`는 member identity 정본이고, `proposer_raw`는 `외 N인` 등 join으로 복원되지 않는 원천 문구라는 차이를 schema/comment/test/docs에 고정한다. rename 후 `bills.proposer` 컬럼은 존재하지 않는다.

## Implementation Decisions

### 스키마 (상세는 `ERD.md`)

- **핵심 fact/junction 테이블**: `members`, `bills`, `bill_lead_proposers`, `bill_coproposers`, `votes`, `bill_relations`, `bill_source_aliases`, `bill_final_outcomes`.
- **수집 운영 테이블**: `ingest_runs`, `ingest_cursors`, `dead_letters`.
- **자연키 우선**: `members.mona_cd`, `bills.bill_id`를 PK로 사용.
- **시점 데이터**: 의원의 시점 정당은 `votes.poly_nm_at_vote`. 의원별 위원회 membership/history는 현재 DB 범위 밖이다. 별도 history 테이블 X. **현직 여부**는 `members.is_incumbent`(명부 동기화에서 파생)로 표시하되, 이 역시 별도 상태 테이블 없이 단일 BOOLEAN으로 둔다.
- **junction 테이블**: `bill_lead_proposers` (대표발의), `bill_coproposers` (공동발의).
- **삭제 우선 cleanup 원칙**: 정본 구조에서 100% 재도출 가능하거나 public 의미가 없는 필드는 COMMENT로 설명하지 않고 제거한다. 운영 감사용 필드는 raw에는 유지하되 `congress_ro` allowlist/view에서 숨긴다.
- **후속 cleanup 결정 (#117)**: `bills.committee`는 `committees` dimension으로 정규화한 뒤 제거했고, 원천 제안자 문구는 `bills.proposer_raw`로 보존한다. `bills.proposer`는 과거 이름이다.
- **직접 SQL 지향 core schema**: PDF/VOD/요약 팝업 링크, upstream source 추적 필드는 core에서 제외한다.
- **soft delete 정책**: 첫 10% 로드 후 결정.

### 외부 API 사용 목록 (확정)

| 용도 | API | 비고 |
|---|---|---|
| 의원 인적사항 | `nwvrqwxyaytdsfvhu` | 286명 |
| 의원 위원회 경력 | (보류) | 위원회 이력 테이블 안 만듦 |
| 법안 목록 | `nzmimeepazxkubdpn` | DAE=22, ~17,000+ |
| 법안 주요내용 | `BPMBILLSUMMARY` | BILL_NO로 1:1 |
| 본회의 표결 | `nojepdqqaweusdfbi` | BILL_ID 단위 |
| 의안별 표결현황 | `ncocpgfiaoituanbr` | 표결된 BILL_ID 목록 |

### API 호출 정책

- **User-Agent 필수** (없으면 Bad Request).
- **모든 API 호출은 wrapper 모듈을 거친다**: 대수 파라미터 형식 차이(`DAE_NUM=22` / `AGE=22` / `ERACO=제22대`)를 한 곳에서 흡수.
- **rate limit / backoff**: 지수 backoff (1→4→16초), 지속 실패 시 `dead_letters`에 저장.

### 수집 orchestration

- **동일 Module 재사용**: 2년치 백필 전용 코드와 증분 전용 코드를 따로 만들지 않는다. 기존 `ingest_*` Module을 재사용하고 실행 mode와 범위만 다르게 지정한다.
- **공식 진입점**: PM/운영자가 기억해야 하는 명령은 하나다. 이 명령은 백필인지 증분인지, 어떤 dead letter를 먼저 재시도해야 하는지를 내부에서 결정한다.
- **백필**: members → bills 100% → votes 100% → sanity/data-completeness 순으로 실행한다.
- **마이그레이션 전 hardening gate** *(완료 — 2026-05-30 통과, 2026-06-06 마이그레이션 종료)*: hosted Postgres 이전에 [PRE-MIGRATION-BACKFILL-GATE.md](PRE-MIGRATION-BACKFILL-GATE.md)에 따라 깨끗한 로컬 DB에서 100% 백필을 실행하고, CLI progress와 DB run state를 관찰하며 느린 stage·누락·dead letter·검증 실패를 고친 뒤 idempotency 재실행까지 통과했다. 이후의 정기 적재는 [SAFE-UPDATE-RUNBOOK.md](SAFE-UPDATE-RUNBOOK.md)의 무손상 사이클이 담당한다.
- **증분 동기화**: run 시작 시 dead_letters 재처리 → members 전체 갱신 → bills/votes 목록 전체 재스캔 upsert(불변 항목 summary·표결은 이미 있으면 skip; *이전 'cursor + 30일 overlap' 폐기 — DECISIONS 2026-06-04 / #46*) 순으로 실행한다.
- **상태 기록**: 모든 실행은 `ingest_runs`에 기록하고, 성공한 source별 기준점은 `ingest_cursors`에 갱신한다.
- **실패 정책**: 일부 item 실패는 `degraded_success`로 기록하고 dead letter를 남긴다. 실패 item은 run 시작 시 우선 재처리한다.

## Testing Decisions

- **단위 테스트는 비즈니스 로직에만**: API 호출 wrapper, 한자→한글 변환, 증분 target 축소 로직.
- **integration test**: 실제 API 호출 → DB 적재 → 쿼리 시나리오(S1~S7) 검증.
- **캘리브레이션 검증**: 초기 10% 적재는 산출물 목표가 아니라 전체 적재 전 병렬 수집 파라미터를 실측하는 단계다. 의원 286명 / 법안 1,700+건 / 표결 ~50,000건을 먼저 적재해 S1~S7 쿼리, rate limit, worker별 처리량, 오버헤드 증가 지점을 확인한 뒤 100% 적재로 확장한다.
- **마이그레이션 전 100% 백필 검증**: 최종 gate는 깨끗한 로컬 DB에서 전체 백필을 실행하며 CLI progress와 `ingest_runs`를 모니터링하고, 이상 지점을 수정한 뒤 full-load 결과와 idempotency rerun을 모두 확인하는 것이다.
- **idempotent 재실행 테스트**: 같은 데이터를 두 번 적재해도 row 수가 변하지 않음 (ON CONFLICT 동작).
- **orchestration 테스트**: 같은 적재 Module을 backfill/incremental mode로 호출하고, 증분의 신규·뒤늦은 변경 포착·불변 항목 skip·dead letter 상태 전이를 public interface(end-to-end)로 검증한다. *(개정 2026-06-04: cursor/30일 overlap planner 검증은 폐기 — 이슈 #46.)*

## Out of Scope

- **위원회 단계 표결** (API에 없음)
- **회의·발언(회의록 utterance) 도메인 전체** — 2026-06-28 마이그레이션(031)으로 제거. 발언 본문의 "누가 무엇을 말했나" 분석은 websearch로 이관([DECISIONS.md](DECISIONS.md)).
- **22대 이전 데이터** (의원의 21대 이력은 텍스트로만 — `members.units`)
- **PDF/HWP·영상 다운로드 및 파싱**
- **PDF/VOD/요약 팝업 링크의 core schema 보존**
- **응용 레이어/스킬/분석 도구 구현** (본 PRD는 DB 적재·정제와 직접 SQL 소비 표면까지)
- **Hosted Postgres 마이그레이션 실행** (로컬 100% 백필 hardening gate 승인 후 별도 슬라이스)
- **위원회 membership / member_committees** — 위원회 *dimension*은 M3 채택(스토리 65). membership(누가 어느 위원)은 명부 API 검증 슬라이스 통과 시에만 재개(DECISIONS 2026-06-11). `member_terms`는 여전히 제외.
- **현행법·시행령·행정규칙·판례·유권해석 본문** — 발의 의안과 구분되는 시행 중인 법. 법제처 3단계 소관([3]). 이 DB는 `prom_law_nm`/`prom_no`/공포일 bridge까지만 제공.
- **정책의제 alias·온톨로지, stance(찬반 논거) 합성, 여론·시민사회·언론 맥락** — 입법전문가 스킬 레이어([4]). DB는 표결 fact만 주고 해석은 스킬이 한다.
- **법안 문서 HWP/PDF 본문 파싱** — `bill_documents`는 URL inventory만(스토리 66). 본문 추출은 후속/[4].
- **vote_summaries 캐시 테이블** (PM 결정, GROUP BY 즉시 계산)
- **263개 미사용 API 검증** (ROI 낮음, [DECISIONS.md](DECISIONS.md)의 2026-05-26 `api_catalog` 결정 참고)
- **매일 일괄 검증 스크립트**
- **개인정보 마스킹** (의원의 공개 정보만 다루므로 불요)

## Further Notes

- **레거시 참조**: SQLite-era legacy tree는 M0에서 제거 완료. 필요한 inf_id와 SQL 결정은 현재 코드와 `DECISIONS.md`에 inline 보존한다.
- **언어**: Python 3.11+, `psycopg[binary,pool]`, `requests`, `beautifulsoup4`, `hanja`.
- **개발 환경**: OrbStack의 Postgres 16 컨테이너 (`postgres:16-alpine`).
- **마지막 의사결정 정리는 `CONTEXT.md`, `docs/design/ERD.md`, `docs/design/IA.md`, `docs/design/DECISIONS.md`에 분산.**
