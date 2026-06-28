.PHONY: db-up db-down db-migrate db-shell db-reset test ingest safe-update \
        render-catalog ingest-members ingest-bills \
        ingest-bill-relations ingest-bill-summaries ingest-votes \
        backfill-bill-source-aliases backfill-bill-final-outcomes ingest-backfill sanity-check data-completeness migration-readiness regression-pack

# .env가 있으면 변수 자동 로드 (없어도 통과)
-include .env
export

# Postgres 컨테이너 기동 + healthy 대기 + schema 자동 적용
db-up:
	docker compose up -d
	@echo "Waiting for Postgres to become healthy..."
	@until [ "$$(docker inspect -f '{{.State.Health.Status}}' congress-db 2>/dev/null)" = "healthy" ]; do \
		sleep 1; \
	done
	@echo "Postgres is ready."
	@$(MAKE) db-migrate

# 컨테이너 중지 (데이터 유지)
db-down:
	docker compose down

# db/schema.sql 적용 (CREATE TABLE IF NOT EXISTS → 멱등)
db-migrate:
	@echo "Applying db/schema.sql..."
	@docker compose exec -T db psql \
		-U $${POSTGRES_USER:-congress} \
		-d $${POSTGRES_DB:-congress} \
		-1 -v ON_ERROR_STOP=1 < db/schema.sql
	@for migration in db/migrations/*.sql; do \
		[ -e "$$migration" ] || continue; \
		echo "Applying $$migration..."; \
		docker compose exec -T db psql \
			-U $${POSTGRES_USER:-congress} \
			-d $${POSTGRES_DB:-congress} \
			-1 -v ON_ERROR_STOP=1 < "$$migration"; \
	done
	@echo "Schema applied."

# 컨테이너 + 볼륨 삭제 후 재기동 (완전 리셋, schema 재적용)
db-reset:
	docker compose down -v
	$(MAKE) db-up

# psql 셸 접속
db-shell:
	docker compose exec db psql -U $${POSTGRES_USER:-congress} -d $${POSTGRES_DB:-congress}

# 테스트 실행
test:
	uv run pytest -v

# 공식 단일 수집 명령 (auto: 첫 baseline 전에는 backfill, 이후에는 incremental)
ingest:
	uv run python -m scripts.ingest

# 안전 Neon 업데이트: 백업 브랜치 → 증분 수집 → 무손상 검증 → 손상 시 자동 복원
# (CONGRESS_MAIN_URL·NEON_API_KEY 는 .env.local 에서 읽는다)
safe-update:
	uv run python -m scripts.safe_update

# docs/ops/API-CATALOG.md 자동 생성
render-catalog:
	uv run python -m scripts.render_api_catalog

# 진단용: members 적재 (국회의원 인적사항 API -> members)
ingest-members:
	uv run python -m scripts.ingest_members

# 진단용: bills + bill_coproposers 적재 (기본 10%)
ingest-bills:
	uv run python -m scripts.ingest_bills

# 진단용: 기존 bills 중 결측 summary만 백필
ingest-bill-summaries:
	uv run python -m scripts.ingest_bill_summaries

# 진단용: bill_relations 대안 관계 백필
ingest-bill-relations:
	uv run python -m scripts.ingest_bill_relations

# 진단용: bill_relations source id를 canonical bills에 alias 연결
backfill-bill-source-aliases:
	uv run python -m scripts.backfill_bill_source_aliases

# 진단용: ALLBILL 공포 이력 + 결측 propose_dt 백필
backfill-bill-final-outcomes:
	uv run python -m scripts.backfill_bill_final_outcomes

# 진단용: votes 적재 (기본 10%)
ingest-votes:
	uv run python -m scripts.ingest_votes

# 진단용: 로컬 100% 백필 실행 (hosted Postgres migration 전 PM gate의 입력)
ingest-backfill:
	uv run python -m scripts.ingest_backfill

# 현재 로컬 적재 결과 통합 sanity check + FTS 결정 리포트 생성
sanity-check:
	uv run python -m scripts.sanity_check

# 현재 로컬 적재 결과 데이터 완성도 follow-up 리포트 생성
data-completeness:
	uv run python -m scripts.data_completeness

# hosted Postgres migration 전 로컬 백필 readiness 리포트 생성
migration-readiness:
	uv run python -m scripts.migration_readiness

# M3 demand-gate: 4개 retrieval anchor read-only regression pack
regression-pack:
	uv run python -m scripts.regression_pack
