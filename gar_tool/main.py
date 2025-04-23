import os
import sys
import signal
import random
import time
from datetime import datetime, timezone
from dotenv import load_dotenv

# Use relative imports for sibling modules within the package
from . import __version__
from .logging_wrapper import logger
from .cli import parse_arguments, check_duplicate_args, collapse_whitespace
from .config_handler import ConfigLoader, ExtractorConfig
from .database_handler import Database
from .analyzer import DocumentAnalyzer
from .file_processor import get_text_content, calculate_chunks


# --- Constants ---
# Max consecutive errors like HTTP errors before aborting
MAX_PASSABLE_EXECUTION_ERRORS = 5
# Max warnings (e.g., JSON parsing issues) before aborting
MAX_PASSABLE_WARNINGS = 20


# --- Signal Handling ---
signal_received = False

def signal_handler(sig, frame, db_instance=None, start_iso=None):
    """Gracefully handles Ctrl+C interrupts."""
    global signal_received
    if signal_received: # Avoid duplicate messages if signal comes rapidly
        return
    signal_received = True
    print("\nCtrl+C detected. Shutting down gracefully...")
    logger.info("Interrupt signal received. Finishing current step if possible...")

    # Attempt to log summary if db connection is available
    if db_instance and db_instance.connection and start_iso:
        try:
            end_iso = get_current_timestamp_iso()
            logger.info("--- Partial Run Summary ---")
            log_run_summary(db_instance, start_iso, end_iso)
            logger.info("-------------------------")
        except Exception as e:
            logger.error(f"Error generating summary during shutdown: {e}")

    # Attempt to close DB connection
    if db_instance:
        db_instance.close()

    print("Exiting.")
    sys.exit(0)


# --- Utility Functions ---
def get_current_timestamp_iso() -> str:
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def log_run_summary(db: Database, start_iso: str, end_iso: str):
     """Logs the summary of the completed or interrupted run."""
     try:
          llm_calls, successes = db.get_run_summary_stats(start_iso, end_iso)
          skipped = db.get_all_skipped_chunks_for_run(start_iso, end_iso)

          logger.info(f"Run Period: {start_iso} -> {end_iso}")
          duration = datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)
          logger.info(f"Run Duration: {duration}")
          logger.info(f"LLM Calls Made: {llm_calls}")
          logger.info(f"Successful Extractions Stored: {successes}")

          if skipped:
               logger.info(f"Chunks Skipped (due to max failures): {len(skipped)}")
               # Log details only if needed/in debug mode
               if logger.get_log_level_name() == "DEBUG":
                    for file, chunk, failures in skipped:
                         logger.debug(f"- Skipped: {file} chunk {chunk} ({failures} failures)")
          else:
                logger.info("Chunks Skipped (due to max failures): 0")

     except Exception as e:
          logger.error(f"Failed to retrieve or log run summary: {e}", exc_info=True)


