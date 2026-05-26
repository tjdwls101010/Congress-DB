.PHONY: db-up db-down db-shell db-reset test

# Postgres 컨테이너 기동 (백그라운드 + healthy 대기)
db-up:
	docker compose up -d
	@echo "Waiting for Postgres to become healthy..."
	@until [ "$$(docker inspect -f '{{.State.Health.Status}}' congress-db 2>/dev/null)" = "healthy" ]; do \
		sleep 1; \
	done
	@echo "Postgres is ready."

# 컨테이너 중지 (데이터 유지)
db-down:
	docker compose down

# 컨테이너 + 볼륨 삭제 후 재기동 (완전 리셋)
db-reset:
	docker compose down -v
	$(MAKE) db-up

# psql 셸 접속
db-shell:
	docker compose exec db psql -U $${POSTGRES_USER:-congress} -d $${POSTGRES_DB:-congress}

# 테스트 실행
test:
	uv run pytest -v
