# Congress-DB

22대 국회(2024-05-30~) 의정 활동을 한 의원 ID로 통합 조회하는 Postgres 16 DB.

상세 도메인은 [CONTEXT.md](CONTEXT.md), 요구사항은 [docs/PRD.md](docs/PRD.md),
화면/경로는 [docs/IA.md](docs/IA.md), 스키마는 [docs/ERD.md](docs/ERD.md) 참고.

## 환경 셋업

전제: macOS + [OrbStack](https://orbstack.dev/), [uv](https://docs.astral.sh/uv/),
Python 3.11+.

```bash
# 1) 의존성 설치
uv sync

# 2) 환경 변수 — .env.example 복사 후 필요시 포트만 조정
cp .env.example .env

# 3) Postgres 컨테이너 기동 (healthy 대기 포함)
make db-up

# 4) 테스트
make test
```

호스트의 5432가 다른 Postgres에 점유돼 있으면 `.env`의 `POSTGRES_PORT`와
`DATABASE_URL`의 포트를 5433 같은 빈 포트로 같이 바꿔준다.

## 주요 Make 타겟

| 타겟 | 동작 |
|---|---|
| `make db-up` | Postgres 16 컨테이너 기동 (healthy 대기) |
| `make db-down` | 컨테이너만 중지 (데이터 유지) |
| `make db-reset` | 컨테이너 + 볼륨 삭제 후 재기동 (완전 리셋) |
| `make db-shell` | psql 셸 접속 |
| `make test` | `uv run pytest -v` |
| `make ingest` | 공식 단일 수집 명령. 첫 baseline 전에는 백필, 이후에는 증분 동기화 |
| `make ingest-backfill` | 진단용: hosted Postgres migration 전 로컬 100% 백필 실행 |
| `make sanity-check` | 현재 로컬 적재 결과 통합 검증 리포트 생성 |
| `make data-completeness` | 현재 로컬 적재 결과 데이터 완성도 follow-up 리포트 생성 |
| `make migration-readiness` | hosted Postgres migration 전 readiness 리포트 생성 |

`ingest-members`, `ingest-bills`, `ingest-votes`, `ingest-meetings`,
`ingest-utterances`, `ingest-session-groups`는 개발/진단용 stage 명령이다.
일반 운영 흐름에서는 `make ingest`를 사용한다.

Hosted Postgres 이전에는 [docs/PRE-MIGRATION-BACKFILL-GATE.md](docs/PRE-MIGRATION-BACKFILL-GATE.md)에 따라
깨끗한 로컬 DB에서 100% 백필을 모니터링하고, 이상 지점을 수정한 뒤 idempotency 재실행까지 통과해야 한다.

## 구조

```
congress_db/      # Python 패키지
db/
  migrations/     # schema.sql 이후 적용되는 변경 SQL
tests/            # pytest 통합 테스트
docs/             # PRD / IA / ERD
docker-compose.yml
Makefile
pyproject.toml    # uv 관리
.env.example
```
