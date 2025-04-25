# gar_tool/helpers.py
import re, sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .logging_wrapper import logger

# --- Conditional import for type checking tools like Pylance/MyPy ---
if TYPE_CHECKING:
    from .database_handler import Database # Import Database only during static analysis

def get_current_timestamp_iso():
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()

def collapse_whitespace(text: str): # Used for convenience in the code, to write longer messages as multiline
    return re.sub(r'\s+', ' ', text.replace('\n', ' ')).strip()

signal_received = False
def signal_handler(sig, frame, db_instance: 'Database', start_iso: str):
    """Handles Ctrl+C interrupt and prints a graceful message with stats."""
    global signal_received # Modify the global defined in THIS module
    if signal_received:
        return
    signal_received = True # Set the flag defined in this module
    logger.info('\nCtrl+C detected. Attempting graceful exit...')
    end_iso = get_current_timestamp_iso()

    try:
        # Runtime access to db_instance methods is fine
        if db_instance and db_instance.connection:
            logger.info("--- Partial Run Summary ---")
            logger.info(db_instance.get_run_summary(start_iso, end_iso))
            logger.info("-------------------------")
        else:
            logger.error("Database not initialized or connection closed during shutdown.")
    except Exception as e:
        logger.exception(f"Error generating summary in signal handler: {e}")

    if db_instance:
        db_instance.close()

    print("Exiting due to interrupt.")
    sys.exit(0)