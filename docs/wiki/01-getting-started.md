# 01 — 시작하기: Neon 접속

Congress-DB는 [Neon](https://neon.tech)에 호스팅된 Postgres 17 데이터베이스입니다. 공개 **읽기전용** 계정 `congress_ro`로 누구나 접속할 수 있습니다.

## 연결 문자열 (공개 read-only)

```
postgresql://congress_ro:-bnO7FC_xrsV12xPm4cwtpNBmhFY_TXU@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress?sslmode=require
```

| 항목 | 값 |
| --- | --- |
| host | `ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech` (pooled) |
| database | `congress` |
| user | `congress_ro` |
| 권한 | `SELECT` + 검색 함수 `EXECUTE`만. 쓰기·DDL 불가 |
| SSL | 필수 (`sslmode=require`) |

> 이 비밀번호는 **공개 read-key**입니다(읽기전용·공개 사실 데이터). 비밀이 아니라 누구나 써도 되는 접근 키로 의도된 값입니다.

## 클라이언트별 접속

### psql
```bash
psql "postgresql://congress_ro:-bnO7FC_xrsV12xPm4cwtpNBmhFY_TXU@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress?sslmode=require"
-- 접속 후
\dt                          -- 테이블 목록
\d+ bills                    -- bills 구조 + 컬럼 COMMENT(함정 설명 포함)
\df+ search_bills            -- 검색 함수 시그니처
SELECT * FROM search_bills('전세사기', 20);
```

### Python (psycopg 3)
```python
import psycopg

URL = ("postgresql://congress_ro:-bnO7FC_xrsV12xPm4cwtpNBmhFY_TXU"
       "@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress?sslmode=require")

# pooled endpoint는 prepared statement 비활성 필요
conn = psycopg.connect(URL, prepare_threshold=None)
rows = conn.execute(
    "SELECT bill_no, bill_name FROM bills WHERE bill_name ILIKE %s LIMIT 10",
    ("%기후%",),
).fetchall()
for r in rows:
    print(r)
```

### Python (SQLAlchemy / pandas)
```python
import pandas as pd
from sqlalchemy import create_engine

engine = create_engine(
    "postgresql+psycopg://congress_ro:-bnO7FC_xrsV12xPm4cwtpNBmhFY_TXU"
    "@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress?sslmode=require"
)
df = pd.read_sql("SELECT proc_result, count(*) FROM bills GROUP BY 1 ORDER BY 2 DESC", engine)
```

### DBeaver / TablePlus / DataGrip
새 PostgreSQL 연결에서 host/database/user/password를 위 표대로 넣고, SSL을 `require`로 설정하면 됩니다.

### DuckDB (postgres scanner)
```sql
INSTALL postgres; LOAD postgres;
ATTACH 'postgresql://congress_ro:-bnO7FC_xrsV12xPm4cwtpNBmhFY_TXU@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress?sslmode=require' AS congress (TYPE postgres, READ_ONLY);
SELECT count(*) FROM congress.bills;
```

## 권한과 제약

- **읽기전용**: `INSERT/UPDATE/DELETE/DDL`은 `permission denied`로 거부됩니다.
- **노출 범위**: 소비자용 객체(테이블 10 · 뷰 2 · 함수 3, 아래)만 보입니다. 내부 적재/운영 테이블(`ingest_runs` 등)과 raw 테이블은 권한으로 차단됩니다.
- **쿼리 시간 제한**: 한 쿼리당 `statement_timeout = 60초`. 무거운 쿼리는 잘립니다 — 보통 분석 쿼리는 1초 미만입니다.
- **pooled 연결**: 짧은 질의 여러 번에 최적화돼 있습니다. psycopg는 `prepare_threshold=None`을 주세요.

## 노출된 객체 (테이블 10 · 뷰 2 · 함수 3)

**테이블 (10)**: `bills` · `members` · `committees` · `bill_lead_proposers` · `bill_coproposers` · `votes` · `meetings` · `utterances` · `meeting_bills` · `bill_final_outcomes`

**뷰 (2)**: `bill_lineage`(원안→대안 계보) · `bill_meeting_contexts`(법안×회의 evidence)

**함수 (3)**: `search_bills(text, int)` · `search_utterances(text, int)` · `search_snippet(text, text, int)`

구조·관계는 [02 — 데이터 모델](02-data-model.md)에서, 바로 쓰는 질의는 [03 — 질의 쿡북](03-query-cookbook.md)에서 이어집니다.

## 먼저 introspect하세요

이 DB는 self-documenting입니다. 함정·도메인 의미가 전부 COMMENT에 있습니다:

```sql
\d+ bills                          -- 컬럼별 설명 + 생애주기 단계 순서
\d+ bill_final_outcomes            -- 공포 bridge 키 설명
SELECT obj_description('bill_lineage'::regclass);   -- 뷰 커버리지 caveat
```
