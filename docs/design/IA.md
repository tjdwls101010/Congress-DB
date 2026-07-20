# Information Architecture — Congress-DB

DB의 모든 설계는 "한 자연키 ID로 그 의원/법안의 모든 정보를 SQL JOIN 한 줄로 조회"를 목표로 한다. 향후 스킬, AI agent, 개발자는 이 구조를 introspect하고 read-only SQL로 직접 조회한다.

> 회의·발언(회의록 utterance) 도메인은 2026-06-28 마이그레이션(031)으로 제거됐다. 발언 본문의 "누가 무엇을 말했나" 심층 분석은 websearch로 이관하고, 심의 진행·상태는 구조화 테이블(`bills.proc_result`·`bill_lineage`·`bill_final_outcomes`)로 답한다. 상세는 `DECISIONS.md`(2026-06-28).

## 핵심 엔터티 (Top-level)

```
의원 (Member)        법안 (Bill)
─────────────        ───────────
↓ 발의              ↓ 표결됨
↓ 표결              ↓ 공동발의자
```

두 엔터티가 서로 N:M으로 얽힌다. junction 테이블(`bill_lead_proposers`, `bill_coproposers`)이 그 관계를 표현.

## 사용자 시나리오 (핵심 쿼리 카탈로그)

### S1. 한 의원의 의정 활동 한눈에

> "강대식 의원의 22대 의정 활동 전체"

> ⚠ 이름이 같은 의원이 있으면(예: 박지원 2명, `mona_cd` 다름) `hg_nm` 스칼라 서브쿼리가 에러(다중 행)나거나 두 사람을 합친다. 먼저 `SELECT mona_cd, poly_nm, orig_nm FROM members WHERE hg_nm = '…'`로 `mona_cd`를 확정한 뒤, 아래 쿼리의 서브쿼리를 그 `mona_cd` 리터럴로 바꿔 조회한다.

```sql
-- 기본 정보
SELECT * FROM members WHERE hg_nm = '강대식';

-- 대표발의 법안
SELECT bill_no, bill_name, proc_result, propose_dt
FROM bill_lead_proposers lp JOIN bills b USING (bill_id)
WHERE lp.mona_cd = (SELECT mona_cd FROM members WHERE hg_nm='강대식')
ORDER BY propose_dt DESC;

-- 공동발의 법안
SELECT b.bill_no, b.bill_name, b.proc_result
FROM bill_coproposers c JOIN bills b USING (bill_id)
WHERE c.mona_cd = (SELECT mona_cd FROM members WHERE hg_nm='강대식');

-- 본회의 표결 이력
SELECT b.bill_name, v.result_vote_mod, v.vote_date, v.poly_nm_at_vote
FROM votes v JOIN bills b USING (bill_id)
WHERE v.mona_cd = (SELECT mona_cd FROM members WHERE hg_nm='강대식')
ORDER BY v.vote_date DESC;
```

### S2. 한 법안의 처리 과정 추적

> "항공안전법 일부개정법률안의 발의→위원회→본회의 처리"

```sql
-- 법안 기본 + 처리결과
SELECT b.bill_no, b.bill_name, b.propose_dt, c.committee_name, b.proc_result, b.proc_dt, b.summary
FROM bills b
LEFT JOIN committees c ON c.committee_id = b.committee_id
WHERE b.bill_id = ?;

-- 공동발의자 명단
SELECT m.hg_nm, m.poly_nm, c.order_no
FROM bill_coproposers c JOIN members m USING (mona_cd)
WHERE c.bill_id = ? ORDER BY c.order_no;

-- 대표발의자 명단
SELECT m.hg_nm, m.poly_nm, lp.order_no
FROM bill_lead_proposers lp JOIN members m USING (mona_cd)
WHERE lp.bill_id = ? ORDER BY lp.order_no;

-- 본회의 표결 결과 (의원별 1행, 표결당 ~285~300 · 평균 ~297; 고정 286 아님)
SELECT m.hg_nm, m.poly_nm, v.result_vote_mod
FROM votes v JOIN members m USING (mona_cd)
WHERE v.bill_id = ? ORDER BY m.poly_nm, m.hg_nm;

-- 표결 집계 (찬/반/기권/불참)
SELECT result_vote_mod, COUNT(*) AS 표수
FROM votes WHERE bill_id = ? GROUP BY result_vote_mod;
```

