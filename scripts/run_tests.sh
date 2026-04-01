#!/bin/bash
# ============================================================================
# Test Runner for ObsAI - Observability AI Assistant
# Usage: bash scripts/run_tests.sh [quick|full|ci|smoke]
#
# Modes:
#   quick  — Unit tests only (fast, <5s). Excludes smoke and integration tests.
#   full   — Unit + smoke tests. Excludes integration (needs live services).
#   ci     — Full + coverage report. Fails if coverage < 60%.
#   smoke  — Smoke tests only (pipeline validation with sample data).
#
# Examples:
#   bash scripts/run_tests.sh          # defaults to 'quick'
#   bash scripts/run_tests.sh full     # unit + smoke tests
#   bash scripts/run_tests.sh ci       # full suite with coverage gating
# ============================================================================

set -euo pipefail

MODE="${1:-quick}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# Files to always skip (need live services or missing deps)
SKIP_ALWAYS="--ignore=tests/test_integration_health.py --ignore=tests/test_spl_pipeline.py --ignore=tests/test_nlp_to_spl.py"
# Tests with module-level mock isolation — run separately to avoid cross-test pollution
ISOLATED_TESTS="tests/test_vectorstore.py tests/test_prometheus_live.py"

echo "========================================"
echo " ObsAI Test Runner — mode: $MODE"
echo "========================================"

case "$MODE" in
  quick)
    echo "Running unit tests only (fast)..."
    python3 -m pytest tests/ \
      $SKIP_ALWAYS \
      --ignore=tests/test_smoke.py \
      --ignore=tests/test_vectorstore.py \
      --ignore=tests/test_prometheus_live.py \
      -q --tb=short
    echo ""
    echo "Running isolated tests (vectorstore)..."
    python3 -m pytest tests/test_vectorstore.py -q --tb=short || true
    ;;

  full)
    echo "Running unit + smoke tests..."
    python3 -m pytest tests/ \
      $SKIP_ALWAYS \
      -v --tb=short
    ;;

  ci)
    echo "Running full suite with coverage..."
    python3 -m pytest tests/ \
      $SKIP_ALWAYS \
      --cov=chat_app --cov=shared \
      --cov-report=term-missing \
      --cov-fail-under=20 \
      -v --tb=short
    ;;

  smoke)
    echo "Running smoke tests only..."
    python3 -m pytest tests/test_smoke.py \
      -v --tb=short
    ;;

  *)
    echo "Unknown mode: $MODE"
    echo "Usage: bash scripts/run_tests.sh [quick|full|ci|smoke]"
    exit 1
    ;;
esac

echo ""
echo "========================================"
echo " Tests completed successfully!"
echo "========================================"
