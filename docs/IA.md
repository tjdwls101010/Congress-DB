# Information Architecture — Congress-DB

DB의 모든 설계는 "한 자연키 ID로 그 의원/법안/회의의 모든 정보를 SQL JOIN 한 줄로 조회"를 목표로 한다. 향후 검색 API/SDK는 이 쿼리 패턴 위에 얹는다.

## 핵심 엔터티 (Top-level)

```
의원 (Member)        법안 (Bill)         회의 (Meeting)
─────────────        ───────────         ─────────────
↓ 발의              ↓ 표결됨            ↓ 발언
↓ 표결              ↓ 다뤄짐            ↓ 다뤄진 법안
↓ 발언              ↓ 공동발의자        ↓ Q&A 그룹
```

세 엔터티가 서로 N:M으로 얽힌다. junction 테이블(`bill_lead_proposers`, `bill_coproposers`, `meeting_bills`)이 그 관계를 표현.

## 사용자 시나리오 (핵심 쿼리 카탈로그)

### S1. 한 의원의 의정 활동 한눈에

> "강대식 의원의 22대 의정 활동 전체"

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
SELECT bill_no, bill_name, propose_dt, committee, proc_result, proc_dt, summary
FROM bills WHERE bill_id = ?;

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

-- 본회의 표결 결과 (의원 286명)
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

-- Q&A 그룹 (있다면)
SELECT sg.id, m.hg_nm AS 질의자, sg.respondents, sg.utterance_count, sg.total_chars
FROM session_groups sg JOIN members m ON sg.questioner_mona_cd = m.mona_cd
WHERE sg.meeting_id = ?
ORDER BY sg.seq_start;
```

### S4. 본문 키워드 검색 (pg_trgm)

> "전세사기 관련 발언 / 법안"

```sql
-- 법안 검색
SELECT bill_no, bill_name, propose_dt FROM bills
WHERE bill_name ILIKE '%전세사기%' OR summary ILIKE '%전세사기%'
ORDER BY propose_dt DESC;

-- 발언 검색
SELECT m.title, m.conf_date, u.speaker_name, u.content
FROM utterances u JOIN meetings m ON u.meeting_id = m.mnts_id
WHERE u.content ILIKE '%전세사기%'
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

### S6. Q&A 단위 검색

> "기획재정부 장관이 답변한 모든 Q&A"

```sql
SELECT m.title, m.conf_date, mb.hg_nm AS 질의자, sg.respondents
FROM session_groups sg
  JOIN meetings m ON sg.meeting_id = m.mnts_id
  JOIN members mb ON sg.questioner_mona_cd = mb.mona_cd
WHERE sg.respondents @> '[{"title":"기획재정부장관"}]'::jsonb
ORDER BY m.conf_date DESC;
```

`session_groups`는 정밀한 Q&A 의미 단위로 우선 사용한다. 다만 본회의·소위원회처럼 그룹화하지 않은 회의나, 상임위·국정감사 안에서도 누락된 발언은 `utterances` 검색으로 보완한다.

```sql
SELECT u.meeting_id, m.title, m.conf_date,
       u.sequence, u.speaker_name, u.speaker_title, u.content
FROM utterances u
  JOIN meetings m ON u.meeting_id = m.mnts_id
WHERE u.content ILIKE ('%' || ? || '%')
ORDER BY m.conf_date DESC, u.meeting_id, u.sequence
LIMIT 50;
```

