.PHONY: db-up db-down db-migrate db-shell db-reset test

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
