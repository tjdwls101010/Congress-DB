# 05 — 적재 파이프라인 운영

앞의 네 장이 "DB를 어떻게 쓰는가"였다면, 이 장은 **"그 데이터가 어떻게 채워지는가"** 입니다. 파이프라인을 돌리거나 코드에 손댈 사람을 위한 문서입니다. 단순히 데이터를 조회하려는 분은 여기까지 읽지 않아도 됩니다.

## 원천

| 원천 | 무엇을 주는가 | 채우는 테이블 |
| --- | --- | --- |
| 열린국회정보 OpenAPI — 의원 인적사항 | 현직 의원 명부 | `members` |
| 열린국회정보 OpenAPI — 발의법률안 | 의안 목록·발의자 | `bills`, `bill_lead_proposers`, `bill_coproposers`, `committees` |
| 열린국회정보 OpenAPI — 법률안 제안이유 | 의안 요약 | `bills.summary` |
| 열린국회정보 OpenAPI — 표결정보 | 본회의 표결 | `votes` |
| ALLBILL | 공포·정부이송 이력 | `bill_final_outcomes` |
| 의안정보시스템(likms) **스크래핑** | 원안→대안 관계 | `bill_relations` → `bill_lineage` 뷰 |

대안 관계만 스크래핑인 이유는 **OpenAPI에 그 필드가 아예 없기 때문**입니다. likms 상세페이지의 숨은 입력값(`selRefBillId`)을 파싱합니다. 이 경로가 가장 취약해서, 매일 전체를 다시 긁지 않고 **아직 없는 것만**(`missing-only`) 수집합니다.

## 로컬 개발 환경

