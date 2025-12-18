# SWE-bench Docker Architecture

## Introduction

The SWE-bench evaluation harness uses Docker containers to create reproducible environments for evaluating model-generated patches on software repositories. This containerized approach ensures consistent evaluation results across different platforms and eliminates environmental discrepancies. This document describes the Docker architecture, image building process, test execution flow, and how validators integrate with this infrastructure.

## Docker Architecture Overview

The SWE-bench evaluation harness builds Docker images in three layers:

1. **Base image**: Common dependencies for all evaluations (Language and tooling support). It is the lowest layer. Its Dockerfile installs the OS, language toolchain (e.g. Python), and common utilities needed by all benchmarks.
2. **Environment images**: Python environments for different configurations (~60 images) (Repository-specific dependencies). Each **environment image** is built **FROM a base image**. Its Dockerfile and `setup_env.sh` script install repository-specific dependencies: Python packages, system libraries, test tools, etc. Multiple SWE-bench instances for the same repository can share a single environment image.
3. **Instance images**: Specific dependencies for each evaluation task (problem-specific configurations). For a specific SWE-bench data point, the instance layer:
    - Checks out the target repository at the specified commit,
    - Runs any repository-specific setup needed to prepare the project for testing,
    - Adds any instance-specific files or configuration.
    This produces a self-contained image that is ready to accept a solution patch and run tests for exactly one SWE-bench instance.

## Image Building Process

The SWE-bench harness builds Docker images on demand as evaluations are prepared and run. For each layer (base, environment, instance), it follows the same pattern: check whether the required image already exists, and if not, build it. Depending on how you invoke the harness, some or all of these images may be created in an explicit preparation step, or they may be created lazily the first time an instance that needs them is evaluated.

### Base images

Base images are the foundation for all other layers. They contain the operating system, language runtime (for example, a specific Python version), and common tooling shared across many repositories.

- For a given set of SWE-bench instances, the harness computes which base image keys are required. Each key uniquely identifies a base image (including name, tag, and platform).
- Whenever an operation (either a preparation command or an evaluation run) needs a particular base image, it first checks whether a local image matching that key already exists.
- If the image is missing, it is built once by generating a Dockerfile that installs the OS, language runtime, and shared tools, and then invoking a Docker build.
- Once built, the same base image is reused by all environment and instance images that depend on that key, unless a configuration option explicitly forces a rebuild.

In practice, this means base images may be created ahead of time in a dedicated “prepare images” step, or created the first time an evaluation needs them, but they are not rebuilt for every instance.

### Environment images

Environment images sit on top of base images and capture repository‑specific dependencies: Python packages, system libraries, and any test tools needed to run that project’s test suite.

- For each repository present in the selected SWE-bench instances, the harness determines which environment image key is required (for example, “Django, Python 3.11, specific dependency set”).
- When a repository is about to be used (either during a preparation phase or the first time one of its instances is run), the harness checks whether the corresponding environment image already exists.
- If it does not, the harness builds it by:
  - Starting from the correct base image,
  - Running a setup script inside the Docker build context that installs the repository’s dependencies (e.g. via `pip` and system package managers),
  - Producing a tagged environment image that can be shared by all instances from that repository.

As with base images, an environment image is typically built once for a given configuration and then reused across many instance images and evaluation runs.

### Instance images

Instance images are the most specific layer and are tightly coupled to individual SWE-bench data points. Each instance image represents a particular repository at a particular commit, prepared and ready for testing.

- When the harness is about to evaluate a specific data point, it:
  - Identifies the environment image that should be used as the parent,
  - Checks whether an instance image for that data point already exists.
- If the instance image is missing, the harness builds it just in time by:
  - Starting from the appropriate environment image,
  - Checking out the target repository at the commit specified in the data point,
  - Running any repository-specific setup steps (install commands, pre-install hooks, etc.) needed to get the project ready for tests.
- Once the instance image exists, the harness starts a container from it and runs the test commands for that data point inside the container.

Because instance images depend on their environment images, the system behaves as if there is a “preparation” phase for shared layers (base and environment), followed by per-instance builds for the final layer. Whether the shared layers are created in an explicit preparation command or on the first evaluation that needs them is controlled by how you run the harness, but the logical layering and reuse pattern remains the same.

### Where data point requirements are installed

