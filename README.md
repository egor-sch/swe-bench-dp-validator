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

## GitHub Actions

This repository includes GitHub Actions workflows for automated validation:

### Automated Validation (`validate-datapoints.yml`)

Automatically validates data points when they are added or modified in pull requests or pushes.

**Triggers:**
- Push events affecting files in `data_points/**`
- Pull request events affecting files in `data_points/**`

**Features:**
- Detects only changed/new data point files (performance optimization)
- Validates all changed data points in parallel
- Reports validation results as status checks
- Uploads detailed logs and evaluation outputs as artifacts
- Fails the workflow if any validation fails

**Usage:** No manual action required - the workflow runs automatically when you push or create a PR with changes to `data_points/` files.

### Manual Validation (`validate-datapoint-manual.yml`)

Manually trigger validation for specific data points from the GitHub Actions UI.

**Usage:**
1. Go to the "Actions" tab in your repository
2. Select "Validate SWE-bench Data Point (Manual)"
3. Click "Run workflow"
4. Enter data point name(s) (comma-separated, without `.json` extension)
   - Example: `astropy__astropy-11693`
   - Multiple: `astropy__astropy-11693,astropy__astropy-11692`
5. Click "Run workflow"

**Use cases:**
- Testing validation before committing
- Re-validating existing data points
- Debugging validation issues

## Architecture Documentation

For detailed information about how the validator integrates with SWE-bench's Docker-based evaluation infrastructure, see [swe-bench-docker-architecture.md](swe-bench-docker-architecture.md).

This document explains:
- The 3-layer Docker image system (Base → Environment → Instance)
- Image building process and dependency installation
- Test execution flow and patch application
- How the validator integrates with the evaluation harness