### S4. 본문 키워드 검색

> "전세사기 관련 법안"

```sql
-- 법안 검색: 직접 trigram/ILIKE를 조립하지 말고 DB 함수 사용
SELECT bill_id, bill_no, bill_name, propose_dt, snippet, similarity_score
FROM search_bills('전세사기', 50);
```

### S7. 정당별/시점별 표결 패턴

> "더불어민주당의 어떤 법안 찬성률"

```sql
SELECT poly_nm_at_vote, result_vote_mod, COUNT(*) AS 표수
FROM votes WHERE bill_id = ?
GROUP BY poly_nm_at_vote, result_vote_mod
ORDER BY poly_nm_at_vote, result_vote_mod;
```

> "2024년 12월 표결한 법안들과 각 결과"

```sql
SELECT b.bill_name, b.proc_result,
       SUM(CASE WHEN v.result_vote_mod = '찬성' THEN 1 ELSE 0 END) AS 찬성,
       SUM(CASE WHEN v.result_vote_mod = '반대' THEN 1 ELSE 0 END) AS 반대
FROM votes v JOIN bills b USING (bill_id)
WHERE v.vote_date BETWEEN '2024-12-01' AND '2024-12-31'
GROUP BY b.bill_id, b.bill_name, b.proc_result
ORDER BY b.bill_name;
```

## 검색 입력 → 출력 흐름

```
[입력]                       [내부 매핑]                 [결과 화면]
─────                       ──────────                  ─────────
의원 이름 텍스트     →     members.mona_cd        →     S1 카드
법안 키워드        →     bills pg_trgm 검색     →     S2 카드
키워드 (다목적)     →     search_bills           →     S4 결과
정당 + 날짜        →     votes + members        →     S7 집계
```

## 직접 SQL 소비자 설계 고려사항

- **자연키 우선:** `mona_cd`, `bill_id`, `bill_no`를 결과에 보존해야 후속 SQL을 안정적으로 이어갈 수 있다.
- **검색 결과 발췌:** `search_bills`가 snippet과 similarity를 제공한다. recall 한계는 COMMENT와 CONTEXT의 검색 경고를 따른다.
- **차원별 facet**: 의원 검색에서 정당·현직 여부·표결 시점 정당 등은 가능하지만, 위원회 membership은 현재 DB 범위 밖이다.
- **정책 의제 레이어**: 전세사기·의대정원 같은 정책 주제는 향후 `policy_topics` / `topic_mentions` / `member_topic_positions` 같은 evidence-backed 레이어에서 다룬다.

## 데이터 외 정보(메타) 흐름

```
congress_db/core/endpoints.py ────────→ docs/ops/API-CATALOG.md
                                ↑
                    파이프라인이 실제 사용하는 endpoint 상수
```

`api_catalog` 테이블은 삭제됐다. 운영 모니터링은 카탈로그 매일 검증 스크립트가 아니라, **실제 사용 중인 API 로드 실패 알림**으로 대체한다.

## 수집 운영 흐름

> ⚠ **이 절(O1~O3)은 owner(`congress_owner`) 운영용이다.** `ingest_runs`·`ingest_cursors`·`dead_letters`는 ops 테이블이라 read-only 소비자 role(`congress_ro`)에는 REVOKE되어 있어, 직접-SQL 소비자가 이 쿼리를 돌리면 `permission denied`가 난다. 소비자 조회 표면은 위 S1~S7이다.

초기 백필과 이후 증분 동기화는 같은 적재 Module을 사용한다. 운영 화면/API가 생기기 전에도 아래 쿼리로 PM gate를 확인할 수 있어야 한다.

PM/운영자가 기억해야 하는 공개 Interface는 단일 수집 명령이다. 이 명령은 내부적으로 unresolved dead letter 재시도, 백필/증분 범위 결정, source별 upsert, readiness 리포트 갱신을 순서대로 조율한다. 개별 `ingest-members`, `ingest-bills` 같은 stage 명령은 개발/진단용 보조 Interface로만 취급한다.