전제: [OrbStack](https://orbstack.dev/) 또는 Docker · [uv](https://docs.astral.sh/uv/) · Python 3.11+

```bash
uv sync                  # 의존성 설치
cp .env.example .env     # 환경변수 — 필요시 포트만 조정
make db-up               # Postgres 16 컨테이너 기동 + 스키마 자동 적용
make test                # pytest
```

호스트의 5432가 다른 Postgres에 점유돼 있으면 `.env`의 `POSTGRES_PORT`와 `DATABASE_URL`의 포트를 **같이** 바꿔야 합니다.

> 로컬은 Postgres 16 Docker, 프로덕션은 Neon Postgres 17입니다. `congress_ro`·`anonymous` 같은 역할은 로컬에 존재하지 않으며, 역할을 다루는 마이그레이션 블록은 전부 `pg_roles` 가드로 감싸 로컬에서 no-op으로 넘어갑니다.

### 스키마 적용 방식 — 마이그레이션 추적 테이블이 없습니다

`make db-migrate`는 `db/schema.sql`을 먼저 적용한 뒤 `db/migrations/*.sql`을 **매번 전부** glob 순서로 다시 적용합니다. 따라서 **모든 마이그레이션은 스스로 멱등해야 합니다**(`IF NOT EXISTS`, `CREATE OR REPLACE`, `DO` 블록 가드).

⚠️ `db/migrations/`만 단독으로 이미 마이그레이션된 DB에 돌리면 **실패합니다.** 001·006·012 등이 031에서 삭제된 회의록 테이블을 참조하는데, 이게 통과하는 건 `schema.sql`이 그 테이블들을 먼저 재생성하기 때문입니다. Neon에는 Makefile이 적용하지 않고 owner 연결로 개별 마이그레이션을 수동 적용합니다.

## 수집 명령

**공식 단일 명령은 `make ingest` 하나입니다.**

```bash
make ingest              # auto — 첫 baseline 전에는 백필, 이후에는 증분
```

`auto` 모드는 `ingest_runs`에 성공한 백필이 있는지 보고 결정합니다. 없으면 백필, 있으면 증분입니다.

`ingest-members`·`ingest-bills`·`ingest-votes` 등 stage별 타겟도 있지만 **진단·개발용**입니다. 일반 운영에서는 쓰지 마세요.

### 증분 전략 — 커서가 아니라 DB 상태로 판단합니다

흔한 오해와 달리 이 파이프라인은 "마지막 실행 이후 날짜"로 범위를 좁히지 않습니다. 국회 기록은 **뒤늦게 수정**되기 때문에(처리결과 정정 등) 날짜 창을 쓰면 그 변경을 놓칩니다.

- **싼 목록 endpoint는 매번 전체를 다시 훑습니다** — 뒤늦은 변경까지 잡기 위해서.
- **한 번 확정되면 안 바뀌는 것은 건너뜁니다** — 이미 `summary`가 있는 의안, 이미 `votes` 행이 있는 의안, 이미 해소된 대안 관계.
- 공포 이력만은 예외적으로 조건이 정교합니다 — outcome 행이 있어도 **법률안이 공포 대기 중이면 다시 조회**하고, 공포 대상이 아닌 비-법률 의안은 종착으로 보고 제외합니다.
- `ingest_cursors`는 fetch 범위를 좁히는 데 쓰지 않고 **모드 선택용 관찰 지표**로만 남아 있습니다.

### 실행 상태와 실패 편지

`ingest_runs.status`는 `running` · `success` · `degraded_success` · `failed` · `blocked` 중 하나입니다. 실패한 API item은 삭제하지 않고 `dead_letters`에 보존해 누락 원인을 추적합니다. 다음 실행의 첫 단계가 이 재시도입니다.

⚠️ `dead_letters`는 **일부** 갭만 담습니다 — 원천이 애초에 주지 않는 "수용된 갭"은 여기 없습니다. 결측 주장의 유일한 근거로 쓰면 안 됩니다.

## 프로덕션 적재 — `make safe-update`

Neon `main`에 직접 증분 수집하되, **기존 데이터가 절대 손상되지 않도록** 감싼 명령입니다.

```bash
make safe-update
```

흐름:

1. **백업 브랜치 생성** — Neon copy-on-write라 사실상 즉시·무비용. 복원해도 endpoint host가 바뀌지 않아 **공개 연결문자열이 깨지지 않습니다.**
2. **수집 전 fingerprint** — 읽기전용으로 행수·PK 집합·non-null 여부·자식 행 분포를 스냅샷.
3. **증분 수집 실행**
4. **수집 후 diff**
5. **손상이면 main을 백업으로 자동 복원**, 무손상이면 백업 브랜치 삭제.

### 손상 판정 기준 (4가지)

이 넷 중 하나라도 걸리면 손상으로 보고 되돌립니다.

1. 기존에 있던 PK가 **사라짐**
2. append-only 테이블(`votes`)의 **행수가 감소**
3. 값이 있던 컬럼이 **NULL로 회귀**
4. 자식 행을 갖고 있던 부모가 **자식을 전부 잃음**

자식 행이 *줄어든* 것만으로는 손상이 아닙니다(원천 변경으로 정상 가능). 반대로 **행수가 같은 채 내용만 바뀐 변조는 이 tripwire로 못 잡습니다** — 그 경우의 최종 보험이 백업 브랜치입니다.

플래그: `--keep-backup`(무손상이어도 백업 유지) · `--no-restore`(탐지만 하고 판단은 사람이) · `--no-backup`(비권장, 복원 보험 없음).

⚠️ 손상이 감지돼 자동 복원되면 **그 실행의 신규 데이터는 유실됩니다.** 원천이 정상으로 돌아온 뒤 `make safe-update`를 다시 돌리면 됩니다.

자세한 절차는 [`SAFE-UPDATE-RUNBOOK.md`](../design/SAFE-UPDATE-RUNBOOK.md).

## CI — 워크플로 두 개

### `scheduled-ingest.yml` — 매일 03:00 KST

`make safe-update`를 자동 실행합니다.

⚠️ **`runs-on: self-hosted`입니다.** 국회 OpenAPI(`open.assembly.go.kr`)가 **해외 클라우드 IP를 차단**해서, GitHub 호스트 러너(Azure US/EU)에서는 연결 타임아웃이 납니다. 한국에 있는 자체 러너가 필요합니다.

**빨간불의 의미가 특이합니다** — 손상이 감지돼 자동 복원된 경우에도 종료코드 1로 실패 처리합니다. "데이터는 지켰지만 이번 적재는 롤백됐다"가 조용한 초록불이 되지 않게 하려는 의도입니다.

### `freshness-watchdog.yml` — 매일 10:00 KST

적재가 **조용히 멈춘 것**을 잡는 감시자입니다.

자체 러너가 죽으면 예약된 실행은 큐에 24시간 머물다 `cancelled`가 되는데, **취소는 알림을 보내지 않습니다.** 그래서 이 워치독은 무료 GitHub 호스트 러너에서 공개 `congress_ro` 계정으로 Neon에 붙어(Neon 자체는 지오차단이 없습니다) 네 가지를 확인하고 빨간불을 켭니다.

1. `bills` 적재가 3일 이상 정지
2. `bill_final_outcomes` 적재가 3일 이상 정지
3. 30일 넘게 통과한 법률안인데 공포 이력이 없음
4. 최근 7일 내 통과한 법률안인데 표결 행이 없음

> 참고: GitHub 예약 워크플로는 **기본 브랜치에서만** 실행되고, 저장소가 60일간 비활성이면 자동 비활성화됩니다.

## 진단·리포트 명령

생성물은 전부 `docs/ops/`로 나가며 **gitignored**입니다(코드 생성물이지 손편집 문서가 아닙니다).

| 명령 | 하는 일 |
| --- | --- |
| `make sanity-check` | 대표 시나리오 질의를 돌려 결과를 사람이 훑어볼 리포트로 |
| `make data-completeness` | 결측을 원천 갭 / 안전한 보정 / 위험한 자동매핑으로 분류 |
| `make migration-readiness` | 백필 성공·미해소 dead letter·필수 신호를 보고 ready 판정 |
| `make regression-pack` | **공개 `congress_ro`로** 4개 정책주제 회귀 검증. 실패 시 종료코드 1 |
| `make render-catalog` | 코드의 endpoint 상수에서 API 카탈로그 생성 |

`make regression-pack`은 특히 중요합니다 — Neon Data API 설정을 만지면 **RLS가 조용히 다시 켜져** `congress_ro`가 모든 테이블을 0행으로 보게 되는 사고가 실제로 있었습니다(뷰는 소유자 권한으로 실행돼 정상 반환하니 더 헷갈립니다). 이 회귀팩이 "0 < floor"로 실패해 잡아냅니다. Data API를 건드린 뒤에는 반드시 돌리고, 실패하면 `db/roles/data_api_public_read.sql`을 재실행하세요.

## 코드 구조

```
congress_db/
  core/      # 공유 인프라 — API 클라이언트·DB 연결·endpoint 카탈로그·진행률·동시성 제한
  ingest/    # 백필/증분/재시도 오케스트레이션과 source별 적재
  ops/       # 진단·리포트·안전 업데이트·벤치마크
db/
  schema.sql       # 기반 스키마 (현재 스키마 ≠ 이 파일. 여기 + 마이그레이션 38개)
  migrations/      # 001~038, 전부 멱등
  roles/           # congress_ro 권한 allowlist, Data API 공개읽기 복구 스크립트
scripts/           # 각 Make 타겟이 부르는 얇은 CLI 래퍼
tests/             # pytest — 단위 + 라이브 Postgres 통합
docs/design/       # 손편집 설계문서 (PRD·IA·ERD·DECISIONS·런북)
docs/wiki/         # 이 문서
docs/ops/          # 코드 생성 리포트 (gitignored)
```

**설계 원칙 몇 가지**

- **백필과 증분은 같은 모듈**입니다. 별도 코드로 만들면 drift가 생기므로 실행 mode만 다릅니다.
- **모든 upsert는 비파괴적**입니다 — `COALESCE(EXCLUDED.x, 기존.x)`라 원천이 빈 응답을 줘도 기존 값을 NULL로 덮지 않습니다.
- **발의자 갱신은 범위를 좁힙니다** — 응답에 실제로 발의자 코드가 담긴 의안만 지우고 다시 넣습니다. 전체를 지우면 빈 응답 하나가 발의자를 전멸시킵니다.
- **외부 HTTP는 전역 동시성 상한**(기본 20)을 공유합니다. OpenAPI와 likms 스크래핑이 같은 예산을 씁니다.

## 접속 자격증명

| 변수 | 용도 | 비밀인가 |
| --- | --- | --- |
| `CONGRESS_RO_URL` | 읽기전용 소비자 | **아니오** — 의도적 공개 |
| `DATABASE_URL` / `CONGRESS_MAIN_URL` | owner, 적재 대상 | **예** |
| `NEON_API_KEY` | Neon 컨트롤플레인 (브랜치 생성·복원) | **예** |
| `NATIONAL_ASSEMBLY_API_KEY` | 국회 OpenAPI | **예** |
| `.neon` (project id) | safe-update가 프로젝트를 찾는 용도 | 아니오 — 커밋됨 |

비밀 값은 `.env`·`.env.local`에 두며 둘 다 gitignored입니다. `make`는 `.env`만 로드하므로 `safe_update`는 `.env.local`을 직접 읽습니다.

접근 제어는 **RLS가 아니라 명시적 GRANT allowlist**로 합니다 — 자세한 이유와 절차는 [`DB-ACCESS.md`](../design/DB-ACCESS.md).

## 테스트

```bash
make test                              # 전체
uv run pytest tests/test_schema.py -v  # 하나만
```

- 순수 단위 테스트(API 클라이언트·벤치마크·동시성·리포트 렌더링)는 아무 준비 없이 돕니다.
- 나머지 대부분은 **로컬 Postgres가 떠 있어야** 합니다(`make db-up`). `conftest.py`가 없어 skip 처리가 안 되고 그냥 실패합니다.
- **API 키나 네트워크는 필요 없습니다** — 외부 HTTP 경계는 전부 mock입니다.
- 통합 테스트는 `TEST_*` 접두 sentinel 키를 쓰고 전후로 정리해 실제 데이터를 오염시키지 않습니다.

기여 절차와 마이그레이션 작성 규칙은 [`CONTRIBUTING.md`](../../CONTRIBUTING.md)를 보세요.
