# Information Architecture — Congress-DB

DB의 모든 설계는 "한 자연키 ID로 그 의원/법안/회의의 모든 정보를 SQL JOIN 한 줄로 조회"를 목표로 한다. 향후 스킬, AI agent, 개발자는 이 구조를 introspect하고 read-only SQL로 직접 조회한다.

## 핵심 엔터티 (Top-level)

```
의원 (Member)        법안 (Bill)         회의 (Meeting)
─────────────        ───────────         ─────────────
↓ 발의              ↓ 표결됨            ↓ 발언
↓ 표결              ↓ 다뤄짐            ↓ 다뤄진 법안
↓ 발언              ↓ 공동발의자        ↓ 다뤄진 법안
```

세 엔터티가 서로 N:M으로 얽힌다. junction 테이블(`bill_lead_proposers`, `bill_coproposers`, `meeting_bills`)이 그 관계를 표현.

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

-- 발언이 있는 회의 + 발언 수
SELECT m.title, m.conf_date, m.comm_name, COUNT(*) AS 발언수
FROM utterances u JOIN meetings m ON u.meeting_id = m.mnts_id
WHERE u.speaker_mona_cd = (SELECT mona_cd FROM members WHERE hg_nm='강대식')
GROUP BY m.mnts_id, m.title, m.conf_date, m.comm_name
ORDER BY m.conf_date DESC;
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

-- 이 법안이 다뤄진 회의들 (위원회 심사 → 본회의)
SELECT m.title, m.conf_date, m.meeting_type, m.comm_name
FROM meeting_bills mb JOIN meetings m ON mb.meeting_id = m.mnts_id
WHERE mb.bill_id = ? ORDER BY m.conf_date;

-- 본회의 표결 결과 (의원별 1행, 표결당 ~285~300 · 평균 ~297; 고정 286 아님)
SELECT m.hg_nm, m.poly_nm, v.result_vote_mod
FROM votes v JOIN members m USING (mona_cd)
WHERE v.bill_id = ? ORDER BY m.poly_nm, m.hg_nm;

-- 표결 집계 (찬/반/기권/불참)
SELECT result_vote_mod, COUNT(*) AS 표수
FROM votes WHERE bill_id = ? GROUP BY result_vote_mod;
```

### S3. 한 회의의 본문 + 다뤄진 법안

> "2026.04.14 과방위 4차 회의"

```sql
-- 회의 메타
SELECT * FROM meetings WHERE mnts_id = ?;

-- 다뤄진 법안들
SELECT b.bill_no, b.bill_name
FROM meeting_bills mb JOIN bills b USING (bill_id)
WHERE mb.meeting_id = ?;

-- 발언 stream (시간 순)
SELECT sequence, speaker_name, speaker_title, content,
       (SELECT hg_nm FROM members WHERE mona_cd = u.speaker_mona_cd) AS speaker_resolved
FROM utterances u WHERE meeting_id = ? ORDER BY sequence;
```

### S4. 본문 키워드 검색

> "전세사기 관련 발언 / 법안"

```sql
-- 법안 검색: 직접 trigram/ILIKE를 조립하지 말고 DB 함수 사용
SELECT bill_id, bill_no, bill_name, propose_dt, snippet, similarity_score
FROM search_bills('전세사기', 50);

-- 발언 검색 + 회의 메타
SELECT m.title, m.conf_date, s.sequence, s.speaker_name, s.speaker_title, s.snippet
FROM search_utterances('전세사기', 50) s
JOIN meetings m ON m.mnts_id = s.meeting_id
ORDER BY m.conf_date DESC LIMIT 50;
```

### S5. 위원회 단위 활동

> "국방위원회 회의들 + 누가 가장 많이 발언했나"

```sql
-- 국방위 회의 목록
SELECT mnts_id, title, conf_date, meeting_type
FROM meetings WHERE comm_name = '국방위원회' AND meeting_type IN ('상임위','국정감사')
ORDER BY conf_date DESC;

