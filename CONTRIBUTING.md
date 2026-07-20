# 기여 안내

Congress-DB에 관심 가져 주셔서 감사합니다. 이 문서는 이 저장소 특유의 관행 — 특히 **데이터를 망가뜨리지 않기 위한 규칙** — 을 담고 있습니다.

## 먼저 읽을 것

| 무엇을 하려는가 | 어디를 보나 |
| --- | --- |
| 데이터를 조회만 하고 싶다 | [Wiki](docs/wiki/README.md) — 기여할 필요 없습니다 |
| 파이프라인 구조를 알고 싶다 | [05 파이프라인 운영](docs/wiki/05-operations.md) |
| 왜 이렇게 설계했는지 | [`DECISIONS.md`](docs/design/DECISIONS.md) |
| 도메인 용어가 헷갈린다 | [`CONTEXT.md`](CONTEXT.md) |

## 개발 환경

전제: Docker(또는 [OrbStack](https://orbstack.dev/)) · [uv](https://docs.astral.sh/uv/) · Python 3.11+

```bash
uv sync
cp .env.example .env
make db-up      # Postgres 16 컨테이너 기동 + schema.sql + 마이그레이션 전체 적용
make test
```

호스트 5432가 점유돼 있으면 `.env`의 `POSTGRES_PORT`와 `DATABASE_URL`의 포트를 **둘 다** 바꾸세요.

`make db-reset`은 볼륨까지 지우고 재기동합니다(완전 초기화).

### 테스트에 필요한 것

- 대부분의 통합 테스트는 **로컬 Postgres가 떠 있어야 합니다.** `conftest.py`가 없어 skip 없이 그냥 실패합니다.
- **API 키·네트워크는 필요 없습니다** — 외부 HTTP 경계는 전부 mock입니다.
- 통합 테스트는 `TEST_*` sentinel 키를 쓰고 전후로 정리합니다. **이 관행을 깨지 마세요** — 실제 데이터를 오염시킵니다.

## 마이그레이션 작성 규칙

가장 중요한 부분입니다.

### 1. 번호는 순차, 이름은 서술적으로

```
db/migrations/039_your_change_here.sql
```

현재 038까지 있습니다. 번호를 건너뛰거나 재사용하지 마세요.

### 2. 반드시 멱등해야 합니다

**이 프로젝트에는 마이그레이션 추적 테이블이 없습니다.** `make db-migrate`는 `schema.sql` 적용 후 `db/migrations/*.sql`을 **매번 전부** 다시 돌립니다.

```sql
-- 좋음
CREATE TABLE IF NOT EXISTS ...
CREATE INDEX IF NOT EXISTS ...
CREATE OR REPLACE VIEW ...
ALTER TABLE x ADD COLUMN IF NOT EXISTS ...

-- 나쁨 — 두 번째 실행에서 실패
CREATE TABLE foo (...)
ALTER TABLE x ADD CONSTRAINT ...
```

컬럼 DROP이나 제약 추가처럼 조건부 처리가 필요하면 `DO $$ ... $$` 블록으로 감싸고 `information_schema`를 확인하세요.

### 3. 역할 관련 구문은 `pg_roles` 가드로 감쌀 것

`congress_ro`·`anonymous`·`authenticated`는 **로컬에 존재하지 않습니다.** 가드 없이 `GRANT`를 쓰면 로컬 셋업이 통째로 깨집니다.

```sql
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'congress_ro') THEN
    GRANT SELECT ON your_new_view TO congress_ro;
  END IF;
END $$;
```

### 4. 파괴적 변경에는 가드를 넣을 것

컬럼이나 테이블을 지우기 전에 전제를 검증하고, 어긋나면 `RAISE EXCEPTION`으로 멈추세요. 기존 마이그레이션(예: 018의 중복 검사, 021의 무결성 검사)이 좋은 본보기입니다.

### 5. Neon 적용은 수동입니다

`make db-migrate`는 로컬 Docker에만 적용합니다. 프로덕션은 owner 연결로 개별 적용하고, **적용 전후로 `make regression-pack`을 돌리세요.**

## COMMENT는 문서가 아니라 인터페이스입니다

이 프로젝트에서 **`COMMENT ON`은 부차적인 게 아니라 1차 소비자 표면입니다.** SDK가 없기 때문에, 소비자(사람이든 AI 에이전트든)가 `\d+ bills`로 얻는 정보가 곧 이 DB의 사용설명서입니다.

새 컬럼·테이블·뷰를 추가하면 **반드시 COMMENT를 답니다.** 특히:

- 이 필드를 잘못 쓰면 **조용히 틀린 답**이 나오는 경우 → 그 함정을 명시
- 커버리지가 불완전한 경우 → 무엇이 빠졌는지와 대략의 규모
- 다른 필드와 혼동하기 쉬운 경우 → 무엇과 다른지 (예: `law_proc_dt`는 공포일이 아니다)

**정량 수치를 쓸 때 주의하세요.** 절대값(예: "66건 NULL")은 증분 수집으로 낡아 "확인된 거짓"이 됩니다. 비율이나 상대 표현을 쓰고 "count로 재산출하라"를 덧붙이는 게 이 저장소의 관행입니다.

COMMENT를 덮어쓸 때는 **이전 경고를 지우지 않았는지** 확인하세요 — 과거에 마이그레이션 026이 013의 경고를 덮어버린 사고가 있었습니다.

## 적재 코드 수정 시

### 비파괴 원칙을 깨지 마세요

원천 API가 빈 응답이나 부분 응답을 주는 일은 실제로 일어납니다. 그래서:

- **upsert는 `COALESCE(EXCLUDED.x, 기존.x)`** — 새 값이 NULL이면 기존 값을 유지합니다.
- **DELETE는 범위를 좁힙니다** — 발의자 갱신은 응답에 실제로 발의자 코드가 담긴 의안만 대상으로 합니다. 전체를 지우면 빈 응답 하나가 발의자를 전멸시킵니다.
- **링크 테이블은 append-only** — `ON CONFLICT DO NOTHING`, DELETE 없음.

이 원칙을 바꿔야 한다면 PR에 **왜 안전한지**를 적으세요.

### 스크래핑 경로는 조심스럽게

대안 관계는 의안정보시스템(likms) 스크래핑으로 채웁니다. 이게 가장 취약한 경로라 **매일 전체를 다시 긁지 않고 `missing-only`로 수집합니다.** 이 방식을 전체 재수집으로 바꾸지 마세요.

### 외부 HTTP는 전역 동시성 상한을 공유합니다

OpenAPI와 스크래핑이 같은 예산(기본 20)을 씁니다. 워커 수를 직접 늘리지 말고 `cap_worker_count`를 통과시키세요.

## 문서 구조 제약 — 테스트가 강제합니다

`tests/test_docs_structure.py`가 다음을 검사합니다. **모르고 어기면 CI가 빨간불이 됩니다.**

- 다음 파일은 **경로 이동·개명 불가**: `CONTEXT.md`, `docs/design/PRD.md`, `docs/design/IA.md`, `docs/design/ERD.md`, `docs/design/DB-QUERY-GUIDE.md`, `docs/design/DECISIONS.md`
- `DECISIONS.md`에는 `ADR-0001` ~ `ADR-0009` 문자열이 남아 있어야 합니다(과거 개별 ADR을 흡수한 흔적)
- 위 5개 문서에 `congress-sdk`·`Congress-SDK`·`검색 API/SDK` 문자열이 있으면 안 됩니다 — 이 프로젝트는 SDK가 아니라 직접 SQL 중심입니다
- `docs/adr/` 디렉터리를 다시 만들면 안 됩니다
- `docs/ops/*` 파일명은 코드 상수와 묶여 있습니다 — 이름을 바꾸려면 모듈 상수와 이 테스트를 함께 고쳐야 합니다

`docs/ops/`는 **코드가 생성하는 리포트**이고 gitignored입니다. 손으로 편집하지 마세요.
`docs/design/`은 손편집 설계문서, `docs/wiki/`는 외부 소비자용 문서입니다.

## PR 전 체크리스트

```bash
make test          # 전체 통과
```

- [ ] 마이그레이션을 추가했다면 — 번호 순차, 멱등, 역할 구문에 가드
- [ ] 스키마를 바꿨다면 — COMMENT를 달았고, `ERD.md`를 갱신했나
- [ ] 소비자 표면(테이블·뷰·함수)이 바뀌었다면 — `db/roles/congress_ro.sql`과 `docs/wiki/`도 갱신했나
- [ ] 절대 수치를 문서에 적었다면 — 기준일을 병기했나
- [ ] `.env`·`.env.local`이 스테이지에 없나

## 커밋과 PR

- 커밋 메시지는 한국어로 씁니다. 관행은 `타입(범위): 요약` — 예: `feat(schema): ...`, `fix(votes): ...`, `docs: ...`
- **설계 판단이 담긴 변경은 `DECISIONS.md`에 항목을 추가하세요.** 이 저장소에서 "왜"는 커밋 메시지가 아니라 이 로그에 남깁니다. 형식은 `## YYYY-MM-DD — 짧은 제목`, 최신이 위입니다.
- PR 설명에는 **무엇을 바꿨는지보다 왜 안전한지**를 적어 주세요. 특히 데이터 파괴 가능성이 있는 변경이라면.

## 질문

일반 질문·데이터 오류 제보는 [GitHub Issues](https://github.com/tjdwls101010/Congress-DB/issues)로, 보안 취약점은 [SECURITY.md](SECURITY.md)의 비공개 경로로 부탁드립니다.