*(완료된 절차 — 기록용)* Hosted Postgres 이전에 [PRE-MIGRATION-BACKFILL-GATE.md](PRE-MIGRATION-BACKFILL-GATE.md)의 운영 gate를 먼저 통과했다(2026-05-30 통과, 2026-06-06 마이그레이션 종료). 이 gate는 CLI progress를 보며 100% 로컬 백필을 실제로 돌리고, 느린 stage·retry loop·dead letter·row count gap·검증 실패를 수정한 뒤 idempotency 재실행까지 확인하는 절차였다. 현재 정기 적재의 안전장치는 [SAFE-UPDATE-RUNBOOK.md](SAFE-UPDATE-RUNBOOK.md)다.

### O1. 백필 readiness

> "로컬 100% 적재를 hosted Postgres로 옮겨도 되는가?"

```sql
-- 최근 백필 실행 상태
SELECT id, status, started_at, finished_at, summary, error
FROM ingest_runs
WHERE mode = 'backfill'
ORDER BY started_at DESC
LIMIT 1;

-- unresolved dead letter
SELECT source, stage, status, COUNT(*) AS count
FROM dead_letters
WHERE status IN ('pending', 'retrying', 'blocked')
GROUP BY source, stage, status
ORDER BY count DESC;
```

PM gate: 깨끗한 로컬 DB에서 100% 백필이 완료되고, CLI progress와 `ingest_runs` 기준으로 설명 안 된 느린 stage/skip/retry가 없고, idempotency 재실행이 통과하고, `dead_letters=0`, sanity-check S1~S7 review 가능, data-completeness 잔여 공백 expected/accepted일 때 hosted Postgres migration을 승인한다.

### O2. 증분 동기화 상태

> "오늘 동기화가 정상적으로 끝났나?"

```sql
SELECT id, mode, status, started_at, finished_at, summary
FROM ingest_runs
WHERE mode = 'incremental'
ORDER BY started_at DESC
LIMIT 10;

SELECT source, cursor_kind, cursor_value, overlap_days, updated_at
FROM ingest_cursors
ORDER BY source;
```

`overlap_days`는 과거 windowing 설계의 잔여 컬럼이며, 현재 공식 증분 경로에서는 fetch 범위 결정에 쓰지 않는다. 정상적인 신규 cursor는 source별 `last_success_at` 기준점과 `overlap_days = 0`을 기록한다.

상태 의미:

- `success`: 실패 item 없이 완료.
- `degraded_success`: 성공분은 반영됐고 실패 item은 dead letter로 남음.
- `failed`: 핵심 stage가 중단되어 run 자체가 실패.
- `blocked`: dead letter 누적 또는 반복 실패가 임계값을 넘어 수동 개입 필요.

### O3. dead letter 재처리

> "어떤 데이터가 아직 못 들어왔나?"

```sql
SELECT source, stage, item_key, attempts, last_failed_at, left(error, 240) AS error
FROM dead_letters
WHERE status IN ('pending', 'retrying', 'blocked')
ORDER BY last_failed_at ASC
LIMIT 100;
```

매 incremental run 시작 시 unresolved dead letter를 먼저 재처리한다. 성공하면 row를 삭제하지 않고 `resolved`로 바꿔 지연 적재 이력을 보존한다.

## 데이터의 시점성

| 데이터 | 시점성 표현 |
|---|---|
| 의원 정당·선거구 | members.poly_nm은 **현재**. 시점은 표결 row의 박힘 필드(`votes.poly_nm_at_vote`)에서 추론 |
| 의원 위원회 | 의원별 위원회 membership/history는 현재 DB 범위 밖. bill-side 소관 위원회는 `bills.committee_id` |
| 법안 처리결과 | bills.proc_result는 현재 상태. 매일 업데이트 |

## 본 DB가 답할 수 **없는** 질문 (out of scope)

- "위원회에서 가결됐는데 본회의 부의되지 않은 법안" — 위원회 표결 API 없음 (PM 결정)
- "2024년 8월 5일 시점 국방위 의원 명단" — 시점별 위원회 명단은 표결 데이터로만 추론 가능 (member_committees 안 만듦)
- "PDF/영상 원본" — core schema에 보존하지 않고 다운로드/파싱도 하지 않음