- Repository dependencies (Python/system/test tools) are installed during the **environment image** build, so they’re shared across all instances for that repo.
- Repository checkout and any repo-specific setup (clone, reset to base commit, repo install hooks) happen during the **instance image** build, so each instance starts from a clean, ready-to-test workspace.
- The **solution patch** (model or gold) is applied at runtime inside the container immediately before the evaluation script runs.
- The **test patch** from the data point is applied at runtime inside the container (in `eval.sh`) just before tests run, then reverted after tests finish.

### Optional pre-building of instance images

In addition to building instance images on demand, SWE-bench also supports an optional preparation phase that walks over a set of data points and pre-builds all corresponding instance images. When this workflow is used, subsequent evaluation runs can immediately start containers and run tests, trading higher upfront build time and disk usage for more predictable evaluation latency.

## Test Execution Flow

Once the necessary Docker images exist, the SWE-bench harness evaluates each data point by starting a container from the corresponding instance image and running the repository’s tests inside that container. This section describes how patches are applied, how tests are executed with timeouts, and how outputs are parsed into final evaluation results.

### High-level per-instance flow

For each SWE-bench data point selected for evaluation, the harness performs the following steps:

1. Ensure the instance image for that data point exists (building it on demand if needed).
2. Start a new Docker container from the instance image.
3. Apply the solution patch (model prediction or gold patch) inside the container’s working copy of the repository.
4. Run the evaluation script inside the container, which applies the test patch that modifies the test files and then executes the test command with a configured timeout.
5. Capture and store the full test output log.
6. Parse the log to determine which tests passed or failed and whether the instance is considered resolved.
7. Clean up the container and, depending on cache settings, optionally remove the instance image.

Each instance is evaluated in isolation in its own container, and multiple instances can be processed in parallel by using multiple worker processes.

### Patch application process

Two different patches can be applied during evaluation:

- A **solution patch** (the model prediction or gold patch) that changes the repository’s source code to fix the bug.
- A **test patch** that adjusts the test files themselves (for example, adding or updating tests that capture the intended behavior).

The solution patch is applied first:

- The harness writes the solution patch text from the prediction file (or gold data) to a temporary `patch.diff` file on the host.
- This file is copied into the running container next to the repository working tree.
- Inside the container, the harness attempts to apply the patch to the repository using a sequence of `git apply` commands with different option combinations.
- If one of these commands succeeds (exit code 0), the patch is considered successfully applied and evaluation continues.
- If all attempts fail, the harness logs a “patch apply failed” message, marks the instance as an evaluation error, and skips running tests for that instance.

The test patch is handled inside the evaluation script:

- The `eval.sh` script generated for the instance contains commands that:
  - Reset the relevant test files to their state at the base commit,
  - Apply the `test_patch` from the SWE-bench instance using `git apply`,
  - Run the repository’s test command,
  - Reset the test files back again after the tests finish.
- This ensures the test suite reflects the benchmark’s intended checks but leaves the repository in a clean state once evaluation completes.

### Test command execution with timeout

After the solution patch has been successfully applied, the harness runs the test suite for that repository and instance:

- The harness generates a shell script named `eval.sh` that contains the evaluation commands for that instance. This script:
  - Activates the correct environment inside the container,
  - Navigates to the repository directory,
  - Applies the test patch to the relevant test files,
  - Runs the project’s test runner with the subset of tests relevant for the SWE-bench instance (covering both `FAIL_TO_PASS` and `PASS_TO_PASS` test groups),
  - Resets the test files back to their original state after tests complete.
- The `eval.sh` script is copied into the container and then invoked via a shell command.
- Execution is wrapped in a timeout mechanism:
  - If the tests finish before the timeout, the harness records the total runtime and captures all stdout/stderr output.
  - If the timeout is exceeded, the harness:
    - Stops the test execution,
    - Appends a timeout message to the test output log,
    - Marks the instance as an evaluation error due to timeout.

The complete test output (including any test runner output, tracebacks, and timeout messages) is saved to a per-instance log file for later inspection.

### Output parsing and result extraction

Once test execution completes (or times out), the harness converts raw logs into structured evaluation results:

- It may capture a second `git diff` of the repository to detect if the evaluation script itself modified any files (for debugging and auditing).
- The test output log is passed to a grading component that:
  - Identifies the status of each relevant test (pass/fail/error),
  - Groups results by `FAIL_TO_PASS` and `PASS_TO_PASS` expectations,
  - Determines whether the instance is **resolved**, meaning:
    - All previously failing tests in `FAIL_TO_PASS` now pass, and
    - All tests in `PASS_TO_PASS` remain passing.
