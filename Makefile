.PHONY: up down lint test load load-a load-b seed demo
up:
	docker compose up --build
down:
	docker compose down
lint:
	cd backend && uv run ruff check . && uv run mypy app
test:
	cd backend && uv run pytest
seed:
	cd backend && uv run python -m app.seed
load:
	cd backend && uv run locust -f ../tests/load/locustfile.py --host http://localhost:8001
load-a:
	powershell -ExecutionPolicy Bypass -File tests/load/run_profiles.ps1 -Profile A
load-b:
	powershell -ExecutionPolicy Bypass -File tests/load/run_profiles.ps1 -Profile B
demo:
	docker compose up --build