# --- Main Application Logic ---
def run_analysis(config: ExtractorConfig, start_iso: str):
    """Orchestrates the document analysis process."""
    global signal_received

    try:
        with Database(config) as db:
            # Register signal handler *after* DB is connected
            signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, db, start_iso))

            analyzer = DocumentAnalyzer(config)

            # 1. Identify files potentially needing work
            all_files_in_folder_abs = [
                os.path.abspath(os.path.join(config.inconfig_values.data_folder, f))
                for f in os.listdir(config.inconfig_values.data_folder)
                if os.path.isfile(os.path.join(config.inconfig_values.data_folder, f))
            ]

            if not all_files_in_folder_abs:
                logger.warning(f"No files found in data folder: {config.inconfig_values.data_folder}")
                return # Exit cleanly

            files_in_db = set(db.get_all_files_in_fchunks())
            files_potentially_needing_work_db = set(db.get_files_with_potential_unprocessed_chunks(start_iso))

            # Files to check = (those needing work according to DB AND currently in folder)
            #                UNION (those in folder but not yet in DB)
            files_to_consider_db = files_potentially_needing_work_db & set(all_files_in_folder_abs)
            files_new_in_folder = set(all_files_in_folder_abs) - files_in_db

            files_to_iterate = list(files_to_consider_db | files_new_in_folder)

            if not files_to_iterate:
                logger.info("All files and chunks appear processed or skipped from previous runs.")
                return # Exit cleanly

            logger.info(f"Found {len(files_to_iterate)} file(s) to check for processing.")
            random.shuffle(files_to_iterate) # Process files in random order

            # 2. Iterate through files
            for file_path in files_to_iterate:
                if signal_received: break
                logger.info(f"--- Checking file: {os.path.basename(file_path)} ---")

                # 3. Read/Convert file content (only once per file)
                text_content = get_text_content(file_path)
                if text_content is None or text_content == "":
                    logger.warning(f"Skipping file {os.path.basename(file_path)} due to read/conversion error or empty content.")
                    # TODO: Maybe log this skip permanently in DB?
                    continue

                # 4. Calculate and store chunks if file is new to DB
                if file_path not in files_in_db:
                     logger.debug(f"Calculating chunks for new file: {os.path.basename(file_path)}")
                     try:
                          chunk_bounds = calculate_chunks(
                               text_content, config.inconfig_values.chunk_size
                          )
                          if not chunk_bounds:
                               logger.warning(f"No chunks calculated for {os.path.basename(file_path)}. Skipping.")
                               continue
                          db.insert_chunks(file_path, chunk_bounds)
                          files_in_db.add(file_path) # Add to set to avoid re-check
                     except Exception as e:
                          logger.error(f"Failed to calculate/store chunks for {os.path.basename(file_path)}: {e}", exc_info=True)
                          continue

                # 5. Get specific chunks needing processing for THIS file in THIS run
                unprocessed_chunks = db.get_unprocessed_chunks(file_path, start_iso)
                if not unprocessed_chunks:
                     logger.info(f"No chunks require processing for {os.path.basename(file_path)} in this run.")
                     continue

                logger.info(f"Found {len(unprocessed_chunks)} chunk(s) to process for {os.path.basename(file_path)}")

                # 6. Process each required chunk
                for chunk_info in unprocessed_chunks:
                     if signal_received: break
                     _filename, chunk_number = chunk_info # _filename should match file_path
                     logger.info(f"Processing chunk {chunk_number}...")

                     chunk_bounds = db.get_chunk_bounds(file_path, chunk_number)
                     if not chunk_bounds:
                          logger.error(f"Cannot get bounds for chunk {chunk_number}. Skipping.")
                          continue

                     try:
                          content_for_chunk = text_content[chunk_bounds[0]:chunk_bounds[1]]
                     except IndexError:
                           logger.error(f"Content slicing error for chunk {chunk_number} (Bounds: {chunk_bounds}, TextLen: {len(text_content)}). Skipping.")
                           # Log failure?
                           continue
                     except Exception as e:
                          logger.error(f"Unexpected error slicing content for chunk {chunk_number}: {e}", exc_info=True)
                          continue

                     # Perform analysis
                     analysis_result = analyzer.analyze_chunk_content(content_for_chunk)
                     current_time = get_current_timestamp_iso()

                     # Log the outcome
                     db.log_request(file_path, chunk_number, current_time, analysis_result)

                     # Store successful results
                     if analysis_result.success and analysis_result.extracted_data:
                          db.store_results(
                               db.connection.execute("SELECT last_insert_rowid()").fetchone()[0], # Get last request ID
                               file_path,
                               chunk_number,
                               analysis_result.extracted_data
                          )
                     elif not analysis_result.success:
                          logger.warning(f"Analysis failed for chunk {chunk_number}. Error: {analysis_result.error_message}")

                     # Optional slight delay
                     # time.sleep(0.05)

                if signal_received: break # Check again after finishing file's chunks

    except sqlite3.OperationalError as e:
        logger.critical_exit(f"Exiting due to critical database error: {e}")
    except Exception as e:
        logger.critical(f"An unexpected critical error occurred during analysis: {e}")
        logger.exception("Traceback:")
        # Attempt to signal handler for cleanup if possible, though it might fail
        signal_handler(signal.SIGINT, None)
        sys.exit(1)