-- 국방위에서 발언량 top 의원
SELECT m.hg_nm, m.poly_nm, COUNT(*) AS 발언수, SUM(LENGTH(u.content)) AS 총글자수
FROM utterances u
  JOIN meetings mt ON u.meeting_id = mt.mnts_id
  JOIN members m ON u.speaker_mona_cd = m.mona_cd
WHERE mt.comm_name = '국방위원회'
GROUP BY m.mona_cd, m.hg_nm, m.poly_nm
ORDER BY 발언수 DESC LIMIT 20;
```

### S6. 답변자 직함 검색 + 주변 읽기

> "기획재정부 장관이 답변한 대목과 직전 의원 발언"

```sql
SELECT
  m.title,
  m.conf_date,
  prev_u.sequence AS 직전의원순번,
  prev_u.speaker_name AS 직전의원,
  prev_u.content AS 직전발언,
  u.sequence AS 답변순번,
  u.speaker_name AS 답변자,
  u.speaker_title AS 답변자직함,
  u.content AS 답변
FROM utterances u
JOIN meetings m ON m.mnts_id = u.meeting_id
LEFT JOIN LATERAL (
  SELECT sequence, speaker_name, content
  FROM utterances p
  WHERE p.meeting_id = u.meeting_id
    AND p.sequence < u.sequence
    AND p.speaker_mona_cd IS NOT NULL
  ORDER BY p.sequence DESC
  LIMIT 1
) prev_u ON true
WHERE u.speaker_title ILIKE '%기획재정부장관%'
ORDER BY m.conf_date DESC, u.meeting_id, u.sequence
LIMIT 50;
```

Q&A 블록은 DB에 저장하지 않는다. 답변자 발언, 정책 키워드 hit, 특정 의원 발언을 anchor로 잡고 같은 `meeting_id`의 앞뒤 `sequence` window를 읽어 질의·답변 문맥을 복원한다.

```sql
SELECT u.meeting_id, m.title, m.conf_date,
       u.sequence, u.speaker_name, u.speaker_title, u.content
FROM utterances u
  JOIN meetings m ON u.meeting_id = m.mnts_id
WHERE u.content ILIKE ('%' || ? || '%')
ORDER BY m.conf_date DESC, u.meeting_id, u.sequence
LIMIT 50;
```

직접 SQL 소비자는 `utterances` hit를 anchor로 잡고, 같은 `meeting_id`의 `sequence` 앞뒤 window를 함께 읽어 지역 문맥을 복원한다. 별도 Q&A candidate 레이어는 현재 계획에 넣지 않고, 검색 품질 검증에서 중요한 누락이 반복될 때 재검토한다.

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
회의 ID/제목       →     meetings.mnts_id       →     S3 카드
키워드 (다목적)     →     search_bills/search_utterances → S4 결과
위원회 이름        →     meetings.comm_name     →     S5 집계
화자 직함 패턴      →     utterances.speaker_title + sequence window → S6/S4 결과
정당 + 날짜        →     votes + members        →     S7 집계
```

## 직접 SQL 소비자 설계 고려사항

- **자연키 우선:** `mona_cd`, `bill_id`, `bill_no`, `mnts_id`, `utterance_id`, `sequence`를 결과에 보존해야 후속 SQL을 안정적으로 이어갈 수 있다.
- **큰 결과 제한:** `utterances`는 한 회의당 수천 row일 수 있으므로 `LIMIT`, 날짜/회의/화자 필터, sequence window를 명시한다.
- **검색 결과 발췌:** `search_bills`/`search_utterances`가 snippet과 similarity를 제공한다. recall 한계는 COMMENT와 CONTEXT의 검색 경고를 따른다.
- **Utterance-first 검색**: Q&A/토론/안건 문맥은 `utterances` pg_trgm keyword search + `sequence` window로 복원한다.
- **차원별 facet**: 의원 검색에서 정당·현직 여부·표결 시점 정당 등은 가능하지만, 위원회 membership은 현재 DB 범위 밖이다.
- **정책 의제 레이어**: 전세사기·의대정원 같은 정책 주제는 회의 안건이 아니라 향후 `policy_topics` / `topic_mentions` / `member_topic_positions` 같은 evidence-backed 레이어에서 다룬다.

