<p align="center">
  <img src="https://github.com/tjdwls101010/tjdwls101010/blob/main/Images/congress%20db.png?raw=true" alt="Congress-DB" width="100%">
</p>

<h1 align="center">Congress-DB</h1>

<p align="center">
  22대 국회의 <b>발의 의안</b>과 <b>본회의 표결</b>을 한 의원 ID로 통합 조회하는 공개 Postgres 데이터베이스
</p>

<p align="center">
  <img src="https://img.shields.io/badge/PostgreSQL-17-336791?logo=postgresql&logoColor=white" alt="PostgreSQL 17">
  <img src="https://img.shields.io/badge/access-read--only%20public-3ECF8E" alt="public read-only">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT">
  <img src="https://img.shields.io/badge/의안-19%2C277-lightgrey" alt="bills 19,277">
  <img src="https://img.shields.io/badge/표결-482%2C714-lightgrey" alt="votes 482,714">
</p>

---

국회 데이터는 흩어져 있습니다. 의원 명부, 발의 법안, 표결 기록, 공포 이력이 전부 다른 API에 있고 키 형식마저 제각각이라, "이 의원이 발의한 법안이 어떻게 됐나" 같은 단순한 질문 하나에도 여러 API를 붙이고 이름으로 대조하는 작업이 따라붙습니다.

Congress-DB는 그걸 **정규화해 한 곳에 적재한 Postgres**입니다. 의원 한 명을 키로 그 사람의 발의 법안과 본회의 표결이 `JOIN` 한 줄로 나옵니다. 가입도, API 키도, SDK도 필요 없습니다 — **연결문자열 하나로 아무 Postgres 클라이언트에서나 자유 SQL을 던지면 됩니다.**

## 30초 안에 첫 쿼리

```bash
psql "postgresql://congress_ro:-bnO7FC_xrsV12xPm4cwtpNBmhFY_TXU@ep-muddy-unit-ao33i6y0-pooler.c-2.ap-southeast-1.aws.neon.tech/congress?sslmode=require" \
  -c "SELECT bill_no, bill_name, proc_result FROM bills WHERE bill_name ILIKE '%연금%' LIMIT 5;"
```

이 비밀번호는 유출된 게 아니라 **의도적으로 공개된 read-key**입니다. `congress_ro` 계정은 읽기전용이고(쓰기·DDL은 권한으로 거부), 데이터는 전부 공개 입법 사실이며 개인정보 컬럼은 제거돼 있습니다.

Python·DBeaver·DuckDB 등 클라이언트별 예시는 [시작하기](docs/wiki/01-getting-started.md)에 있습니다.

## 무엇이 들어 있나

**기준: 2026-07-19 적재.** 22대 국회는 진행 중이라 매일 증분 수집으로 늘어납니다.

| 항목 | 규모 |
| --- | --- |
| 의안 `bills` | **19,277건** (법률안 19,106 · 비-법률 의안 171) |
| 본회의 표결 `votes` | **482,714행** / 1,627개 의안 |
| 공동발의 `bill_coproposers` | 216,537행 |
| 대표발의 `bill_lead_proposers` | 18,467행 |
| 공포 이력 `bill_final_outcomes` | 1,625건 (공포 완료 1,425) |
| 대안 계보 `bill_lineage` | 4,204행 |
| 의원 `members` | 320명 (현직 299) |
| 위원회 `committees` | 32개 |

수치를 단정하기 전에 `SELECT * FROM data_freshness;`로 **도메인별 기준일을 확인**하세요 — 표결은 의안보다 늦게 들어오는 경우가 있습니다.

## 이 프로젝트의 핵심은 wrapper가 아니라 DB 자체입니다

SDK를 만들지 않기로 한 것은 의도적인 결정입니다. 고정된 함수 표면은 하나만 안 맞아도 막히는데, 실제 입법 분석 질문은 열려 있기 때문입니다. 대신 **DB 자체를 인터페이스로 만들었습니다** — 구조·관계·도메인 용어, 그리고 **조용히 틀린 답을 만드는 함정**이 전부 테이블·컬럼 `COMMENT`에 박혀 있습니다.

```sql
\d+ bills     -- 컬럼 설명 + 생애주기 단계 순서 + 함정이 전부 여기에
```

문서는 낡지만 COMMENT는 DB와 함께 움직입니다. **먼저 introspect하세요.**

## 모르면 조용히 틀리는 것 세 가지

