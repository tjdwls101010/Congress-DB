.PHONY: db-up db-down db-migrate db-shell db-reset test \
        seed-catalog verify-catalog render-catalog ingest-members ingest-bills \
        ingest-votes ingest-meetings validate-minutes-dom ingest-utterances \
        ingest-session-groups ingest-backfill validate-session-groups evaluate-session-groups \
        sanity-check data-completeness

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

# api_catalog seed (PRD 확정 10개 endpoint UPSERT)
seed-catalog:
	uv run python -m scripts.seed_api_catalog

# api_catalog verify (10개 endpoint 실제 호출 + 결과 기록)
verify-catalog:
	uv run python -m scripts.verify_api_catalog

# docs/API-CATALOG.md 자동 생성
render-catalog:
	uv run python -m scripts.render_api_catalog

# members 적재 (국회의원 인적사항 API -> members)
ingest-members:
	uv run python -m scripts.ingest_members

# bills + bill_coproposers 적재 (기본 10%)
ingest-bills:
	uv run python -m scripts.ingest_bills

# votes 적재 (기본 10%)
ingest-votes:
	uv run python -m scripts.ingest_votes

# meetings + agenda_items + meeting_bills 적재 (기본 캘리브레이션 500건)
ingest-meetings:
	uv run python -m scripts.ingest_meetings

# utterances 적재 (기본 캘리브레이션 500건)
ingest-utterances:
	uv run python -m scripts.ingest_utterances

# 회의록 DOM 구조 다층 샘플 검증
validate-minutes-dom:
	uv run python -m scripts.validate_minutes_dom

# session_groups 적재 (기본 캘리브레이션 500건)
ingest-session-groups:
	uv run python -m scripts.ingest_session_groups

# 로컬 100% 백필 실행 (Supabase migration 전 PM gate의 입력)
ingest-backfill:
	uv run python -m scripts.ingest_backfill

# session_groups 생성률/정합성 검증
validate-session-groups:
	uv run python -m scripts.validate_session_groups

# session_groups 정확도 검증 라벨/리포트 생성
evaluate-session-groups:
	uv run python -m scripts.evaluate_session_groups

# 10% 통합 sanity check + FTS 결정 리포트 생성
sanity-check:
	uv run python -m scripts.sanity_check

# 10% 데이터 완성도 follow-up 리포트 생성
data-completeness:
	uv run python -m scripts.data_completeness
