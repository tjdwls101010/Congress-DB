# Congress-DB Wiki

22대 국회(2024-05-30~ )의 **발의 의안**과 **본회의 표결**을 담은 공개 Postgres 데이터베이스입니다. 누구나 읽기전용 SQL로 자유롭게 조회할 수 있습니다 — SDK도, API 키도, 가입도 필요 없습니다.

## 30초 안에 첫 쿼리

```bash
psql "postgresql://congress_ro:-bnO7FC_xrsV12xPm4cwtpNBmhFY_TXU@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress?sslmode=require" \
  -c "SELECT bill_no, bill_name, proc_result FROM bills WHERE bill_name ILIKE '%연금%' LIMIT 5;"
```

`congress_ro` 계정은 **읽기전용**입니다. `INSERT`·`UPDATE`·`DELETE`·DDL은 권한으로 거부되고, 공개 입법 사실 데이터만 보입니다.

## 이 프로젝트의 핵심은 wrapper가 아니라 DB 자체입니다

구조·관계·도메인 용어, 그리고 **조용히 틀린 답을 만드는 함정**이 전부 테이블·컬럼 `COMMENT`에 박혀 있습니다. `\d+ bills` 한 줄이면 그 컬럼이 무엇이고 어디서 함정에 빠지는지 DB가 직접 설명합니다. 문서는 낡지만 COMMENT는 DB와 함께 움직입니다 — **먼저 introspect하세요.**

## 무엇을 할 수 있나

- 한 법안의 **생애주기** 추적 — 발의 → 소관위 → 법사위 → 본회의 → 정부이송 → 공포
- 경쟁 법안들이 하나의 **위원장 대안으로 통합**되는 계보 추적 (대안반영폐기)
- **의원·정당·위원회·발의·표결**을 의원 ID 하나로 JOIN
- 공포된 법을 외부 **법제처/현행법** 데이터와 잇는 bridge 키(`prom_no`)

## 문서 안내

| 문서 | 내용 |
| --- | --- |
| [01 — 시작하기](01-getting-started.md) | 접속 방법, 클라이언트별 예시(psql·Python·DBeaver·DuckDB), 권한·제약, 노출 객체 목록 |
| [02 — 데이터 모델](02-data-model.md) | 테이블·관계·법안 생애주기·생성컬럼·법제처 bridge |
| [03 — 질의 쿡북](03-query-cookbook.md) | 라이브 검증된 SQL 레시피 |
| [04 — 함정과 경계](04-gotchas-and-limits.md) | **조용한 오답을 피하는 법**, 이 DB가 담지 않는 것 |
| [05 — 적재 파이프라인 운영](05-operations.md) | 데이터가 어떻게 채워지는가 — 수집·안전장치·CI·코드 구조 |

더 깊은 레퍼런스: [`DB-QUERY-GUIDE.md`](../design/DB-QUERY-GUIDE.md)(cross-table 레시피) · [`CONTEXT.md`](../../CONTEXT.md)(도메인 용어 정의) · [`ERD.md`](../design/ERD.md)(스키마) · [`DECISIONS.md`](../design/DECISIONS.md)(설계 결정 이력).

## 규모

**기준: 2026-07-19 적재** — 숫자는 매일 증분 수집으로 늘어납니다. 단정하기 전에 `SELECT * FROM data_freshness;`로 기준일을 확인하고 산출물에 병기하세요.

| 항목 | 규모 |
| --- | --- |
| 의안 (`bills`) | 19,277건 (법률안 19,106 · 비-법률 의안 171) |
| 본회의 표결 (`votes`) | 482,714행 / 1,627개 의안 |
| 공동발의 (`bill_coproposers`) | 216,537행 |
| 대표발의 (`bill_lead_proposers`) | 18,467행 |
| 공포 이력 (`bill_final_outcomes`) | 1,625건 (공포 완료 1,425) |
| 대안 계보 (`bill_lineage`) | 4,204행 (대안 해소 3,704) |
| 의원 (`members`) | 320명 (현직 299) |
| 위원회 (`committees`) | 32개 |

발의일 범위 2024-05-30 ~ 2026-07-16 · 표결일 범위 2024-07-04 ~ 2026-06-18.

## 범위 밖

- **현행법·시행령 본문, 판례, 유권해석** → 법제처 소관. 이 DB의 `bills`는 *발의된 의안*이지 *시행 중인 법*이 아닙니다.
- **회의록·발언** ("누가 무엇을 말했나") → 2026-06-28에 제거(마이그레이션 031). 심의 *진행·상태*는 `bills.proc_result`·`bill_lineage`·`bill_final_outcomes`가 답하고, 발언 내용 분석은 websearch 영역입니다.
- **위원회 단계 표결** → 원천 API가 제공하지 않습니다. `votes`는 본회의 표결만 담습니다.

## 원천과 책임

원천은 [열린국회정보 OpenAPI](https://open.assembly.go.kr)의 공개 데이터입니다. 데이터는 원천 그대로(raw fidelity) 보존하므로 결측·표기 불일치가 그대로 남아 있습니다 — 분석 전에 [04 — 함정과 경계](04-gotchas-and-limits.md)를 먼저 읽으세요.