# --- Entry Point ---
def main():
    """Main function to setup and run the analysis."""
    start_iso = get_current_timestamp_iso()
    # Check for duplicate args before parsing fully
    check_duplicate_args(sys.argv)
    args = parse_arguments()

    # Setup Logging
    logger.set_log_level(args.log_level)
    # Use non-negative int parser for max_log_length, 0 means unlimited (None)
    log_excerpt = args.max_log_length if args.max_log_length > 0 else None
    logger.set_excerpt_length(log_excerpt)
    logger.set_max_passable(
        max_errors=MAX_PASSABLE_EXECUTION_ERRORS,
        max_warnings=MAX_PASSABLE_WARNINGS,
        error_message="Too many critical errors ({max_errors}). Aborting run.",
        warning_message="Too many warnings ({max_warnings}), indicating potential issues. Aborting run."
    )

    # Load Environment Variables (.env file)
    load_dotenv()
    api_key = os.getenv('OPENROUTER_API_KEY')

    # Load Configuration File
    config = ConfigLoader.load_config_file(args.config)
    if not config:
        sys.exit(1) # Error logged in load_config_file

    # Override config defaults with CLI arguments
    config.inconfig_values.chunk_size = args.chunk_size
    config.inconfig_values.temperature = args.temperature
    config.inconfig_values.timeout = args.timeout
    config.inconfig_values.data_folder = args.data_folder
    config.inconfig_values.max_failures = args.max_failures
    config.inconfig_values.model = args.model
    config.inconfig_values.provider = args.provider
    config.inconfig_values.max_log_length = args.max_log_length # Store CLI value

    # Apply other CLI args to config object
    config.results_db = args.results_db
    config.skip_key_check = args.skip_key_check
    config.run_tag = args.run_tag
    config.key = api_key

    # Final validation of combined config
    if not ConfigLoader.validate_runtime_config(config):
        sys.exit(1)

    # Log final configuration (excluding sensitive info like key)
    logger.info("--- GAR Tool Configuration ---")
    logger.info(f"Version: {__version__}")
    logger.info(f"Run Start Time (UTC): {start_iso}")
    logger.info(f"Config File: {args.config}")
    logger.info(f"Data Folder: {config.inconfig_values.data_folder}")
    logger.info(f"Results DB: {config.results_db}")
    logger.info(f"Run Tag: {config.run_tag}")
    logger.info(f"Model: {config.inconfig_values.model}")
    logger.info(f"Provider: {config.inconfig_values.provider}")
    logger.info(f"Chunk Size: {config.inconfig_values.chunk_size}")
    logger.info(f"Temperature: {config.inconfig_values.temperature}")
    logger.info(f"Timeout: {config.inconfig_values.timeout}")
    logger.info(f"Max Failures/Chunk: {config.inconfig_values.max_failures}")
    logger.info(f"Log Level: {args.log_level}")
    logger.info(f"Log Excerpt Length: {'Unlimited' if not log_excerpt else log_excerpt}")
    logger.debug(f"Full Prompt Template (First 500 chars):\n{config.prompt[:500]}...")
    logger.info("-----------------------------")
    logger.info("Starting analysis process...")

    # Register initial signal handler (will be re-registered with DB instance later)
    signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, None, start_iso))

    # Run the main analysis workflow
    run_analysis(config, start_iso)

    # Log final summary if not interrupted
    if not signal_received:
        end_iso = get_current_timestamp_iso()
        # Need DB instance again - maybe Database should not be context managed in run_analysis?
        # Or pass DB details to log_run_summary?
        # Let's re-open DB briefly just for summary if not interrupted.
        logger.info("--- Final Run Summary ---")
        try:
            with Database(config) as final_db:
                log_run_summary(final_db, start_iso, end_iso)
        except Exception as e:
            logger.error(f"Could not generate final summary: {e}")
        logger.info("-----------------------")
        logger.info("Run completed.")


if __name__ == "__main__":
    main()
