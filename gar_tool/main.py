import sqlite3
import os, sys, stat
import signal
import yaml
import argparse
from argparse import Namespace
import json
import re
import random
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple, SupportsFloat, Callable
from dotenv import load_dotenv
import requests
import traceback

from . import __version__ as VERSION

from .logging_wrapper import logger
from .file_processor import get_text_content, calculate_chunks
from .config_handler import ExtractorConfig, ConfigLoader
from .database_handler import Database
from .analyzer import DocumentAnalyzer
from .helpers import get_current_timestamp_iso, collapse_whitespace, signal_handler, signal_received
from .cli import parse_arguments, check_duplicate_args

MAX_PASSABLE_EXECUTION_ERRORS = 3 # for things like http errors, so loop with a wrong API key would terminate
MAX_PASSABLE_WARNINGS=10 # stop if too many warnings, the model clearly can't handle it

signal_received = False  # global flag to avoid failures message duplication on terminal kill

def main():
    global signal_received
    start_iso = get_current_timestamp_iso()

    check_duplicate_args(sys.argv)
    args = parse_arguments()
    
    logger.set_log_level(args.log_level)
    logger.set_excerpt_length(args.max_log_length)
    logger.set_max_passable(
        max_errors=MAX_PASSABLE_EXECUTION_ERRORS,
        max_warnings=MAX_PASSABLE_WARNINGS,
        error_message=collapse_whitespace("""
        Too many execution errors ({max_errors}). Perhaps the LLM provider is down. Terminating process.
        """),
        warning_message=collapse_whitespace("""
        Too many warnings ({max_warnings}) encountered,
        likely from attempts to extract structured data from LLM responses,
        which means your model can't handle it. Review logs and/or try to update prompt.
        """)
    )
    config: ExtractorConfig = ConfigLoader.load_config_file(args.config)

    # Override defaults with command line arguments if provided
    if args.chunk_size is not None: config.inconfig_values.chunk_size = args.chunk_size
    if args.temperature is not None: config.inconfig_values.temperature = args.temperature
    if args.timeout is not None: config.inconfig_values.timeout = args.timeout
    if args.data_folder is not None: config.inconfig_values.data_folder = args.data_folder
    if args.max_failures is not None: config.inconfig_values.max_failures = args.max_failures
    if args.model is not None: config.inconfig_values.model = args.model
    if args.provider is not None: config.inconfig_values.provider = args.provider
    # Set fields that don't come from config, their defaults in config class declaration
    if args.results_db is not None: config.results_db = args.results_db 
    else: config.results_db=f"{config.name}.db"
    config.skip_key_check = args.skip_key_check
    if args.run_tag is not None: config.run_tag = args.run_tag
    else: config.run_tag = args.config

    load_dotenv()
    key = os.getenv('OPENROUTER_API_KEY')
    if key is not None: config.key = key

    try:
        ConfigLoader.validate_config_values(config)
    except ValueError as e:
        logger.critical_exit(f"Configuration error: {e}")

    # OK, settings are good, let's proceed

    logger.info("Welcome! Check README at Github for useful prompt engineering tips")
    logger.info(f"Version {VERSION} started run at UTC {start_iso}")
    if config.run_tag:  # Use config object
        logger.info(f"Run Tag: {config.run_tag}")
    logger.info("\n=== Using configuration:")
    logger.info(f"Database: {config.results_db}")
    logger.info(f"Context window: {config.inconfig_values.chunk_size}")
    logger.info(f"Temperature: {config.inconfig_values.temperature}")
    # logger.info(f"LLM Excerpt Length: {config.excerpt}")
    logger.info(f"Timeout: {config.inconfig_values.timeout}")
    logger.info(f"Data folder: {config.inconfig_values.data_folder}")
    logger.info(f"Max failures: {config.inconfig_values.max_failures}")
    logger.debug(f"LLM prompt: {config.prompt}")
    logger.info(f"Model: {config.inconfig_values.model}\n\nPress Ctrl-C to stop the run (you can continue later)\n")
 
    with Database(config) as db:
        analyzer = DocumentAnalyzer(config, db)
        signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, db, start_iso))
        
        try:

            # --- Cache and Set for efficiency ---
            files_processed_this_session = set() # Stores files where content has been read/converted this session
            text_content_cache = {} # Stores content {file_path: content_string}
            files_completed_this_run = set() # Stores files fully processed in this run
            # --- END Add Cache and Set ---
            
            while True:
    
                if signal_received: # Check for interrupt signal
                    logger.info("Loop interrupted by user signal.")
                    break
                
                # --- Step 1: Discover files, update cache, calculate/store chunks (mostly unchanged) ---
                # This ensures we know about all files and have their chunks defined before picking one.
                files_in_folder_full_path = [
                    os.path.abspath(os.path.join(config.inconfig_values.data_folder, f)) # Use absolute paths
                    for f in os.listdir(config.inconfig_values.data_folder)
                    if os.path.isfile(os.path.join(config.inconfig_values.data_folder, f))
                ]

                # Ensure content is cached and chunks are defined for all current files
                for full_path in files_in_folder_full_path:
                    if full_path not in files_processed_this_session:
                        logger.debug(f"Checking/Processing file for chunk definitions: {os.path.basename(full_path)}")
                        # --- Use file_processor's get_text_content ---
                        current_content = get_text_content(full_path)
                        files_processed_this_session.add(full_path) # Mark as visited this session

                        if current_content is None:
                             logger.error(f"File not found or inaccessible: {full_path}. Skipping.")
                             text_content_cache[full_path] = None # Cache None to indicate error
                             continue # Skip chunk calculation for this file
                        elif current_content == "":
                             logger.warning(f"File {os.path.basename(full_path)} is empty or conversion failed. Skipping.")
                             text_content_cache[full_path] = "" # Cache empty string
                             continue # Skip chunk calculation for this file
                        else:
                             text_content_cache[full_path] = current_content # Cache the content

                        # --- Calculate and store chunks using file_processor's calculate_chunks ---
                        if not db.chunk_exists(full_path):
                             logger.info(f"Calculating chunks for new file: {os.path.basename(full_path)}")
                             chunk_bounds = calculate_chunks(current_content, config.inconfig_values.chunk_size)
                             if chunk_bounds:
                                 db.insert_chunks(full_path, chunk_bounds)
                             else:
                                 logger.warning(f"No chunks calculated for {os.path.basename(full_path)}. Content might be too small or calculation failed.")

                # --- Step 2: Identify files that *currently* have unprocessed chunks AND haven't been completed ---
                cursor = db.connection.cursor()
                cursor.execute("SELECT DISTINCT file FROM FCHUNKS")
                known_files_in_db = {row[0] for row in cursor.fetchall()}
                files_in_folder_set = set(files_in_folder_full_path)
                # Consider only files that are both in the DB and currently in the folder
                relevant_files_in_db = list(known_files_in_db.intersection(files_in_folder_set))

                files_needing_processing = []
                logger.debug("Checking files for pending chunks...") # Add debug log
                for file_path in relevant_files_in_db:
                    # <<< CHECK if file is already marked as completed in this run >>>
                    if file_path in files_completed_this_run:
                        logger.debug(f"Skipping check for already completed file: {os.path.basename(file_path)}")
                        continue
                    # <<< END CHECK >>>

                    # Ensure content is valid before checking for unprocessed chunks (existing check)
                    if file_path in text_content_cache and text_content_cache[file_path] is not None and text_content_cache[file_path] != "":
                        logger.debug(f"Querying unprocessed chunks for: {os.path.basename(file_path)}")
                        unprocessed_check = db.get_unprocessed_chunks(file_path, start_iso)
                        if unprocessed_check: # If the list of unprocessed chunks is not empty
                            logger.debug(f"Found {len(unprocessed_check)} pending chunks for {os.path.basename(file_path)}. Adding to processing list.")
                            files_needing_processing.append(file_path)
                        else:
                            logger.debug(f"No pending chunks found for {os.path.basename(file_path)}. Marking as completed for this run.")
                            # If no unprocessed chunks are found here, mark it as complete for this run
                            files_completed_this_run.add(file_path)
                    else:
                        logger.debug(f"Skipping check for file with invalid/missing content in cache: {os.path.basename(file_path)}")
                        # File had error/was empty during step 1, or removed since start, skip.

                if not files_needing_processing:
                    logger.info("\nNo more files with unprocessed chunks found. All relevant files processed or skipped!")
                    break # Exit the main while loop

                # --- Step 3: Select a random *file* and process its chunks sequentially ---
                chosen_file_path = random.choice(files_needing_processing)
                logger.info(f"Selected file for processing: {os.path.basename(chosen_file_path)}")

                # Get *all* unprocessed chunks specifically for this chosen file
                unprocessed_chunks_for_file = db.get_unprocessed_chunks(chosen_file_path, start_iso)
                processed_all_listed_chunks = True # Flag to track if the inner loop processed all items it started with

                # Process these chunks in order
                for file, chunk_number in unprocessed_chunks_for_file: # 'file' will always be chosen_file_path here
                    if signal_received:
                        logger.info("Inner loop interrupted by user signal.")
                        processed_all_listed_chunks = False # Didn't finish the planned batch
                        break # Exit this inner for-loop

                    logger.info(f"Processing {os.path.basename(file)} chunk {chunk_number}")

                    # --- Retrieve the specific chunk's content from cache ---
                    if file not in text_content_cache or text_content_cache[file] is None:
                         logger.error(f"Content for file {os.path.basename(file)} not found or is invalid in cache. Cannot process chunk {chunk_number}. Skipping.")
                         # Mark that we didn't process everything intended for this file in this pass
                         # processed_all_listed_chunks = False # Let's not do this, failure != interruption
                         continue # Skip this chunk

                    text_content = text_content_cache[file]
                    chunk_bounds = db.get_chunk_bounds(file, chunk_number)

                    if not chunk_bounds:
                         logger.error(f"Could not retrieve bounds for chunk {chunk_number} of {os.path.basename(file)}. Skipping.")
                         # processed_all_listed_chunks = False
                         continue # Skip this chunk

                    try:
                         # Slice the content based on stored bounds
                         content_for_chunk = text_content[chunk_bounds[0]:chunk_bounds[1]]
                    except IndexError:
                         logger.error(f"Error slicing content for {os.path.basename(file)} chunk {chunk_number}. Bounds: {chunk_bounds}, Text Length: {len(text_content)}. Skipping.")
                         # processed_all_listed_chunks = False
                         continue # Skip this chunk
                    except Exception as slice_e:
                         logger.error(f"Unexpected error slicing content for {os.path.basename(file)} chunk {chunk_number}: {slice_e}. Skipping.")
                         # processed_all_listed_chunks = False
                         continue # Skip this chunk
                    # --- END OF Content Retrieval ---

                    # --- Call the process_chunk ---
                    # Success/failure is handled internally by process_chunk and logged to DB
                    analyzer.process_chunk(
                        db=db,
                        filename=file,
                        chunk_number=chunk_number,
                        chunk_content=content_for_chunk # Pass the actual content
                    )
                # --- End of sequential chunk processing for the chosen file ---

                # --- Step 4: Check completion status *after* attempting to process the batch ---
                if signal_received: # If interrupted during the inner loop
                     logger.info("Outer loop interrupted by user signal after file processing batch.")
                     break # Exit the main while loop

                # Only check for completion if the inner loop wasn't interrupted by signal
                # We re-query to see the current state after the processing attempts
                logger.debug(f"Re-checking unprocessed chunks for {os.path.basename(chosen_file_path)} after processing attempt.")
                unprocessed_after_attempt = db.get_unprocessed_chunks(chosen_file_path, start_iso)
                if not unprocessed_after_attempt:
                    logger.info(f"Confirmed: File {os.path.basename(chosen_file_path)} now fully processed or all remaining chunks skipped for this run.")
                    files_completed_this_run.add(chosen_file_path)
                else:
                    # This case means either some chunks failed and haven't hit max_failures yet,
                    # or they were skipped due to errors before calling process_chunk.
                    logger.info(f"File {os.path.basename(chosen_file_path)} still has {len(unprocessed_after_attempt)} unprocessed/pending chunks after this pass.")
                    # The file remains *not* in files_completed_this_run and might be picked again later.

        finally:
            end_iso = get_current_timestamp_iso()
            if not signal_received:
                 try:
                     logger.info(db.get_run_summary(start_iso, end_iso))
                 except Exception as summary_e:
                     logger.error(f"Failed to generate final run summary: {summary_e}")

if __name__ == "__main__":
    main()