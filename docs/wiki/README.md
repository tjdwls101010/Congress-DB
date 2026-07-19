# Congress-DB Wiki — 대한민국 국회 입법 데이터베이스

22대 국회(2024-05-30~ )의 **발의 의안 · 본회의 표결**을 담은 공개 Postgres 데이터베이스입니다. 누구나 **읽기전용 SQL로 자유롭게** 조회할 수 있습니다 — 별도 SDK나 API 키 없이, 어떤 Postgres 클라이언트로든 바로 붙어서 `SELECT`를 던지면 됩니다.

> **회의·발언 도메인은 2026-06-28(031)에 제거됐습니다** — 발언 내용("누가 무엇을 말했나") 분석은 이 DB 범위 밖(→ websearch)이고, 심의 진행·상태는 구조화 테이블이 답합니다.

> 이 프로젝트의 핵심 가치는 wrapper가 아니라 **DB 자체**입니다. 구조·관계·도메인 용어·함정이 전부 테이블/컬럼 `COMMENT`에 박혀 있어, `\d+ <table>`만으로 self-documenting합니다.

## 무엇을 할 수 있나

- 특정 법안의 **생애주기**(발의 → 위원회 → 본회의 → 공포) 추적
- 경쟁 법안들이 하나의 **대안으로 통합**돼 처리되는 과정 추적 (대안반영 계보)
- **발의자·공동발의자·정당·위원회·표결**을 SQL로 자연스럽게 연결
- 공포된 법안을 외부 **법제처/현행법** 데이터와 잇는 bridge 키(`prom_no`)

## 빠른 시작 (30초)

```bash
psql "postgresql://congress_ro:-bnO7FC_xrsV12xPm4cwtpNBmhFY_TXU@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress?sslmode=require" \
  -c "SELECT bill_no, bill_name, proc_result FROM bills WHERE bill_name ILIKE '%연금%' LIMIT 5;"
```

이 계정(`congress_ro`)은 **읽기전용**입니다 — `INSERT/UPDATE/DELETE`는 거부되고, 공개 사실 데이터만 보입니다.

## 문서 안내

| 문서 | 내용 |
| --- | --- |
| [01 — 시작하기](01-getting-started.md) | Neon 접속 방법, 클라이언트별(psql·Python·DBeaver·DuckDB) 예시, 권한·제약 |
| [02 — 데이터 모델](02-data-model.md) | 테이블·관계·법안 생애주기·공포 bridge·도메인 용어 |
| [03 — 질의 쿡북](03-query-cookbook.md) | 자주 쓰는 질의 모음 (생애주기·대안 통합·발의자·표결·공포·의제 추적) |
| [04 — 함정과 범위](04-gotchas-and-limits.md) | 조용한 오답을 피하는 법, 이 DB가 담지 않는 것 |

더 깊은 레퍼런스: [`docs/design/DB-QUERY-GUIDE.md`](../design/DB-QUERY-GUIDE.md)(cross-table 레시피) · [`CONTEXT.md`](../../CONTEXT.md)(도메인 용어) · [`docs/design/ERD.md`](../design/ERD.md)(스키마).

## 규모 (2026-06 기준, 증분 수집으로 증가)

- 의안 약 **18,400건** · 본회의 표결 약 **47만 행** · 공포 약 **1,365건** · 의원 320명

## 라이선스 · 책임

원천은 [열린국회정보 OpenAPI](https://open.assembly.go.kr)의 공개 데이터입니다. 데이터는 원천 그대로(raw fidelity) 보존하므로 결측·표기 불일치가 있을 수 있습니다 — [04 — 함정과 범위](04-gotchas-and-limits.md)를 먼저 읽으세요.
