mer#!/bin/bash
# =============================================================================
# Fix PostgreSQL Database Schema
# =============================================================================
# This script reinitializes the PostgreSQL database if tables are missing
# =============================================================================

set -e

cd "$(dirname "$0")"

# Detect container tool
if command -v podman &> /dev/null; then
    DOCKER_CMD="podman"
else
    DOCKER_CMD="docker"
fi

echo "================================================================================"
echo "PostgreSQL Database Schema Fix"
echo "================================================================================"
echo ""

# Check if PostgreSQL container is running
if ! $DOCKER_CMD ps | grep -q chat_postgres; then
    echo "ERROR: PostgreSQL container (chat_postgres) is not running"
    echo "Please start services first: bash docker_files/start_all.sh"
    exit 1
fi

echo "✓ PostgreSQL container is running"
echo ""

# Test connection
echo "Testing PostgreSQL connection..."
if ! $DOCKER_CMD exec chat_postgres psql -U chainlit -d chainlit -c "SELECT 1;" > /dev/null 2>&1; then
    echo "ERROR: Cannot connect to PostgreSQL database"
    exit 1
fi
echo "✓ Connection successful"
echo ""

# Check if steps table exists
echo "Checking for 'steps' table..."
STEPS_EXISTS=$($DOCKER_CMD exec chat_postgres psql -U chainlit -d chainlit -t -c "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'steps');" | tr -d '[:space:]')

if [ "$STEPS_EXISTS" = "t" ]; then
    echo "✓ 'steps' table already exists"
    echo ""
    echo "Listing all tables:"
    $DOCKER_CMD exec chat_postgres psql -U chainlit -d chainlit -c "\dt"
else
    echo "✗ 'steps' table does NOT exist - reinitializing schema..."
    echo ""

    # Run the initialization script
    echo "Running init_chainlit_schema.sql..."
    $DOCKER_CMD exec -i chat_postgres psql -U chainlit -d chainlit < postgres/init_chainlit_schema.sql

    echo ""
    echo "✓ Schema initialized successfully"
    echo ""
    echo "Listing all tables:"
    $DOCKER_CMD exec chat_postgres psql -U chainlit -d chainlit -c "\dt"
fi

echo ""
echo "================================================================================"
echo "Database Schema Status"
echo "================================================================================"
echo ""

# Show table counts
echo "Table row counts:"
$DOCKER_CMD exec chat_postgres psql -U chainlit -d chainlit -c "
SELECT
    schemaname,
    tablename,
    (xpath('/row/cnt/text()', xml_count))[1]::text::int as row_count
FROM (
  SELECT
    schemaname,
    tablename,
    query_to_xml(format('select count(*) as cnt from %I.%I', schemaname, tablename), false, true, '') as xml_count
  FROM pg_tables
  WHERE schemaname = 'public'
) t
ORDER BY tablename;
"

echo ""
echo "✓ PostgreSQL database is ready"
echo ""