## 데이터 외 정보(메타) 흐름

```
congress_db/core/endpoints.py ────────→ docs/ops/API-CATALOG.md
                                ↑
                    파이프라인이 실제 사용하는 endpoint 상수
```

`api_catalog` 테이블은 삭제됐다. 운영 모니터링은 카탈로그 매일 검증 스크립트가 아니라, **실제 사용 중인 API와 회의록 웹 목록/HTML viewer 로드 실패 알림**으로 대체한다.

## 수집 운영 흐름

> ⚠ **이 절(O1~O3)은 owner(`congress_owner`) 운영용이다.** `ingest_runs`·`ingest_cursors`·`dead_letters`는 ops 테이블이라 read-only 소비자 role(`congress_ro`)에는 REVOKE되어 있어, 직접-SQL 소비자가 이 쿼리를 돌리면 `permission denied`가 난다. 소비자 조회 표면은 위 S1~S7이다.

초기 백필과 이후 증분 동기화는 같은 적재 Module을 사용한다. 운영 화면/API가 생기기 전에도 아래 쿼리로 PM gate를 확인할 수 있어야 한다.

PM/운영자가 기억해야 하는 공개 Interface는 단일 수집 명령이다. 이 명령은 내부적으로 unresolved dead letter 재시도, 백필/증분 범위 결정, source별 upsert, 회의록 웹 목록 대조, 필요한 utterance 재스크래핑, readiness 리포트 갱신을 순서대로 조율한다. 개별 `ingest-members`, `ingest-bills`, `ingest-utterances` 같은 stage 명령은 개발/진단용 보조 Interface로만 취급한다.

Hosted Postgres 이전에는 [PRE-MIGRATION-BACKFILL-GATE.md](PRE-MIGRATION-BACKFILL-GATE.md)의 운영 gate를 먼저 통과한다. 이 gate는 CLI progress를 보며 100% 로컬 백필을 실제로 돌리고, 느린 stage·retry loop·dead letter·row count gap·검증 실패를 수정한 뒤 idempotency 재실행까지 확인하는 절차다.

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

PM gate: 깨끗한 로컬 DB에서 100% 백필이 완료되고, CLI progress와 `ingest_runs` 기준으로 설명 안 된 느린 stage/skip/retry가 없고, idempotency 재실행이 통과하고, `dead_letters=0`, `total/22.do` 웹 목록 대비 HTML 회의록 coverage gap 0, sanity-check S1~S7 review 가능, data-completeness 잔여 공백 expected/accepted일 때 hosted Postgres migration을 승인한다.

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
| 의원 정당·선거구 | members.poly_nm은 **현재**. 시점은 표결/발언 row의 박힘 필드(`votes.poly_nm_at_vote`)에서 추론 |
| 의원 위원회 | 회의/발언 문맥의 위원회는 meetings.comm_name. 의원별 위원회 membership/history는 현재 DB 범위 밖 |
| 법안 처리결과 | bills.proc_result는 현재 상태. 매일 업데이트 |
| 회의록 | meetings.fetched_at 으로 마지막 수집 시각 |

## 본 DB가 답할 수 **없는** 질문 (out of scope)

- "위원회에서 가결됐는데 본회의 부의되지 않은 법안" — 위원회 표결 API 없음 (PM 결정)
- "2024년 8월 5일 시점 국방위 의원 명단" — 시점별 위원회 명단은 표결 데이터로만 추론 가능 (member_committees 안 만듦)
- "본회의 마지막 자유토론을 자동 세그먼트 단위로 보여 달라" — 저장된 의미 세그먼트를 만들지 않음
- "한 회의에서 회의 안건 X에 대한 발언만" — 본문이 안건별 분해 안 됨 (PM 통찰: 회의 안건은 메뉴판)
- "PDF/영상 원본" — core schema에 보존하지 않고 다운로드/파싱도 하지 않음
