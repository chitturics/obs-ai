# ObsAI Makefile — common development commands
.PHONY: build test deploy stop lint clean logs health frontend

# ── Build ──────────────────────────────────────────────
build:
	podman build -f docker_files/Dockerfile.app -t chainlit-app:latest .

frontend:
	cd frontend && npm run build

build-all: frontend build

# ── Test ───────────────────────────────────────────────
test:
	bash scripts/run_tests.sh quick

test-verbose:
	PYTHONPATH=.:chat_app python3 -m pytest tests/ -v --tb=short

test-coverage:
	PYTHONPATH=.:chat_app python3 -m pytest tests/ --cov=chat_app --cov-report=term-missing

# ── Deploy ─────────────────────────────────────────────
deploy:
	podman stop chat_ui_app 2>/dev/null || true
	podman rm chat_ui_app 2>/dev/null || true
	bash docker_files/start_all.sh --no-ingest

deploy-full:
	bash docker_files/stop_all.sh
	bash docker_files/start_all.sh

stop:
	bash docker_files/stop_all.sh

# ── Lint & Type Check ──────────────────────────────────
lint:
	ruff check chat_app/ tests/ shared/ --fix

typecheck:
	mypy chat_app/settings.py chat_app/schemas.py chat_app/registry.py --ignore-missing-imports

lint-frontend:
	cd frontend && npx tsc --noEmit

# ── Logs & Health ──────────────────────────────────────
logs:
	podman logs -f chat_ui_app --tail 100

health:
	curl -s http://localhost:8000/ready | python3 -m json.tool

# ── Clean ──────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage
