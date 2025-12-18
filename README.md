# SWE-bench Data Point Validator

A validation system for SWE-bench data points that uses the official SWE-bench evaluation harness to verify that data points are correctly formatted and that patches successfully fix the intended issues.

This repository provides:
- **Validator**: Validates SWE-bench data points by running them through the official evaluation harness
- **Downloader**: Downloads SWE-bench data points from the official datasets
- **GitHub Actions**: Automated validation workflows for CI/CD integration

## Validator

The validator checks that:
- Data points are properly formatted (valid JSON, required fields present)
- Patches apply successfully to the target repositories
- All `FAIL_TO_PASS` tests pass after applying the patch
- All `PASS_TO_PASS` tests remain passing

### Usage

#### Using the shell script:

```bash
# Validate a single data point
./scripts/validate_swe_bench.sh --data_point_names "astropy__astropy-11693.json"

# Validate multiple data points
./scripts/validate_swe_bench.sh --data_point_names "astropy__astropy-11693.json" --data_point_names "astropy__astropy-11692.json"
```

#### Using UV directly:

```bash
# Validate a single data point
uv run python -m swe_bench_validator --data_point_names "astropy__astropy-11693.json"

# Validate multiple data points
uv run python -m swe_bench_validator --data_point_names "astropy__astropy-11693.json" --data_point_names "astropy__astropy-11692.json" --verbose
```

**Options:**
- `--data_point_names`: Data point file name(s) to validate (can be used multiple times)
- `--timeout`: Timeout in seconds for running tests (default: 1800)
- `--verbose` / `-v`: Enable verbose output with detailed logging

## Downloader

The downloader fetches SWE-bench data points from official datasets and saves them to the `data_points/` directory.

### Usage

#### Using the shell script:

```bash
./scripts/download_swe_bench.sh --instance_id "django__django-12345"
```

#### Using UV directly:

```bash
uv run python -m swe_bench_downloader --instance_id "django__django-12345"
```

**Common options:**
- `--instance_id`: Specific SWE-bench instance identifier
- `--repo`: Repository filter (e.g., 'django/django')
- `--dataset`: Dataset name ('swe-bench', 'swe-bench-lite', etc., default: 'swe-bench')
- `--split`: Data split ('train', 'test', 'dev', default: 'test')
- `--limit`: Maximum number of data points to download

## Architecture Documentation

For detailed information about how the validator integrates with SWE-bench's Docker-based evaluation infrastructure, see [swe-bench-docker-architecture.md](swe-bench-docker-architecture.md).

This document explains:
- The 3-layer Docker image system (Base → Environment → Instance)
- Image building process and dependency installation
- Test execution flow and patch application
- How the validator integrates with the evaluation harness
