"""
Command-line interface for the SWE-bench data point validator.
"""

import json
import logging
import shutil
import click
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
import sys

from .validator import SWEBenchValidator, ValidationError

console = Console()
tmp_dir_name = "tmp"


@click.command()
@click.option(
    "--data_point_name",
    required=True,
    help="Data point file name to be validated in 'data_points' directory",
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
    data_point_name,
    timeout,
    verbose
):
    """
    Validate the specific SWE-bench data point using the official SWE-bench library.
    
    Examples:
    
    # Validate the data point
    validate_swe_bench.sh --data_point_name "astropy__astropy-11693.json"
    """

    try:
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

        # Initialize validator
        validator = SWEBenchValidator(
            data_point_name=data_point_name,
            tmp_dir=tmp_dir,
            timeout=timeout,
        )

        # Run the validation
        validator.validate()
        
        console.print(f"[bold green]✓ Validation successful![/bold green]")
        return 0  # Success exit code
                
    except ValidationError as e:
        # Detailed validation error - show full message with log paths
        console.print(f"[bold red]✗ Validation FAILED[/bold red]")
        console.print(f"[red]{str(e)}[/red]")
        if verbose and e.tests_status:
            console.print("\n[bold]Detailed test status:[/bold]")
            console.print_json(json.dumps(e.tests_status, indent=2))
        if verbose:
            console.print_exception()
        return 1  # Failure exit code for GitHub Actions
        
    except Exception as e:
        # Other errors (e.g., infrastructure, setup issues)
        console.print(f"[bold red]✗ Error: {str(e)}[/bold red]")
        if verbose:
            console.print_exception()
        return 1  # Failure exit code
    finally:
        try:
            shutil.rmtree(tmp_dir)
            console.print(f"{tmp_dir} directory is deleted")
        except Exception as e:
            console.print(f"{tmp_dir} directory deletion error: {str(e)}")



if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code) 
