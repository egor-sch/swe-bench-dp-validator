#!/bin/bash

# SWE-bench Data Point Validator
# Validate the specific SWE-bench data point using the official SWE-bench library.
# Usage: ./scripts/validate_swe_bench.sh [options]

set -e

# Change to the project root directory
cd "$(dirname "$0")/.."

# Install dependencies
uv sync

# Use UV to run the Python module with all arguments passed through
uv run python -m swe_bench_validator "$@"
