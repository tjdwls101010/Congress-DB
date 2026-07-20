# 01 — 시작하기: 접속과 첫 쿼리

Congress-DB는 [Neon](https://neon.tech)에 호스팅된 **PostgreSQL 17** 데이터베이스입니다(리전 `ap-southeast-1`). 공개 읽기전용 계정 `congress_ro`로 누구나 접속할 수 있습니다.

## 연결 문자열

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

> 이 비밀번호는 **의도적으로 공개된 read-key**입니다. 유출된 자격증명이 아니라, "쓰기는 소유자만, 읽기는 누구나"라는 공개 정책([DECISIONS](../design/DECISIONS.md) 2026-06-18)에 따라 배포하는 값입니다. 데이터는 전부 공개 입법 사실이고 개인정보 컬럼은 제거돼 있습니다.

## 클라이언트별 접속

### psql

```bash
psql "postgresql://congress_ro:-bnO7FC_xrsV12xPm4cwtpNBmhFY_TXU@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress?sslmode=require"
```

```sql
\dt                    -- 보이는 테이블 목록
\d+ bills              -- bills 구조 + 컬럼 COMMENT (함정 설명 포함)
\df+ search_bills      -- 검색 함수 시그니처 + 사용 주의
SELECT * FROM search_bills('전세사기', 20);
```

### Python (psycopg 3)

```python
import psycopg

URL = ("postgresql://congress_ro:-bnO7FC_xrsV12xPm4cwtpNBmhFY_TXU"
       "@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress?sslmode=require")

# pooled endpoint(PgBouncer)는 prepared statement 비활성이 필요합니다
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

새 PostgreSQL 연결에서 host·database·user·password를 위 표대로 넣고 SSL을 `require`로 설정합니다.

### DuckDB (postgres scanner)

```sql
INSTALL postgres; LOAD postgres;
ATTACH 'postgresql://congress_ro:-bnO7FC_xrsV12xPm4cwtpNBmhFY_TXU@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress?sslmode=require' AS congress (TYPE postgres, READ_ONLY);
SELECT count(*) FROM congress.bills;
```

## 권한과 제약

- **읽기전용** — `INSERT`·`UPDATE`·`DELETE`·DDL은 `permission denied`로 거부됩니다.
- **노출 범위** — 아래 11개 객체만 보입니다. 내부 적재·운영 테이블(`ingest_runs`·`ingest_cursors`·`dead_letters`)과 ETL raw 테이블(`bill_relations`·`bill_source_aliases`)은 권한으로 차단됩니다. `\dt`에 안 보이거나, 보이더라도 조회하면 `permission denied`입니다.
- **쿼리 시간 제한** — 한 쿼리당 `statement_timeout = 60초`. 보통 분석 쿼리는 1초 미만이라 영향이 없습니다.
- **pooled 연결** — 짧은 질의를 여러 번 던지는 패턴에 최적화돼 있습니다. psycopg는 `prepare_threshold=None`을 주세요.

## 노출된 객체 (테이블 7 · 뷰 2 · 함수 2)

**테이블 (7)** — `bills` · `members` · `committees` · `bill_lead_proposers` · `bill_coproposers` · `votes` · `bill_final_outcomes`

**뷰 (2)**
- `bill_lineage` — 폐기 원안 → 흡수한 대안 계보
- `data_freshness` — 도메인별 마지막 적재 시각·최신 사실 날짜. **단정하기 전에 이걸 먼저 보세요**

**함수 (2)** — `search_bills(text, int)` · `search_snippet(text, text, int)`

> 회의·발언 도메인(`meetings`·`meeting_bills`·`utterances` 테이블, `bill_meeting_contexts` 뷰, `search_utterances` 함수)은 2026-06-28 마이그레이션 031에서 제거됐습니다.

### 생성컬럼 3종

`\d+`로 보면 나타나는 `GENERATED ALWAYS AS ... STORED` 컬럼입니다. 매번 손으로 재조립하던 기계적 규칙을 엔진이 계산하게 승격한 것이라, **직접 식을 쓰지 말고 이 컬럼을 쓰세요.**

| 컬럼 | 계산식 | 왜 필요한가 |
| --- | --- | --- |
| `votes.vote_date_kst` | `(vote_date AT TIME ZONE INTERVAL '9 hours')::date` | 서버 세션이 GMT라 `vote_date::date`는 늦은 시각 표결을 하루 어긋나게 뽑습니다 |
| `bills.is_law_bill` | `bill_name ~ '법(률)?안'` | 공포 대상인 법률안과 비-법률 의안(결의안·감사요구안 등 171건)을 가릅니다 |
| `bill_final_outcomes.prom_law_nm_norm` | 가운뎃점 통일 + 공백 제거 | 법제처 법령명과 이름 매칭할 때 씁니다 |

## 먼저 introspect하세요

이 DB는 self-documenting입니다. 함정과 도메인 의미가 전부 COMMENT에 있습니다.

```sql
\d+ bills                                            -- 컬럼별 설명 + 생애주기 단계 순서
\d+ votes                                            -- 불참·시간대 함정
\d+ bill_final_outcomes                              -- 공포 bridge 키 설명
SELECT obj_description('bill_lineage'::regclass);    -- 뷰 커버리지 caveat
SELECT * FROM data_freshness ORDER BY domain;        -- 각 도메인이 언제까지 채워졌나
```

구조·관계는 [02 — 데이터 모델](02-data-model.md), 바로 쓰는 질의는 [03 — 질의 쿡북](03-query-cookbook.md), 조용한 오답을 피하는 법은 [04 — 함정과 경계](04-gotchas-and-limits.md)로 이어집니다.
