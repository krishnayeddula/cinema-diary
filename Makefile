PB       := ./bin/pocketbase
PB_FLAGS := --dir=./pb_data --migrationsDir=./pb_migrations --hooksDir=./pb_hooks --publicDir=./pb_public

.PHONY: serve test lint fmt check sandbox

serve:
	$(PB) serve $(PB_FLAGS) --http=127.0.0.1:8090

test:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

check: lint test

sandbox:
	$(PB) serve --dir=./sandbox/pb_data --migrationsDir=./sandbox/pb_migrations --hooksDir=./sandbox/pb_hooks --http=127.0.0.1:8091
