import argparse
import re
from . import __version__ # Import version from package __init__

# Import default values from config_handler
from .config_handler import (
    DEFAULT_CHUNK_SIZE, DEFAULT_TEMPERATURE, DEFAULT_TIMEOUT,
    DEFAULT_DATA_FOLDER, DEFAULT_MAX_FAILURES, DEFAULT_MODEL,
    DEFAULT_PROVIDER, DEFAULT_MAX_LOG_LENGTH
)


def collapse_whitespace(text: str):
    """Replaces multiple whitespace chars with a single space."""
    return re.sub(r'\s+', ' ', text.replace('\n', ' ')).strip()


def positive_int(value):
    """Argparse type checker for positive integers."""
    try:
        ivalue = int(value)
        if ivalue <= 0:
            raise argparse.ArgumentTypeError(f"{value} is not a positive integer")
        return ivalue
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value} is not an integer")

def non_negative_int(value):
    """Argparse type checker for non-negative integers."""
    try:
        ivalue = int(value)
        if ivalue < 0:
             raise argparse.ArgumentTypeError(f"{value} must be a non-negative integer")
        return ivalue
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value} is not an integer")


def temperature_float(value):
     """Argparse type checker for temperature float (0.0 to 2.0)."""
     try:
          fvalue = float(value)
          # Allow slightly wider range based on common models
          if not (0.0 <= fvalue <= 2.0):
               raise argparse.ArgumentTypeError(f"{value} must be between 0.0 and 2.0")
          return fvalue
     except ValueError:
          raise argparse.ArgumentTypeError(f"{value} is not a valid float")


def parse_arguments() -> argparse.Namespace:
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description=collapse_whitespace("""
        GAR: Generation-Augmented Retrieval Tool. Extracts structured data
        from text files (txt, md, pdf, docx, pptx) using LLMs. Requires
        'markitdown-python' for PDF/DOCX/PPTX. See README for details.
        """),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter # Show defaults
    )

    # --- Input/Output Group ---
    io_group = parser.add_argument_group("Input and Output")
    io_group.add_argument(
        '--config', type=str, default='config.yaml',
        help="Path to the YAML configuration file."
    )
    io_group.add_argument(
        '--data_folder', type=str, default=DEFAULT_DATA_FOLDER,
        help="Path to the directory containing source files."
    )
    io_group.add_argument(
        '--results_db', type=str, default=None,
        help="Name of the SQLite DB file. If None, uses '<config_name>.db'."
    )

    # --- Processing Control Group ---
    proc_group = parser.add_argument_group("Processing Control")
    proc_group.add_argument(
        '--chunk_size', type=positive_int, default=DEFAULT_CHUNK_SIZE,
        help="Target chunk size in characters."
    )
    proc_group.add_argument(
        '--max_failures', type=non_negative_int, default=DEFAULT_MAX_FAILURES,
        help="Max consecutive LLM failures per chunk before skipping."
    )
    proc_group.add_argument(
        '--run_tag', type=str, default=None,
        help="Label for this run in DB (allows reruns). Defaults to config filename."
    )

    # --- AI Parameters Group ---
    ai_group = parser.add_argument_group("AI Parameters")
    ai_group.add_argument(
        '--model', type=str, default=DEFAULT_MODEL,
        help="Name of the LLM to use (provider-specific)."
    )
    ai_group.add_argument(
        '--provider', type=str, default=DEFAULT_PROVIDER,
        help="Base URL of the LLM provider API (OpenAI compatible)."
    )
    ai_group.add_argument(
        '--temperature', type=temperature_float, default=DEFAULT_TEMPERATURE,
        help="LLM temperature (0.0-2.0). Lower is more deterministic."
    )
    ai_group.add_argument(
        '--timeout', type=positive_int, default=DEFAULT_TIMEOUT,
        help="Timeout in seconds for LLM API requests."
    )
    ai_group.add_argument(
        '--skip_key_check', action='store_true',
        help="Skip API key check (e.g., for local models)."
    )

    # --- Script Behavior Group ---
    script_group = parser.add_argument_group("Script Behavior")
    script_group.add_argument(
        '--max_log_length', type=non_negative_int, default=DEFAULT_MAX_LOG_LENGTH,
        help="Max length for logged excerpts (LLM prompts/responses). 0=unlimited."
    )
    script_group.add_argument(
        '--log_level', type=str, default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help="Set the logging level."
    )
    script_group.add_argument(
        "--version", action="version",
        version=f"%(prog)s {__version__}", # Get version from __init__
        help="Show program's version number and exit."
    )

    args = parser.parse_args()

    # Post-parsing validation/defaults
    if args.results_db is None:
        config_name = os.path.splitext(os.path.basename(args.config))[0]
        args.results_db = f"{config_name}.db"

    if args.run_tag is None:
        args.run_tag = os.path.basename(args.config) # Default tag to config filename

    return args

# --- Utility function to check for duplicate arguments (Optional) ---
import sys
import os

def check_duplicate_args(argv):
    """Checks for duplicate named arguments (e.g., --foo ... --foo)."""
    seen_args = set()
    duplicates = []

    for arg in argv[1:]:
        if arg.startswith('--'):
            arg_name = arg.split('=', 1)[0] # Handle --arg=value form
            if arg_name in seen_args:
                 if arg_name not in duplicates: # Report each duplicate only once
                     duplicates.append(arg_name)
            seen_args.add(arg_name)
        # Stop checking after '--' if used
        elif arg == '--':
             break

    if duplicates:
        print(f"Error: Duplicate argument(s) found: {', '.join(duplicates)}", file=sys.stderr)
        sys.exit(2) # Use standard exit code for CLI errors
