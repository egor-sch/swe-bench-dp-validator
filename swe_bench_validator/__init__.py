"""
SWE-bench Data Point Validator

A command-line tool for validating the specific SWE-bench data points
using the official SWE-bench library from the local data_points/ folder.
"""

__version__ = "0.1.0"

from .validator import SWEBenchValidator
from .cli import main

__all__ = ["SWEBenchValidator", "main"]
