.PHONY: help docker-up docker-down docker-reset setup-db test test-unit test-integration migrate validate clean

# Default target
help:
	@echo "DestaquesGovBr Data Platform - Makefile Commands"
	@echo ""
	@echo "Docker Commands:"
	@echo "  make docker-up        - Start PostgreSQL container"
	@echo "  make docker-down      - Stop PostgreSQL container"
	@echo "  make docker-reset     - Reset PostgreSQL (remove all data)"
	@echo "  make docker-logs      - Show PostgreSQL logs"
	@echo ""
	@echo "Database Commands:"
	@echo "  make setup-db         - Setup local database (schema + master data)"
	@echo "  make populate-master  - Populate agencies and themes"
	@echo "  make psql             - Connect to PostgreSQL with psql"
	@echo ""
	@echo "Testing Commands:"
	@echo "  make test             - Run all tests"
	@echo "  make test-unit        - Run unit tests only"
	@echo "  make test-integration - Run integration tests only"
	@echo ""
	@echo "Migration Commands:"
	@echo "  make migrate          - Migrate data from HuggingFace (test: 1000 records)"
	@echo "  make migrate-full     - Migrate ALL data from HuggingFace"
	@echo "  make validate         - Validate migration"
	@echo ""
	@echo "Cleanup Commands:"
	@echo "  make clean            - Clean Python cache files"
	@echo "  make clean-all        - Clean everything (cache + docker volumes)"

# Docker commands
docker-up:
	@echo "Starting PostgreSQL container..."
	docker-compose up -d
	@echo "Waiting for PostgreSQL to be ready..."
	@sleep 3
	@docker exec destaquesgovbr-postgres pg_isready -U destaquesgovbr_dev || (echo "PostgreSQL not ready yet, waiting more..." && sleep 5)
	@echo "PostgreSQL is ready!"

docker-down:
	@echo "Stopping PostgreSQL container..."
	docker-compose down

docker-reset:
	@echo "Resetting PostgreSQL (removing all data)..."
	docker-compose down -v
	@echo "Starting fresh PostgreSQL..."
	docker-compose up -d
	@sleep 3

docker-logs:
	docker-compose logs -f postgres

# Database commands
setup-db: docker-up
	@echo "Setting up local database..."
	@bash scripts/setup_local_db.sh

populate-master:
	@echo "Populating master tables..."
	DATABASE_URL="postgresql://destaquesgovbr_dev:dev_password@localhost:5433/destaquesgovbr_dev" \
		poetry run python scripts/populate_agencies.py && \
	DATABASE_URL="postgresql://destaquesgovbr_dev:dev_password@localhost:5433/destaquesgovbr_dev" \
		poetry run python scripts/populate_themes.py

psql:
	docker exec -it destaquesgovbr-postgres psql -U destaquesgovbr_dev -d destaquesgovbr_dev

# Testing commands
test:
	PYTHONPATH=src poetry run pytest tests/ -v

test-unit:
	PYTHONPATH=src poetry run pytest tests/unit/ -v

test-integration:
	DATABASE_URL="postgresql://destaquesgovbr_dev:dev_password@localhost:5433/destaquesgovbr_dev" \
		PYTHONPATH=src poetry run pytest tests/integration/ -v

# Migration commands
migrate:
	@echo "Running test migration (1000 records)..."
	DATABASE_URL="postgresql://destaquesgovbr_dev:dev_password@localhost:5433/destaquesgovbr_dev" \
		poetry run python scripts/migrate_hf_to_postgres.py --max-records 1000

migrate-full:
	@echo "Running FULL migration (all records)..."
	@read -p "This will migrate ALL records. Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		DATABASE_URL="postgresql://destaquesgovbr_dev:dev_password@localhost:5433/destaquesgovbr_dev" \
		poetry run python scripts/migrate_hf_to_postgres.py; \
	fi

validate:
	@echo "Validating migration..."
	DATABASE_URL="postgresql://destaquesgovbr_dev:dev_password@localhost:5433/destaquesgovbr_dev" \
		poetry run python scripts/validate_migration.py

# Cleanup commands
clean:
	@echo "Cleaning Python cache files..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true

clean-all: clean docker-reset
	@echo "All cleaned!"