에러가 나면 알아차리지만, 분모가 잘못된 찬성률은 그럴듯한 숫자로 보고서에 들어갑니다.

1. **`'불참'`은 빠진 행이 아니라 저장된 값**이고 전체 표의 약 25%입니다. 찬성률 분모를 `count(*)`로 잡으면 수 %p 낮게 나옵니다 → `FILTER (WHERE result_vote_mod <> '불참')`
2. **`proc_result = '가결'`이라는 값은 존재하지 않습니다.** 통과는 `IN ('원안가결','수정가결')`이고, NULL(약 71%)은 부결이 아니라 미처리입니다.
3. **`bills.law_proc_dt`는 공포일이 아닙니다.** 법사위 처리일입니다. 공포일은 `bill_final_outcomes.promulgation_dt`이고 **`bill_no`로 JOIN**합니다.

나머지 17가지는 [함정과 경계](docs/wiki/04-gotchas-and-limits.md)에 있습니다. **분석 전에 한 번 읽는 것을 강력히 권합니다.**

## 담지 않는 것

- **현행법·시행령 본문, 판례, 유권해석** → 법제처 소관. 이 DB의 `bills`는 *발의된 의안*이지 *시행 중인 법*이 아닙니다. 공포번호(`prom_no`)까지만 bridge로 넘깁니다.
- **회의록·발언** ("누가 무엇을 말했나") → 2026-06-28 제거. 심의 *진행·상태*는 구조화 테이블이 답합니다.
- **위원회 단계 표결** → 원천 API가 제공하지 않습니다.

## 문서

| 문서 | 내용 |
| --- | --- |
| [Wiki](docs/wiki/README.md) | **여기서 시작하세요** |
| [01 시작하기](docs/wiki/01-getting-started.md) | 접속·클라이언트별 예시·권한·노출 객체 |
| [02 데이터 모델](docs/wiki/02-data-model.md) | 테이블·생애주기·생성컬럼·법제처 bridge |
| [03 질의 쿡북](docs/wiki/03-query-cookbook.md) | 검증된 SQL 레시피 |
| [04 함정과 경계](docs/wiki/04-gotchas-and-limits.md) | 조용한 오답을 피하는 법 |
| [05 파이프라인 운영](docs/wiki/05-operations.md) | 수집·안전장치·CI·코드 구조 |

설계 레퍼런스: [`CONTEXT.md`](CONTEXT.md)(도메인 용어) · [`ERD.md`](docs/design/ERD.md)(스키마) · [`DB-QUERY-GUIDE.md`](docs/design/DB-QUERY-GUIDE.md)(cross-table 레시피) · [`DECISIONS.md`](docs/design/DECISIONS.md)(설계 결정 이력) · [`PRD.md`](docs/design/PRD.md)(요구사항) · [`IA.md`](docs/design/IA.md)(질의 카탈로그)

## 파이프라인에 기여하려면

데이터를 쓰는 게 아니라 적재 코드에 손대려는 경우입니다.

```bash
uv sync && cp .env.example .env
make db-up      # Postgres 16 컨테이너 + 스키마 적용
make test
```

전체 절차·마이그레이션 규칙·PR 기준은 [CONTRIBUTING.md](CONTRIBUTING.md), 운영 구조는 [05 파이프라인 운영](docs/wiki/05-operations.md)에 있습니다.

## 프로젝트 경계

이 저장소는 4단계 로드맵의 **1단계(국회 데이터 DB)** 만 담습니다. 2단계는 별도 SDK 없이 이 DB를 직접 SQL로 조회하는 것이고, 3단계 법제처 데이터 계층과 4단계 입법 harness는 별도 저장소입니다.

## 원천과 라이선스

원천은 [열린국회정보 OpenAPI](https://open.assembly.go.kr)와 의안정보시스템의 공개 데이터입니다. 데이터는 원천 그대로(raw fidelity) 보존하므로 결측·표기 불일치가 그대로 남아 있습니다.

이 저장소의 **코드**는 [MIT 라이선스](LICENSE)입니다. MIT는 이 저장소가 저작한 적재·검증 코드에만 적용되며, **이 DB가 담고 있는 국회 데이터 자체의 권리와 이용조건은 별개로 각 제공기관**([열린국회정보 OpenAPI](https://open.assembly.go.kr) · [의안정보시스템](https://likms.assembly.go.kr))**을 따릅니다.**

보안 취약점 제보는 [SECURITY.md](SECURITY.md)를 참고하세요.
