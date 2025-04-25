# gar_tool/cli.py

from .helpers import collapse_whitespace
from .logging_wrapper import logger
import argparse
from argparse import Namespace

from . import __version__ as VERSION

def check_duplicate_args(argv): # Checks for duplicate named arguments and exits with an error if found.
    """
    Checks for duplicate named arguments and exits with an error.

    Rationale:
    Argparse silently overwrites duplicate single-value arguments, potentially
    leading to user confusion and hidden errors. This function prevents this by
    explicitly reporting duplicate named arguments, ensuring predictable and
    transparent command-line argument handling.
    """
    seen_args = set()

    for arg in argv[1:]:  # Start from index 1 to skip the script name
        if arg.startswith('--'):  # Named argument
            if arg in seen_args:
                logger.critical_exit(f"Error: Duplicate argument '{arg}' found.")
            seen_args.add(arg)

def positive_int(value):
    """Checks if a value is a positive integer."""
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value} is not an integer")
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"{value} is not a positive integer")
    return ivalue

def parse_arguments() -> Namespace:
    parser = argparse.ArgumentParser(description=collapse_whitespace("""
    This command-line tool extracts specific information from large collections of 
    text files and organizes it into a spreadsheet within a database, using 
    Large Language Models (LLMs).  It's designed to assist with data that was 
    once structured but is now in plain text, or when deriving new insights 
    from unstructured information. Ideal for data analysts and researchers who 
    need to convert unstructured or semi-structured text into analyzable data.
    """))

    config_group_control = parser.add_argument_group("Script control")    
    config_group_control.add_argument('--config', type=str, default='config.yaml', help=collapse_whitespace("""
        Path to the YAML configuration file containing extraction
        parameters (default: %(default)s).
    """))   
    config_group_control.add_argument('--max_log_length', type=positive_int, default=200, help=collapse_whitespace("""
        Maximum length (in characters) of loggin messages (mostly to limit excerpts for prompts and responses)
        in debug logs (default: %(default)s).
    """))
    config_group_control.add_argument('--log_level', type=str, default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], help=collapse_whitespace("""
        Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        (default: %(default)s).
    """))
    config_group_control.add_argument("--version", action="version", version=f"%(prog)s {VERSION}", help=collapse_whitespace("""
        Show program's version number and exit.
    """))

    # Configuration from YAML file
    config_group_io = parser.add_argument_group("Input and output (command line overwrites values from configuration YAML file)")

    config_group_io.add_argument('--data_folder', type=str, help=collapse_whitespace("""
        Path to the directory containing the text files to process.
    """))
    config_group_io.add_argument('--chunk_size', type=int, help=collapse_whitespace("""
        Chunk size (in characters). Files exceeding this size will be
        split into chunks. The combined chunk and prompt must fit within
        the model's context window (measured in tokens, not characters).
        Token length varies by language. See the README for details.
    """))
    config_group_io.add_argument('--results_db', type=str, help=collapse_whitespace("""
        Name of the SQLite database file to store results. Be careful, the extension '.db' is not added automatically. 
        If this argument is not specified, the project name from the YAML configuration file
        is used.
    """))

    config_group_ai = parser.add_argument_group("AI parameters (command line overwrites values from configuration YAML file)")
    config_group_ai.add_argument('--model', type=str, help=collapse_whitespace("""
        Name of the LLM to use for analysis (e.g., 'deepseek/deepseek-chat:floor').
    """))
    config_group_ai.add_argument('--provider', type=str, help=collapse_whitespace("""
        Base URL of the LLM provider API (e.g., 'https://api.openrouter.ai/v1').
        Default: OpenRouter.
    """))
    config_group_ai.add_argument('--skip_key_check', action='store_true', help=collapse_whitespace("""
        Skip API key check (use for models that don't require keys, or
        set OPENROUTER_API_KEY in .env to any non-empty value).
    """))
    config_group_ai.add_argument('--temperature', type=float, help=collapse_whitespace("""
        Temperature for model generation (0.0 to 1.0). Higher values
        increase creativity.  A value of 0 is recommended for predictable document processing.
    """))

    config_group_run = parser.add_argument_group("Run parameters (command line overwrites values from configuration YAML file)")
    config_group_run.add_argument('--run_tag', type=str, help=collapse_whitespace("""
        Tags records in the DATA table's 'run_tag' column with a run
        label for comparison testing (allowing duplication of
        file and chunk combinations).  Use this to differentiate
        runs based on model name, field order, temperature, or other variations.
        Default: file name of the YAML configuration.
    """))
    config_group_run.add_argument('--timeout', type=int, help=collapse_whitespace("""
        Timeout (in seconds) for requests to the LLM API.
    """))
    config_group_run.add_argument('--max_failures', type=int, help=collapse_whitespace("""
        Maximum number of consecutive failures allowed for a chunk before it
        is skipped.
    """))

    return parser.parse_args()