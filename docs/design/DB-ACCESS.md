# DB 접속 (Neon)

Congress-DB는 Neon Postgres(`congress` DB)에 호스팅된다. 권한을 두 role로 분리한다.

## Role

- **`congress_owner`** (소유자) — 적재·마이그레이션·관리 전용. 모든 쓰기 권한. 적재 파이프라인(`scripts/*`, `make ingest` 등)이 사용. 연결 문자열은 `.env.local`의 `DATABASE_URL`.
- **`congress_ro`** (읽기전용) — 향후 **입법전문가 스킬/런타임**이 ad-hoc SQL을 돌릴 때 쓰는 계정. `SELECT` + 함수 `EXECUTE`만 가능, `INSERT/UPDATE/DELETE/DDL`은 거부된다. no-SDK 결정([DECISIONS](DECISIONS.md) 2026-06-10)의 **안전조건 #1** — LLM이 소유자 권한으로 SQL을 돌리다 환각 하나로 데이터를 손상시키는 것을 구조적으로 차단한다. 연결 문자열은 `.env.local`의 `CONGRESS_RO_URL`(gitignore, 평문 커밋 금지).

RLS(Row Level Security)는 이 DB의 소비자 접근 제어로 쓰지 않는다. 국회 사실 데이터는 row별 tenant/사용자 분리가 없고, Neon에서 RLS가 켜진 채 정책이 없으면 `congress_ro`가 모든 테이블을 0행으로 보게 된다. 접근 제어는 `db/roles/congress_ro.sql`의 명시적 GRANT allowlist로 한다.

## pooled vs direct

Neon은 같은 endpoint에 두 호스트를 준다:

- **pooled** (`...-pooler....neon.tech`) — PgBouncer transaction pooling. 짧은 질의를 여러 번 날리는 패턴(스킬의 ad-hoc 조회)에 효율적. prepared statement 비활성 필요(psycopg `prepare_threshold=None`; 기존 `get_pooled_conn`이 이미 그렇게 함).
- **direct** (`-pooler` 없는 호스트) — 장시간 세션·세션 단위 기능. 적재(`get_conn`)는 direct를 쓴다.

**스킬 런타임 기본값: `congress_ro` + pooled read-only.** 장시간 트랜잭션이 필요한 예외적 경우만 direct.

## 권한 적용 / 갱신

`db/roles/congress_ro.sql`을 **owner 연결**로 실행한다(멱등). 이 스크립트는 broad grant를 먼저 회수한 뒤 consumer allowlist만 다시 부여한다. 재실행 후에도 `ingest_runs`·`ingest_cursors`·`dead_letters`는 `congress_ro`에 보이면 안 된다. 비밀번호는 파일에 두지 않고 `ALTER ROLE congress_ro PASSWORD '<random>'`로 별도 설정, 연결 문자열은 `.env.local`에만 둔다.

```bash
# owner 연결로 role + 권한 적용 (Neon)
psql "$OWNER_DATABASE_URL" -v ON_ERROR_STOP=1 -f db/roles/congress_ro.sql
# 비밀번호는 별도(커밋 금지)
psql "$OWNER_DATABASE_URL" -c "ALTER ROLE congress_ro PASSWORD '…';"
```

## 공개 읽기 접속 (다른 사람에게 공유)

`congress_ro`는 읽기전용(SELECT 9객체 = 테이블 7 + 뷰 2, 검색함수 2개, 쓰기·내부테이블 차단)이고 데이터는 전부 공개 입법 사실이라(개인정보 컬럼은 #015에서 제거), **연결 문자열을 공개 read-key처럼 배포해도 안전하다**. 받는 사람은 어떤 Postgres 클라이언트로든 **로컬에서 하듯 자유 SQL**(JOIN·GROUP BY·CTE·윈도우함수·검색함수·EXPLAIN)을 돌릴 수 있다. no-SDK 목표("직접 SQL로 자유롭게")에 충실한 1차 표면이다.

- **연결 문자열(공유용, pooled):** `postgresql://congress_ro:<password>@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress?sslmode=require` — 실제 `<password>`는 `.env.local`의 `CONGRESS_RO_URL`에 있다. **⚠️ 이 저장소는 현재 GitHub 공개다** — `README.md`·`docs/wiki/`·`.github/workflows/freshness-watchdog.yml`에 비밀번호 포함 전체 문자열이 평문으로 커밋돼 있고, 이는 2026-06-18 공개 읽기 결정에 따른 **의도된 배포**다(별도 채널이 더는 필요 없다). 이 파일에서 `<password>`를 가려 둔 것은 습관일 뿐 보호 장치가 아니다. 따라서 `congress_ro`의 안전성은 "저장소가 비공개라서"가 아니라 **읽기전용 allowlist + PII 제거 + `statement_timeout` 캡**에서 나온다 — 이 세 조건 중 하나라도 깨지면 즉시 비밀번호를 회전해야 한다.
- **자기설명:** 받는 사람은 레포 없이도 `\d+ <table>`/`\df+`로 함정·어휘 COMMENT를 직접 introspect한다(COMMENT가 DB와 함께 이동). cross-table 레시피만 [DB-QUERY-GUIDE](DB-QUERY-GUIDE.md)에 있어, 필요하면 그 파일만 따로 공유한다.
- **남용 방어:** 공개 노출 대비로 `congress_ro`에 `statement_timeout=60s`를 걸어 runaway 쿼리를 캡한다(정상 분석 쿼리는 sub-second~수초라 무영향). 부하는 Neon autoscale 비용으로 잡히니 모니터링한다. 비밀번호 교체가 필요하면 `ALTER ROLE congress_ro PASSWORD`로 회전(공개 키라 모든 소비자가 새 문자열로 갱신해야 해 회전 비용 큼).

```bash
# 받는 사람 예시 — psql
psql "postgresql://congress_ro:<password>@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress?sslmode=require" \
  -c "SELECT bill_no, bill_name, proc_result FROM bills WHERE bill_name ILIKE '%연금%' LIMIT 10;"
```
```python
# 받는 사람 예시 — psycopg (pooled endpoint는 prepared statement 비활성 필요)
import psycopg
conn = psycopg.connect("postgresql://congress_ro:<password>@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress?sslmode=require",
                       prepare_threshold=None)
rows = conn.execute("SELECT * FROM search_bills('전세사기', 20)").fetchall()
```

> HTTP(REST)로 받고 싶은 소비자에겐 Neon **Data API**도 병행 가능하나, 그쪽은 자유 SQL이 아니라 REST 필터/정렬/RPC만 된다. 자유 SQL이 목적이면 위 연결 문자열이 답이다.