SDK/API는 `session_group_id`가 없는 `utterances` hit를 반환할 때, 같은 `meeting_id`의 `sequence` 앞뒤 window를 함께 읽어 지역 문맥을 복원한다. 별도 orphan Q&A candidate 레이어는 현재 계획에 넣지 않고, 검색 품질 검증에서 중요한 누락이 반복될 때 재검토한다.

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
키워드 (다목적)     →     bills + utterances pg_trgm 검색 → S4 결과
위원회 이름        →     meetings.comm_name     →     S5 집계
화자 직함 패턴      →     session_groups.JSONB + utterances keyword fallback → S6/S4 결과
정당 + 날짜        →     votes + members        →     S7 집계
```

## 향후 SDK 설계 시 고려사항

(SDK는 별도 세션이지만, IA는 SDK 설계에 직접 영향)

- **공개 API 형태**: GraphQL이 N:M 그래프 탐색에 자연스러움. RESTful도 가능.
- **자연키 우선 노출**: `mona_cd`, `bill_id`, `mnts_id`는 외부 API에서도 그대로 노출 (URL-friendly).
- **JSON 응답 표준**: 자주 쓰는 시나리오(S1~S3)는 "한 호출에 패널 전체"가 자연스러움. nested response.
- **Rate limit / 캐시**: utterances는 한 회의당 수천 row. 페이지네이션 필수.
- **검색 결과 highlight**: pg_trgm은 후보 row를 빠르게 좁히고, 앱/API 계층에서 검색어 주변 발췌를 만든다.
- **Session-first 검색**: Q&A 결과는 `session_groups`를 우선 노출하고, 누락 가능성은 `utterances` pg_trgm keyword search + `sequence` window로 보완한다.
- **차원별 facet**: 의원 검색에서 정당·위원회·재선 횟수 등 facet.
- **정책 의제 레이어**: 전세사기·의대정원 같은 정책 주제는 회의 안건이 아니라 향후 `policy_topics` / `topic_mentions` / `member_topic_positions` 같은 evidence-backed 레이어에서 다룬다.

## 데이터 외 정보(메타) 흐름

```
api_catalog ────────→ (사람이 docs/API-CATALOG.md 자동 생성으로 본다)
                ↑
       277개 1회성 검증 결과 + 우리가 쓰기로 한 이유 메모
                ↓
       파이프라인이 실제 사용하는 API ~10개에 used_in_pipeline=TRUE
```

운영 모니터링은 카탈로그 매일 검증 스크립트가 아니라, **실제 사용 중인 API와 회의록 웹 목록/HTML viewer 로드 실패 알림**으로 대체한다.

## 수집 운영 흐름

초기 백필과 이후 증분 동기화는 같은 적재 Module을 사용한다. 운영 화면/API가 생기기 전에도 아래 쿼리로 PM gate를 확인할 수 있어야 한다.

PM/운영자가 기억해야 하는 공개 Interface는 단일 수집 명령이다. 이 명령은 내부적으로 unresolved dead letter 재시도, 백필/증분 범위 결정, source별 upsert, 회의록 웹 목록 대조, 필요한 utterance/session_group 재계산, readiness 리포트 갱신을 순서대로 조율한다. 개별 `ingest-members`, `ingest-bills`, `ingest-utterances` 같은 stage 명령은 개발/진단용 보조 Interface로만 취급한다.

Supabase 이전에는 [PRE-MIGRATION-BACKFILL-GATE.md](PRE-MIGRATION-BACKFILL-GATE.md)의 운영 gate를 먼저 통과한다. 이 gate는 CLI progress를 보며 100% 로컬 백필을 실제로 돌리고, 느린 stage·retry loop·dead letter·row count gap·검증 실패를 수정한 뒤 idempotency 재실행까지 확인하는 절차다.

### O1. 백필 readiness

> "로컬 100% 적재를 Supabase로 옮겨도 되는가?"

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

PM gate: 깨끗한 로컬 DB에서 100% 백필이 완료되고, CLI progress와 `ingest_runs` 기준으로 설명 안 된 느린 stage/skip/retry가 없고, idempotency 재실행이 통과하고, `dead_letters=0`, `total/22.do` 웹 목록 대비 HTML 회의록 coverage gap 0, session_group integrity error 0, sanity-check S1~S7 review 가능, data-completeness 잔여 공백 expected/accepted일 때 Supabase migration을 승인한다.

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
| 의원 위원회 | meetings.comm_name이 회의별 시점 위원회. members.cmits는 현재 |
| 법안 처리결과 | bills.proc_result는 현재 상태. 매일 업데이트 |
| 회의록 | meetings.fetched_at 으로 마지막 수집 시각 |

## 본 DB가 답할 수 **없는** 질문 (out of scope)

- "위원회에서 가결됐는데 본회의 부의되지 않은 법안" — 위원회 표결 API 없음 (PM 결정)
- "2024년 8월 5일 시점 국방위 의원 명단" — 시점별 위원회 명단은 표결 데이터로만 추론 가능 (member_committees 안 만듦)
- "본회의 마지막 자유토론에서 무슨 주제 나왔나" — Q&A 그루핑이 본회의에 적용 안 됨
- "한 회의에서 회의 안건 X에 대한 발언만" — 본문이 안건별 분해 안 됨 (PM 통찰: 회의 안건은 메뉴판)
- "PDF/영상 원본" — core schema에 보존하지 않고 다운로드/파싱도 하지 않음
