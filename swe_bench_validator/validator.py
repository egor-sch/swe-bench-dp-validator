"""
Core Validator functionality for SWE-bench data points.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from rich.console import Console

from swebench.harness.run_evaluation import main as run_evaluation
from swebench.harness.constants import RUN_EVALUATION_LOG_DIR, LOG_REPORT

console = Console()
logger = logging.getLogger(__name__)

data_points_dir = "data_points"


class SWEBenchValidator:
    """
    Validates SWE-bench data points using the official SWE-bench library.
    Can validate multiple data points in parallel.
    tmp_dir must already exist.
    """

    def __init__(
        self,
        data_point_names: list[str],
        tmp_dir: Path,
        timeout: int,
    ):
        self.data_point_names = []
        self.data_points = {}  # instance_id -> data_point dict
        self.instance_id_to_name = {}  # instance_id -> file name mapping

        # Load and validate all data points
        for dp_name in data_point_names:
            # Ensure .json extension if not present
            if not dp_name.endswith(".json"):
                dp_name = f"{dp_name}.json"

            data_point_path = Path(data_points_dir) / dp_name

            if not data_point_path.exists():
                raise ValidationError(
                    dp_name,
                    f"Data point file not found: '{data_point_path}'."
                    " Ensure the file exists in the 'data_points' directory.",
                    "",
                    error_type="structural",
                )

            # Load data point - handle JSON parsing errors
            try:
                with data_point_path.open("r", encoding="utf-8") as f:
                    data_point = json.load(f)
            except json.JSONDecodeError as e:
                raise ValidationError(
                    dp_name,
                    f"Invalid JSON format in data point file: {str(e)}."
                    " Please check the file syntax.",
                    "",
                    error_type="structural",
                ) from e
            except Exception as e:
                raise ValidationError(
                    dp_name,
                    f"Failed to read data point file: {str(e)}",
                    "",
                    error_type="structural",
                ) from e

            # Validate required fields
            instance_id = data_point.get("instance_id")
            if instance_id is None:
                raise ValidationError(
                    dp_name,
                    "Missing required field 'instance_id' in data point file."
                    " Please ensure the data point follows the SWE-bench format.",
                    "",
                    error_type="structural",
                )

            patch = data_point.get("patch")
            if patch is None or patch == "":
                raise ValidationError(
                    instance_id,
                    f"Missing or empty 'patch' field in data point '{dp_name}'."
                    " The patch is required for validation.",
                    "",
                    error_type="structural",
                )

            # Check for duplicate instance_ids
            if instance_id in self.data_points:
                raise ValidationError(
                    dp_name,
                    f"Duplicate instance_id '{instance_id}' found."
                    f" Already loaded from '{self.instance_id_to_name[instance_id]}'.",
                    "",
                    error_type="structural",
                )

            self.data_point_names.append(dp_name)
            self.data_points[instance_id] = data_point
            self.instance_id_to_name[instance_id] = dp_name

        self.tmp_dir = tmp_dir
        self.timeout = timeout
        self.run_id = None  # Will be set during validation

        console.print(f"Loaded {len(self.data_points)} data point(s)")
        console.print(f"Instance IDs: {', '.join(self.data_points.keys())}")

    def validate(self):
        """
        Run SWE-bench evaluation on all data points using the official harness.

        This method calls swebench.harness.run_evaluation to execute the evaluation
        in Docker containers for all instances in parallel, then analyzes the results.

        Returns:
            dict: Dictionary mapping data point file names to results:
                {
                    "file1.json": {"success": True},
                    "file2.json": {"success": False, "error": ValidationError(...)}
                }
        """
        # Generate unique run_id for this validation
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        self.run_id = f"validator_{len(self.data_points)}inst_{timestamp}"

        console.print(
            f"[bold blue]Starting evaluation for {len(self.data_points)}"
            " instance(s)...[/bold blue]"
        )
        console.print(f"Run ID: {self.run_id}")

        # Create combined prediction and dataset files
        prediction_path = self._create_predictions_file()
        dataset_path = self._create_dataset_file()

        instance_ids = list(self.data_points.keys())

        # Calculate max_workers: use number of instances, but cap at reasonable limit
        max_workers = min(
            len(instance_ids), 4
        )  # Cap at 4 workers to avoid resource exhaustion

        try:
            # Call SWE-bench evaluation harness with all instances
            run_evaluation(
                dataset_name=str(
                    dataset_path
                ),  # Path to temporary dataset file (list format)
                split="test",  # Default split (may not matter for local file)
                instance_ids=instance_ids,  # All instances to validate
                predictions_path=str(prediction_path),
                max_workers=max_workers,  # Parallel execution
                force_rebuild=False,  # Use default
                cache_level="env",  # Cache base and env images, rebuild instances
                clean=False,  # Use default
                open_file_limit=4096,  # Use default
                run_id=self.run_id,
                timeout=self.timeout,
                namespace=None,  # Use default namespace
                rewrite_reports=False,  # Use default
                modal=False,  # Use default
            )

            console.print(
                "[bold green]✓ Evaluation completed for all instances[/bold green]"
            )
            logger.info(
                f"Evaluation completed successfully for {len(instance_ids)} instances"
            )

            # Analyze reports
            return self._analyze_reports()

        except Exception as e:
            console.print(f"[bold red]✗ Evaluation failed: {str(e)}[/bold red]")
            logger.error(f"Evaluation failed: {e}", exc_info=True)

            # Return error for all instances
            results = {}
            for instance_id in instance_ids:
                dp_name = self.instance_id_to_name[instance_id]
                results[dp_name] = {
                    "success": False,
                    "error": ValidationError(
                        instance_id,
                        "Evaluation harness encountered an unexpected error"
                        f": {str(e)}. This may be a Docker, infrastructure, or"
                        " harness issue. Check the logs for details.",
                        self.run_id,
                        error_type="execution",
                    ),
                }
            return results

    def _create_predictions_file(self):
        """
        Create a SWE-bench predictions file with all data points.

        Returns:
            Path: Path to the predictions file
        """
        if not self.tmp_dir.exists():
            raise RuntimeError(f"Temporary directory '{self.tmp_dir}' does not exist")

        predictions = []
        for instance_id, data_point in self.data_points.items():
            patch = data_point.get("patch")
            predictions.append(
                {
                    "instance_id": instance_id,
                    "model_name_or_path": "validator",
                    "model_patch": patch,
                }
            )

        # Generate timestamp for unique file name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prediction_filename = f"predictions_{len(predictions)}inst_{timestamp}.json"
        prediction_path = self.tmp_dir / prediction_filename

        with prediction_path.open("w", encoding="utf-8") as f:
            json.dump(predictions, f, indent=2)

        logger.info(
            f"Predictions file created at: {prediction_path}"
            f" with {len(predictions)} entries"
        )
        return prediction_path

    def _create_dataset_file(self):
        """
        Create a temporary dataset file with all instances as a list.

        load_swebench_dataset expects a JSON file containing a list of instances.
        """
        # Create list of all instances
        dataset = list(self.data_points.values())

        # Save to temporary file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dataset_filename = f"dataset_{len(dataset)}inst_{timestamp}.json"
        dataset_path = self.tmp_dir / dataset_filename

        with dataset_path.open("w", encoding="utf-8") as f:
            json.dump(dataset, f, indent=2)

        logger.info(
            f"Dataset file created at: {dataset_path} with {len(dataset)} instances"
        )
        return dataset_path

    def _analyze_reports(self):
        """
        Analyze evaluation reports for all instances.

        The harness creates a separate report.json file for each instance at:
        logs/run_evaluation/{run_id}/validator/{instance_id}/report.json

        Each report.json contains a dictionary with the instance_id as the key.

        Returns:
            dict: Dictionary mapping data point file names to results:
                {
                    "file1.json": {"success": True},
                    "file2.json": {"success": False, "error": ValidationError(...)}
                }
        """
        results = {}

        # Load all individual report files and combine them
        combined_report = {}
        for instance_id in self.data_points.keys():
            report_path = (
                RUN_EVALUATION_LOG_DIR
                / self.run_id
                / "validator"
                / instance_id
                / LOG_REPORT
            )

            if report_path.exists():
                try:
                    with report_path.open("r", encoding="utf-8") as f:
                        instance_report = json.load(f)
                    # Each report.json contains {instance_id: {...}}, so merge it
                    combined_report.update(instance_report)
                except Exception as e:
                    logger.warning(f"Failed to load report for {instance_id}: {e}")

        # Analyze each instance
        for instance_id, data_point in self.data_points.items():
            dp_name = self.instance_id_to_name[instance_id]

            if instance_id not in combined_report:
                results[dp_name] = {
                    "success": False,
                    "error": ValidationError(
                        instance_id,
                        f"Evaluation report not found for instance '{instance_id}'."
                        " The evaluation may have failed before completion. "
                        " Check Docker logs and container status.",
                        self.run_id,
                        error_type="execution",
                    ),
                }
                continue

            instance_report = combined_report[instance_id]

            try:
                # Check for patch issues
                if instance_report.get("patch_is_None", False):
                    raise ValidationError(
                        instance_id,
                        "Patch is None or empty. The data point's"
                        " 'patch' field is missing or empty.",
                        self.run_id,
                        error_type="structural",
                    )

                if not instance_report.get("patch_exists", False):
                    raise ValidationError(
                        instance_id,
                        "Patch does not exist in the prediction file. "
                        " This is an internal error - please report this issue.",
                        self.run_id,
                        error_type="execution",
                    )

                if not instance_report.get("patch_successfully_applied", False):
                    raise ValidationError(
                        instance_id,
                        "Patch failed to apply to the codebase. Possible causes:"
                        " malformed patch format, incompatible with target files, "
                        "or files have changed. Check the evaluation "
                        " logs for detailed error messages.",
                        self.run_id,
                        error_type="execution",
                    )

                # Check resolution status
                resolved = instance_report.get("resolved", False)
                tests_status = instance_report.get("tests_status", {})

                if not resolved:
                    # Build detailed error message from tests_status
                    error_details = []

                    fail_to_pass = tests_status.get("FAIL_TO_PASS", {})
                    fail_to_pass_failures = fail_to_pass.get("failure", [])

                    pass_to_pass = tests_status.get("PASS_TO_PASS", {})
                    pass_to_pass_failures = pass_to_pass.get("failure", [])

                    # Report FAIL_TO_PASS failures
                    if fail_to_pass_failures:
                        error_details.append(
                            "FAIL_TO_PASS tests still failing"
                            f" ({len(fail_to_pass_failures)}): "
                            f"{', '.join(fail_to_pass_failures[:5])}"
                            + (
                                f" and {len(fail_to_pass_failures) - 5} more"
                                if len(fail_to_pass_failures) > 5
                                else ""
                            )
                        )

                    # Report PASS_TO_PASS failures
                    if pass_to_pass_failures:
                        error_details.append(
                            f"PASS_TO_PASS tests broken "
                            f"({len(pass_to_pass_failures)}): "
                            f"{', '.join(pass_to_pass_failures[:5])}"
                            + (
                                f" and {len(pass_to_pass_failures) - 5} more"
                                if len(pass_to_pass_failures) > 5
                                else ""
                            )
                        )

                    if not error_details:
                        error_details.append(
                            "Tests did not pass, but specific test"
                            " failures are not available."
                        )

                    error_message = "Test validation failed: " + "; ".join(
                        error_details
                    )

                    raise ValidationError(
                        instance_id,
                        error_message,
                        self.run_id,
                        tests_status=tests_status,
                        error_type="test_failure",
                    )

                # Validation passed
                results[dp_name] = {"success": True}

            except ValidationError as e:
                results[dp_name] = {"success": False, "error": e}

        return results


class ValidationError(Exception):
    """
    Exception raised when a data point fails validation.

    Attributes:
        instance_id: The instance ID that failed validation
        message: Detailed error message
        run_id: The evaluation run ID for locating logs
        tests_status: Optional detailed test status information
        error_type: Type of error ('structural', 'execution', 'test_failure')
    """

    def __init__(
        self,
        instance_id: str,
        message: str,
        run_id: str,
        tests_status: dict = None,
        error_type: str = "execution",
    ):
        self.instance_id = instance_id
        self.message = message
        self.run_id = run_id
        self.tests_status = tests_status
        self.error_type = error_type
        super().__init__(f"[{instance_id}] {message}")

    def __str__(self):
        log_path = RUN_EVALUATION_LOG_DIR / self.run_id / "validator" / self.instance_id
        return (
            f"{super().__str__()}\n"
            f"Check logs at: {log_path}\n"
            f"  - {log_path / 'run_instance.log'} (execution log)\n"
            f"  - {log_path / 'test_output.txt'} (test output)\n"
            f"  - {log_path / 'report.json'} (evaluation report)"
        )

    def get_github_action_message(self) -> str:
        """Get a formatted message for GitHub Actions annotations."""
        if self.error_type == "structural":
            return f"❌ Structural Error: {self.message}"
        elif self.error_type == "test_failure":
            return f"❌ Test Failure: {self.message}"
        else:
            return f"❌ Execution Error: {self.message}"
