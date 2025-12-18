#!/bin/bash

# SWE-bench Data Point Validator
# Validate the specific SWE-bench data point using the official SWE-bench library.
# Usage: ./scripts/validate_swe_bench.sh [options]

# Change to the project root directory
cd "$(dirname "$0")/.."

# Install dependencices
uv sync

# Use UV to run the Python module with all arguments passed through
# Capture exit code to ensure it's propagated
set +e  # Don't exit on error, we'll handle it explicitly
uv run python -m swe_bench_validator "$@"
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    exit $EXIT_CODE
fi
exit 0
