"""
Command-line interface for the SWE-bench data point validator.
"""

import click
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
import sys

from .validator import SWEBenchValidator

console = Console()


@click.command()
@click.option(
    "--data_point_name",
    required=True,
    help="Data point file name to be validated in 'data_points' (without .json extension)",
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
        # Initialize validator
        validator = SWEBenchValidator(
            data_point_name=data_point_name,
            timeout=timeout,
        )
                
    except Exception as e:
        console.print(f"[bold red]✗ Error: {str(e)}[/bold red]")
        if verbose:
            console.print_exception()
        sys.exit(1)


if __name__ == "__main__":
    main() 