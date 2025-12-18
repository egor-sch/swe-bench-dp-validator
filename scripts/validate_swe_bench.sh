#!/bin/bash

# SWE-bench Data Point Validator
# Validate the specific SWE-bench data point using the official SWE-bench library.
# Usage: ./scripts/validate_swe_bench.sh [options]

set -e

# Change to the project root directory
cd "$(dirname "$0")/.."

# Install dependencices
uv sync

# Use UV to run the Python module with all arguments passed through
# Capture exit code to ensure it's propagated
uv run python -m swe_bench_validator "$@"
EXIT_CODE=$?
exit $EXIT_CODE