- The grading step produces a machine-readable JSON report (report.json) summarizing:
  - Whether the instance was successfully evaluated,
  - Whether it was resolved,
  - Any errors (patch-apply failures, timeouts, infrastructure issues),
  - Detailed per-test results.

These per-instance reports are aggregated into a final evaluation summary for the whole run.

### Concrete example

As a concrete example, consider evaluating a single SWE-bench instance for a Python project:

1. The harness ensures the base and environment images for that project exist, and builds the instance image that contains the project’s repository at the specified base commit.
2. It starts a container from this instance image and copies the model’s predicted patch into the container.
3. Inside the container, it applies the patch to the repository using `git apply`. If this fails, the instance is reported as a patch-application error and no tests are run.
4. If the patch applies, the harness copies an `eval.sh` script into the container that:
   - Activates the project’s conda environment,
   - Runs the subset of tests defined by the SWE-bench instance.
5. The harness runs `eval.sh` with a configured timeout (by default - 1,800 seconds), capturing all output to a log file.
6. After the command completes, the grading logic parses the log to see which tests passed or failed and sets the `resolved` flag for this instance accordingly.
7. The container is stopped and removed, and the per-instance report is written to disk and later included in the overall evaluation metrics.

This flow is repeated independently for each data point selected for evaluation, reusing Docker images whenever possible to keep the process efficient.

## Integration Points

The validator integrates with SWE-bench's Docker-based evaluation infrastructure indirectly, by using the official `swebench.harness.run_evaluation` harness as the execution engine.

### Input preparation

The validator reads SWE-bench data point files from the `data_points/` directory. Each file contains a complete instance description in the standard SWE-bench dataset format, including fields such as `instance_id`, `repo`, `base_commit`, `patch`, `test_patch`, `FAIL_TO_PASS`, and `PASS_TO_PASS`.

For each data point being validated, the validator constructs a prediction entry that the harness can consume:

- **`instance_id`**: Copied directly from the data point file.
- **`model_name_or_path`**: Set to a descriptive label (`"validator"`) to identify validator runs in logs and reports.
- **`model_patch`**: Populated from the data point's `patch` field, representing the solution patch to be evaluated.

These prediction entries are written to a temporary predictions file (JSONL format) in the exact structure expected by `swebench.harness.run_evaluation`.

### Harness invocation

The validator invokes the official SWE-bench evaluation harness, by calling `swebench.harness.run_evaluation.main()` as a Python function. The harness is configured with:

- **Dataset source**: Points to the same data point files being validated.
- **Predictions path**: The temporary predictions file generated in the previous step.
- **Instance filtering**: Limited to the specific `instance_id` values being validated.
- **Runtime configuration**: Appropriate timeouts, worker counts, cache levels, and other options for the validation environment.

Once invoked, the harness takes full control of Docker operations: it builds or reuses base, environment, and instance images as needed; starts containers; applies patches; runs tests; and writes logs and reports. The validator does not manage Docker images or containers directly.

### Result interpretation

After the harness completes evaluation, the validator reads the harness's output artifacts:

- **Per-instance reports**: Each evaluated instance produces a `report.json` file in a structured location within the harness's log directory hierarchy. These reports contain:
  - Whether evaluation completed successfully (no infrastructure errors, timeouts, or patch-apply failures),
  - Whether the instance is considered **resolved** (all `FAIL_TO_PASS` tests now pass, all `PASS_TO_PASS` tests remain passing),
  - Detailed per-test status information,
  - Any error messages or diagnostic information.

- **Test output logs**: Raw test execution logs (`test_output.txt`) are also available for detailed inspection if needed.

The validator aggregates these reports to classify each data point as **valid** or **invalid**:

- A data point is **valid** if:
  - Evaluation completed without infrastructure errors,
  - All tests in `FAIL_TO_PASS` pass after applying the patch,
  - All tests in `PASS_TO_PASS` remain passing.

- A data point is **invalid** if any of the above conditions fail, with specific error reasons surfaced (for example, "patch apply failed", "tests in FAIL_TO_PASS still failing", "tests in PASS_TO_PASS broken", "evaluation timed out", "Docker image build failed").

### Error handling and diagnostics

When the harness encounters issues (Docker build failures, container startup problems, test timeouts, or patch-apply failures), these are encoded in the harness's logs and report structures. The validator translates these harness-level conditions into clear validation failures, directing users to the appropriate log files for debugging. The validator does not attempt to fix Docker or test infrastructure problems; it surfaces them as validation failures with actionable error messages.
