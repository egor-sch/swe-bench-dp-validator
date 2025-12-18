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
    Validates the specific SWE-bench data points using the official SWE-bench library.
    tmp_dir must already exist.
    """

    def __init__(
        self,
        data_point_name: str, 
        tmp_dir: Path,
        timeout: int,
    ):
        # Ensure .json extension if not present
        if not data_point_name.endswith('.json'):
            data_point_name = f"{data_point_name}.json"
        
        self.data_point_path = Path(data_points_dir) / data_point_name

        if not self.data_point_path.exists():
            raise ValidationError(
                data_point_name,
                f"Data point file not found: '{self.data_point_path}'. Ensure the file exists in the 'data_points' directory.",
                "",
                error_type="structural"
            )

        # Load data point to get instance_id - handle JSON parsing errors
        try:
            with self.data_point_path.open("r", encoding="utf-8") as f:
                data_point = json.load(f)
        except json.JSONDecodeError as e:
            raise ValidationError(
                data_point_name,
                f"Invalid JSON format in data point file: {str(e)}. Please check the file syntax.",
                "",
                error_type="structural"
            ) from e
        except Exception as e:
            raise ValidationError(
                data_point_name,
                f"Failed to read data point file: {str(e)}",
                "",
                error_type="structural"
            ) from e
        
        # Validate required fields
        self.instance_id = data_point.get("instance_id")
        if self.instance_id is None:
            raise ValidationError(
                data_point_name,
                f"Missing required field 'instance_id' in data point file. Please ensure the data point follows the SWE-bench format.",
                "",
                error_type="structural"
            )
        
        patch = data_point.get("patch")
        if patch is None or patch == "":
            raise ValidationError(
                self.instance_id,
                f"Missing or empty 'patch' field in data point. The patch is required for validation.",
                "",
                error_type="structural"
            )

        self.prediction_path = self._create_prediction(tmp_dir)
        # Create a temporary dataset file with the instance wrapped in a list
        # (load_swebench_dataset expects a list of instances, not a single object)
        self.dataset_path = self._create_dataset_file(tmp_dir)
        self.timeout = timeout
        self.run_id = None  # Will be set during validation
        
        console.print(f"Data point path: {self.data_point_path}\nInstance ID: {self.instance_id}\nPrediction file: {self.dataset_path}\nData set file: {self.prediction_path}\nTimeout: {timeout}")
    
    def validate(self):
        """
        Run SWE-bench evaluation on the data point using the official harness.
        
        This method calls swebench.harness.run_evaluation to execute the evaluation
        in Docker containers, then analyzes the results.
        
        Returns:
            bool: True if validation passed, False otherwise
            
        Raises:
            ValidationError: If the data point fails validation with detailed error message
        """
        # Generate unique run_id for this validation
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_id = f"validator_{self.instance_id}_{timestamp}"
        
        console.print(f"[bold blue]Starting evaluation for instance: {self.instance_id}[/bold blue]")
        console.print(f"Run ID: {self.run_id}")
        
        try:
            # Call SWE-bench evaluation harness
            # For a single instance, we use max_workers=1 (no parallelization needed)
            run_evaluation(
                dataset_name=str(self.dataset_path),  # Path to temporary dataset file (list format)
                split="test",  # Default split (may not matter for local file)
                instance_ids=[self.instance_id],  # Single instance to validate
                predictions_path=str(self.prediction_path),
                max_workers=1,  # Single instance, no need for parallelization
                force_rebuild=False, # Use default
                cache_level="env",  # Cache base and env images, rebuild instances
                clean=False, # Use default
                open_file_limit=4096, # Use default
                run_id=self.run_id,
                timeout=self.timeout,
                namespace=None,  # Use default namespace
                rewrite_reports=False, # Use default
                modal=False, # Use default
            )
            
            console.print(f"[bold green]✓ Evaluation completed for {self.instance_id}[/bold green]")
            logger.info(f"Evaluation completed successfully for {self.instance_id}")
            
            # Analyze the report to determine if validation passed
            return self._analyze_report()
            
        except ValidationError:
            # Re-raise ValidationErrors as-is
            raise
        except Exception as e:
            console.print(f"[bold red]✗ Evaluation failed for {self.instance_id}: {str(e)}[/bold red]")
            logger.error(f"Evaluation failed for {self.instance_id}: {e}", exc_info=True)
            raise ValidationError(
                self.instance_id,
                f"Evaluation harness encountered an unexpected error: {str(e)}. This may be a Docker, infrastructure, or harness issue. Check the logs for details.",
                self.run_id,
                error_type="execution"
            ) from e

    def _create_prediction(self, tmp_dir: Path):
        """
        Create a SWE-bench prediction file in the temporary directory.

        The prediction file:
        - Lives under `tmp_dir`
        - Has the same file name as the data point JSON (no path changes)
        - Contains a single prediction entry for this instance in JSON list form
          compatible with `swebench.harness.run_evaluation`.
        """
        if not tmp_dir.exists():
            raise RuntimeError(f"Temporary directory '{tmp_dir}' does not exist")
        
        # Load data point JSON
        with self.data_point_path.open("r", encoding="utf-8") as f:
            data_point = json.load(f)

        instance_id = data_point.get("instance_id")
        patch = data_point.get("patch")

        if instance_id is None or patch is None:
            raise RuntimeError(
                f"Data point '{self.data_point_path}' is missing required fields "
                "'instance_id' or 'patch'"
            )

        prediction = {
            "instance_id": instance_id,
            "model_name_or_path": "validator",
            "model_patch": patch,
        }

        # Generate timestamp for unique file name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Use file name with timestamp: original_name_timestamp.json
        base_name = self.data_point_path.stem  # filename without extension
        prediction_filename = f"{base_name}_{timestamp}.json"
        prediction_path = tmp_dir / prediction_filename

        with prediction_path.open("w", encoding="utf-8") as f:
            json.dump([prediction], f, indent=2)

        logger.info(f"Prediction file created at: {prediction_path}")
        return prediction_path

    def _create_dataset_file(self, tmp_dir: Path):
        """
        Create a temporary dataset file with the single instance wrapped in a list.
        
        load_swebench_dataset expects a JSON file containing a list of instances,
        but our data point file contains a single instance object.
        """
        # Load the single instance
        with self.data_point_path.open("r", encoding="utf-8") as f:
            instance = json.load(f)
        
        # Wrap it in a list
        dataset = [instance]
        
        # Save to temporary file
        dataset_filename = f"dataset_{self.instance_id}.json"
        dataset_path = tmp_dir / dataset_filename
        
        with dataset_path.open("w", encoding="utf-8") as f:
            json.dump(dataset, f, indent=2)
        
        logger.info(f"Dataset file created at: {dataset_path}")
        return dataset_path

    def _analyze_report(self):
        """
        Analyze the evaluation report to determine if the data point is valid.
        
        Returns:
            bool: True if validation passed, False otherwise
            
        Raises:
            ValidationError: If validation failed with detailed error information
        """
        # Construct report path: logs/run_evaluation/{run_id}/validator/{instance_id}/report.json
        report_path = (
            RUN_EVALUATION_LOG_DIR 
            / self.run_id 
            / "validator" 
            / self.instance_id 
            / LOG_REPORT
        )
        
        if not report_path.exists():
                    raise ValidationError(
                        self.instance_id,
                        f"Evaluation report not found at {report_path}. The evaluation may have failed before completion. Check Docker logs and container status.",
                        self.run_id,
                        error_type="execution"
                    )
        
        # Load the report
        with report_path.open("r", encoding="utf-8") as f:
            report = json.load(f)
        
        if self.instance_id not in report:
            raise ValidationError(
                self.instance_id,
                f"Instance '{self.instance_id}' not found in evaluation report. This may indicate a mismatch between the data point and evaluation run. Report contains: {list(report.keys())}",
                self.run_id,
                error_type="execution"
            )
        
        instance_report = report[self.instance_id]
        
        # Check for patch issues
        if instance_report.get("patch_is_None", False):
            raise ValidationError(
                self.instance_id,
                "Patch is None or empty. The data point's 'patch' field is missing or empty.",
                self.run_id,
                error_type="structural"
            )
        
        if not instance_report.get("patch_exists", False):
            raise ValidationError(
                self.instance_id,
                "Patch does not exist in the prediction file. This is an internal error - please report this issue.",
                self.run_id,
                error_type="execution"
            )
        
        if not instance_report.get("patch_successfully_applied", False):
            raise ValidationError(
                self.instance_id,
                "Patch failed to apply to the codebase. Possible causes: malformed patch format, incompatible with target files, or files have changed. Check the evaluation logs for detailed error messages.",
                self.run_id,
                error_type="execution"
            )
        
        # Check resolution status
        resolved = instance_report.get("resolved", False)
        tests_status = instance_report.get("tests_status", {})
        
        if not resolved:
            # Build detailed error message from tests_status
            error_details = []
            
            fail_to_pass = tests_status.get("FAIL_TO_PASS", {})
            fail_to_pass_failures = fail_to_pass.get("failure", [])
            fail_to_pass_passes = fail_to_pass.get("pass", [])
            
            pass_to_pass = tests_status.get("PASS_TO_PASS", {})
            pass_to_pass_failures = pass_to_pass.get("failure", [])
            pass_to_pass_passes = pass_to_pass.get("pass", [])
            
            # Report FAIL_TO_PASS status
            if fail_to_pass_failures:
                error_details.append(
                    f"FAIL_TO_PASS tests still failing ({len(fail_to_pass_failures)}): "
                    f"{', '.join(fail_to_pass_failures[:5])}"
                    + (f" and {len(fail_to_pass_failures) - 5} more" if len(fail_to_pass_failures) > 5 else "")
                )
            elif fail_to_pass_passes:
                error_details.append(
                    f"✓ FAIL_TO_PASS tests now passing ({len(fail_to_pass_passes)}): "
                    f"{', '.join(fail_to_pass_passes[:5])}"
                    + (f" and {len(fail_to_pass_passes) - 5} more" if len(fail_to_pass_passes) > 5 else "")
                )
            
            # Report PASS_TO_PASS status
            if pass_to_pass_failures:
                error_details.append(
                    f"PASS_TO_PASS tests broken ({len(pass_to_pass_failures)}): "
                    f"{', '.join(pass_to_pass_failures[:5])}"
                    + (f" and {len(pass_to_pass_failures) - 5} more" if len(pass_to_pass_failures) > 5 else "")
                )
            elif pass_to_pass_passes:
                error_details.append(
                    f"✓ PASS_TO_PASS tests still passing ({len(pass_to_pass_passes)}): "
                    f"{', '.join(pass_to_pass_passes[:5])}"
                    + (f" and {len(pass_to_pass_passes) - 5} more" if len(pass_to_pass_passes) > 5 else "")
                )
            
            if not error_details:
                error_details.append("Tests did not pass, but specific test failures are not available.")
            
            error_message = "Test validation failed: " + "; ".join(error_details)
            
            raise ValidationError(
                self.instance_id,
                error_message,
                self.run_id,
                tests_status=tests_status,
                error_type="test_failure"
            )
        
        # Validation passed
        console.print(f"[bold green]✓ Validation PASSED for {self.instance_id}[/bold green]")
        console.print(f"  - Patch applied successfully")
        console.print(f"  - All FAIL_TO_PASS tests now pass")
        console.print(f"  - All PASS_TO_PASS tests remain passing")
        
        return True


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
    
    def __init__(self, instance_id: str, message: str, run_id: str, tests_status: dict = None, error_type: str = "execution"):
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
