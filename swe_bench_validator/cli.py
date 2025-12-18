"""
Command-line interface for the SWE-bench data point validator.
"""

import json
import logging
import os
import shutil
import click
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
import sys

from .validator import SWEBenchValidator, ValidationError
from swebench.harness.constants import RUN_EVALUATION_LOG_DIR

console = Console()
tmp_dir_name = "tmp"


@click.command()
@click.option(
    "--data_point_names",
    multiple=True,
    required=True,
    help="Data point file name(s) to validate in 'data_points' directory (can be used multiple times)",
)
@click.option(
    "--timeout",
    type=int,
    default=1800,
    help="Timeout (in seconds) for running tests, default value is 1800",
)
@click.option(
    "--verbose",
    "-v",
    default=False,
    is_flag=True,
    help="Enable verbose output",
)


def main(
    data_point_names,
    timeout,
    verbose
):
    """
    Validate SWE-bench data point(s) using the official SWE-bench library.
    
    Examples:
    
    # Validate a single data point
    validate_swe_bench.sh --data_point_names "astropy__astropy-11693.json"
    
    # Validate multiple data points
    validate_swe_bench.sh --data_point_names "astropy__astropy-11693.json" --data_point_names "astropy__astropy-11692.json"
    """
    try:
        data_points = list(data_point_names)
        if not data_points:
            console.print("[bold red]Error: Must provide at least one data point name[/bold red]")
            sys.exit(1)
        
        # Configure logging level based on verbose flag
        if verbose:
            # Set root logger to INFO level to see harness progress
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%H:%M:%S'
            )
            # Also enable INFO level for swebench modules
            logging.getLogger('swebench').setLevel(logging.INFO)
        else:
            # Default: only show WARNING and above
            logging.basicConfig(
                level=logging.WARNING,
                format='%(asctime)s - %(levelname)s - %(message)s',
                datefmt='%H:%M:%S'
            )
        
        # Create temporary directory for temporary files
        tmp_dir = Path(tmp_dir_name)
        tmp_dir.mkdir(exist_ok=True)
        console.print(f"{tmp_dir} directory is created")

        # Validate all data points in parallel using the harness
        console.print(f"[bold blue]Validating {len(data_points)} data point(s)...[/bold blue]")
        
        validator = SWEBenchValidator(
            data_point_names=data_points,
            tmp_dir=tmp_dir,
            timeout=timeout,
        )
        
        results = validator.validate()
        
        # Process results
        successful_validations = []
        failed_validations = []
        
        for dp_name, result in results.items():
            if result["success"]:
                successful_validations.append(dp_name)
                console.print(f"[bold green]✓ {dp_name}: Validation successful![/bold green]")
            else:
                error = result["error"]
                failed_validations.append((dp_name, error))
                error_prefix = {
                    "structural": "[bold yellow]⚠[/bold yellow]",
                    "test_failure": "[bold red]✗[/bold red]",
                    "execution": "[bold red]✗[/bold red]"
                }.get(error.error_type if isinstance(error, ValidationError) else "execution", "[bold red]✗[/bold red]")
                error_msg = error.message if isinstance(error, ValidationError) else str(error)
                console.print(f"{error_prefix} {dp_name}: {error_msg}")
                
                # Output GitHub Actions annotation
                if os.getenv("GITHUB_ACTIONS"):
                    if isinstance(error, ValidationError):
                        github_message = error.get_github_action_message()
                    else:
                        github_message = f"Unexpected error: {str(error)}"
                    print(f"::error file=data_points/{dp_name}::{github_message}")
        
        # Summary
        console.print(f"\n[bold]Validation Summary:[/bold]")
        console.print(f"  [green]✓ Successful: {len(successful_validations)}[/green]")
        console.print(f"  [red]✗ Failed: {len(failed_validations)}[/red]")
        
        if failed_validations:
            console.print(f"\n[bold red]Failed validations:[/bold red]")
            for dp_name, error in failed_validations:
                console.print(f"  - {dp_name}")
            sys.exit(1)  # Failure exit code
        
        console.print(f"\n[bold green]✓ All validations successful![/bold green]")
        sys.exit(0)  # Success exit code
                
    except ValidationError as e:
        # Detailed validation error - show full message with log paths
        error_prefix = {
            "structural": "[bold yellow]⚠ Structural Error[/bold yellow]",
            "test_failure": "[bold red]✗ Test Failure[/bold red]",
            "execution": "[bold red]✗ Execution Error[/bold red]"
        }.get(e.error_type, "[bold red]✗ Validation Error[/bold red]")
        
        console.print(f"{error_prefix}: {e.instance_id}")
        console.print(f"[red]{e.message}[/red]")
        
        # Show log paths if run_id is available (not available for structural errors)
        if e.run_id:
            log_path = RUN_EVALUATION_LOG_DIR / e.run_id / "validator" / e.instance_id
            console.print(f"[dim]Logs: {log_path}[/dim]")
        
        if verbose and e.tests_status:
            console.print("\n[bold]Detailed test status:[/bold]")
            console.print_json(json.dumps(e.tests_status, indent=2))
        if verbose:
            console.print_exception()
        
        # Output GitHub Actions annotation
        if os.getenv("GITHUB_ACTIONS"):
            github_message = e.get_github_action_message()
            print(f"::error::{github_message}")
        
        sys.exit(1)  # Failure exit code for GitHub Actions
        
    except Exception as e:
        # Other unexpected errors (e.g., infrastructure, setup issues)
        console.print(f"[bold red]✗ Unexpected Error[/bold red]: {str(e)}")
        if verbose:
            console.print_exception()
        
        # Output GitHub Actions annotation
        if os.getenv("GITHUB_ACTIONS"):
            print(f"::error::Unexpected error: {str(e)}")
        
        sys.exit(1)  # Failure exit code
    finally:
        try:
            shutil.rmtree(tmp_dir)
            console.print(f"{tmp_dir} directory is deleted")
        except Exception as e:
            console.print(f"{tmp_dir} directory deletion error: {str(e)}")



if __name__ == "__main__":
    main()
