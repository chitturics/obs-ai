#!/bin/bash
#
# Runs all ingestion scripts in parallel to populate the vector stores.
#
# This script is a convenience wrapper that calls the individual
# ingestion scripts for each data source as background jobs.
#

set -e

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

echo "========================================================================"
echo " Running All Ingestion Scripts in Parallel"
echo "========================================================================"

# Array to hold background job PIDs
pids=()
scripts_to_run=()

# Discover scripts to run
# The commented-out scripts are kept here for reference
# if [ -f "$SCRIPT_DIR/run_ingest_specs.sh" ]; then
#     scripts_to_run+=("$SCRIPT_DIR/run_ingest_specs.sh")
# fi
# if [ -f "$SCRIPT_DIR/run_ingest_spl_commands.sh" ]; then
#     scripts_to_run+=("$SCRIPT_DIR/run_ingest_spl_commands.sh")
# fi
if [ -f "$SCRIPT_DIR/run_ingest_org_and_local.sh" ]; then
    scripts_to_run+=("$SCRIPT_DIR/run_ingest_org_and_local.sh")
fi
if [ -f "$SCRIPT_DIR/run_ingest_cribl.sh" ]; then
    scripts_to_run+=("$SCRIPT_DIR/run_ingest_cribl.sh")
fi

# Check if there are any scripts to run
if [ ${#scripts_to_run[@]} -eq 0 ]; then
    echo "No ingestion scripts found. Exiting."
    exit 0
fi

# Launch each script as a background job
for script in "${scripts_to_run[@]}"; do
    echo "Starting background ingestion for: $(basename "$script")"
    bash "$script" &
    pids+=($!)
done

echo ""
echo "All ingestion jobs started. Waiting for completion..."
echo "PIDs: ${pids[*]}"
echo ""

# Wait for each background job individually and capture exit codes
exit_code=0
for pid in "${pids[@]}"; do
    if ! wait "$pid" 2>/dev/null; then
        echo "ERROR: Ingestion job with PID $pid failed."
        exit_code=1
    fi
done

if [ "$exit_code" -ne 0 ]; then
    echo ""
    echo "========================================================================"
    echo " One or more ingestion jobs failed."
    echo "========================================================================"
    exit 1
fi

echo ""
echo "========================================================================"
echo " All Ingestion Scripts Completed Successfully"
echo "========================================================================"