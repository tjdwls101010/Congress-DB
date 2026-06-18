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
