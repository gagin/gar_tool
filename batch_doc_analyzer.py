import sqlite3
import os, sys, stat
import signal
import yaml
import argparse
from argparse import Namespace
import json
import random
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple, SupportsFloat, Callable
from dotenv import load_dotenv
import requests
import requests.exceptions
#import time
import traceback
import logging_wrapper

VERSION = '0.1.16' # requires major.minor.patch notation for auto-increment on commits via make command
MAX_LLM_EXTRACTION_FAILURES_LIMIT_PER_CHUNK = 5 # limit on maximum accepted value provided by the user
MAX_PASSABLE_EXECUTION_ERRORS = 3 # for things like http errors, so loop with a wrong API key would terminate
MAX_PASSABLE_WARNINGS=10 # stop if too many warnings, the model clearly can't handle it
### Utility code first

logger = logging_wrapper.logger

def get_current_timestamp_iso():
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()

def collapse_whitespace(text: str): # Used for convenience in the code, to write longer messages as multiline
    return re.sub(r'\s+', ' ', text.replace('\n', ' ')).strip()

signal_received = False  # global flag to avoid failures message duplication on terminal kill
def signal_handler(sig, frame, db_instance, start_iso):
    """Handles Ctrl+C interrupt and prints a graceful message with stats."""
    global signal_received
    signal_received = True
    logger.info('\nCtrl+C detected. Gracefully exiting...')
    end_iso = get_current_timestamp_iso()

    try:
        if db_instance and db_instance.connection:
            logger.info(db_instance.get_run_summary(start_iso, end_iso))
        else:
            logger.error("Database not initialized or connection closed.")
    except Exception as e:
        logger.exception(f"Error in signal handler: {e}")

    if db_instance and db_instance.connection:
        db_instance.close()

    sys.exit(0)

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

def parse_arguments() -> Namespace:
    parser = argparse.ArgumentParser(description=collapse_whitespace("""
    This command-line tool extracts specific information from large collections of 
    text files and organizes it into a spreadsheet within a database, using 
    Large Language Models (LLMs).  It's designed to assist with data that was 
    once structured but is now in plain text, or when deriving new insights 
    from unstructured information. Ideal for data analysts and researchers who 
    need to convert unstructured or semi-structured text into analyzable data.
    """), formatter_class=argparse.RawTextHelpFormatter)

    config_group_control = parser.add_argument_group("Script control")    
    config_group_control.add_argument('--config', type=str, default='config.yaml', help=collapse_whitespace("""
        Path to the YAML configuration file containing extraction
        parameters (default: %(default)s).
    """))   
    config_group_control.add_argument('--llm_debug_excerpt_length', type=int, default=200, help=collapse_whitespace("""
        Maximum length (in characters) of LLM response excerpts displayed
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

### Functional code

@dataclass
class ExtractorDefaults:
    chunk_size: int = 50000
    temperature: float = 0.0
    timeout: int = 30
    data_folder: str = "./src"
    max_failures: int = 2
    model: str = "google/gemini-2.0-flash-001:floor"
    provider: str = "https://openrouter.ai/api/v1"

@dataclass
class ExtractorConfig:
    name: str
    inconfig_values: ExtractorDefaults
    prompt: str
    expected_json_nodes: List[str]
    db_mapping: Dict[str, str]
    results_table: str = "DATA"
    results_db: Optional[str] = "results.db"
    key: Optional[str] = None
    skip_key_check: bool = False
    run_tag: Optional[str] = None
    excerpt: int = 100
    node_configs: Dict[str, Dict[str, Any]] = None #add node_configs to store all node configuration.

class ConfigLoader:
    @staticmethod
    def load_config_file(config_path: str) -> ExtractorConfig:
        """Load and validate configuration from YAML file"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            
            ConfigLoader.validate_file_config(config_data)  # Validate YAML structure
            
            # Load settings
            defaults = ExtractorDefaults(
                chunk_size=config_data['defaults']['chunk_size'],
                temperature=config_data['defaults']['temperature'],
                timeout=config_data['defaults']['timeout'],
                data_folder=config_data['defaults']['data_folder'],
                max_failures=config_data['defaults']['max_failures'],
                model=config_data['defaults']['model'],
                provider=config_data['defaults']['provider']
            )

            # Generate node descriptions for prompt
            node_descriptions = []
            db_mapping = {}
            node_configs = {} #store all node configurations to use required property after
            for name, node in config_data['nodes'].items():
                description = f"- {name}"
                if node.get('required') is False:  # Add optional marker
                    description += " (optional)"
                elif node.get('required') is True: # Add required marker.
                    description += " (required)"
                description += f": {node['description']}"
                if node.get('format'):
                    description += f" ({node['format']})"
                node_descriptions.append(description)

                if 'db_column' in node:
                    db_mapping[name] = node['db_column']
                node_configs[name] = node #store node configuration

            # Format prompt with node descriptions
            prompt = config_data['prompt_template'].format(
                node_descriptions='\n'.join(node_descriptions)
            )

            return ExtractorConfig(
                name=config_data['name'],
                inconfig_values=defaults,
                prompt=prompt,
                expected_json_nodes=list(config_data['nodes'].keys()),
                db_mapping=db_mapping,
                node_configs = node_configs,
            )
            
        except FileNotFoundError:
            logger.critical_exit(f"Configuration file not found: {config_path}")
            # raise ValueError(f"Configuration file not found: {config_path}")
        except yaml.YAMLError as e:
            logger.critical_exit(f"Invalid YAML in configuration file: {e}")
            # raise ValueError(f"Invalid YAML in configuration file: {e}")

    @staticmethod
    def validate_file_config(config_data: Dict[str, Any]) -> None:
        """Validate configuration parameters"""
        if not isinstance(config_data, dict):
            logger.critical_exit("Configuration must be a dictionary.")
        
        # Validate required sections
        required_sections = ['name', 'defaults', 'nodes', 'prompt_template']
        for section in required_sections:
            if section not in config_data:
                logger.critical_exit(f"Missing required section: {section}.")
        
        # Validate inconfig_values
        defaults = config_data['defaults']
        if not isinstance(defaults, dict):
            logger.critical_exit("'defaults' must be a dictionary.")
            
        # Values check is done after CLI overrides
            
        # Validate nodes
        nodes = config_data['nodes']
        if not isinstance(nodes, dict):
            logger.critical_exit("'nodes' must be a dictionary.")
        for node_name, node_config in nodes.items():
            if not isinstance(node_config, dict):
                logger.critical_exit(f"Node '{node_name}' configuration must be a dictionary.")
            if 'description' not in node_config:
                logger.critical_exit(f"Node '{node_name}' missing required 'description' field.")
            if 'required' in node_config and not isinstance(node_config['required'], bool):
                logger.critical_exit(f"Invalid 'required' value for node '{node_name}'. Must be boolean (true or false).")

            
    def validate_config_values(config: ExtractorConfig) -> None:
        """Validates input parameters, exiting with an error message on the first error.
        Includes superficial API key validation.

        Exits:
            1: If any of the following conditions are met:
                - A parameter is of the wrong type or has an invalid value.
                - The data folder does not exist or is not accessible.
                - The API key is missing and not skipped.
        """

        settings = config.inconfig_values
        if not isinstance(settings.temperature, (int, float)): 
            logger.critical_exit(f"Temperature must be a number, got {type(settings.temperature)}") 
        if not (0 <= settings.temperature <= 1): 
            logger.critical_exit(f"Temperature must be between 0 and 1, got {settings.temperature}") 

        if not isinstance(settings.chunk_size, int): 
            logger.critical_exit(f"Context window must be an integer, got {type(settings.chunk_size)}") 

        if settings.chunk_size <= 0: 
            logger.critical_exit(f"Context window must be positive, got {settings.chunk_size}") 

        if not isinstance(settings.timeout, int): 
            logger.critical_exit(f"Timeout must be an integer, got {type(settings.timeout)}") 

        if settings.timeout <= 0: 
            logger.critical_exit(f"Timeout must be positive, got {settings.timeout}") 

        if not isinstance(settings.max_failures, int): 
            logger.critical_exit(f"Max failures must be an integer, got {type(settings.max_failures)}") 

        if settings.max_failures < 1: 
            logger.critical_exit(f"Max failures must be at least 1, got {settings.max_failures}") 
        if settings.max_failures > MAX_LLM_EXTRACTION_FAILURES_LIMIT_PER_CHUNK: 
            logger.critical_exit(f"Max failures cannot exceed {MAX_LLM_EXTRACTION_FAILURES_LIMIT_PER_CHUNK}, got {settings.max_failures}") 

        if not isinstance(config.excerpt, int): 
            logger.critical_exit(f"LLM debug excerpt length must be an integer, got {type(config.excerpt)}") 
        if config.excerpt <= 0: 
            logger.critical_exit(f"LLM debug excerpt length must be positive, got {config.excerpt}") 

        data_folder = settings.data_folder #assign to a variable to avoid long lines 
        if not isinstance(data_folder, str): 
            logger.critical_exit(f"Data folder must be a string, got {type(data_folder)}") 
        if not data_folder:  # Check for empty string 
            logger.critical_exit("Data folder must be specified") 
        if not os.path.exists(data_folder): 
            logger.critical_exit(f"Data folder '{data_folder}' does not exist") 
        if not os.path.isdir(data_folder): 
            logger.critical_exit(f"'{data_folder}' is not a directory") 
        if not os.access(data_folder, os.R_OK): 
            logger.critical_exit(f"Data folder '{data_folder}' is not readable") 

        if not isinstance(settings.model, str): 
            logger.critical_exit(f"Model must be a string, got {type(settings.model)}") 
        if not settings.model:  # Check for empty string 
            logger.critical_exit("Model cannot be empty") 

        if not isinstance(settings.provider, str): 
            logger.critical_exit(f"Provider must be a string, got {type(settings.provider)}") 
        if not settings.provider:  # Check for empty string 
            logger.critical_exit("Provider cannot be empty") 

        if not config.key and not config.skip_key_check:
            error_message = collapse_whitespace("""
                API key is missing. Either set the OPENROUTER_API_KEY environment variable,
                or use --skip_key_check if the model does not require an API key.
                """)
            logger.critical_exit(error_message)

@dataclass
class Column:
    name: str
    type: str
    primary_key: bool = False
    nullable: bool = True
    default: Optional[str] = None

@dataclass
class Table:
    name: str
    columns: List[Column]
    
    def get_create_statement(self) -> str:
        cols = []
        pk_cols = []
        
        for col in self.columns:
            col_def = f"{col.name} {col.type}"
            if not col.primary_key and not col.nullable:
                col_def += " NOT NULL"
            if col.default is not None:
                col_def += f" DEFAULT {col.default}"
            if col.primary_key:
                pk_cols.append(col.name)
            cols.append(col_def)
            
        if pk_cols:
            cols.append(f"PRIMARY KEY ({', '.join(pk_cols)})")
            
        return f"CREATE TABLE IF NOT EXISTS {self.name} ({', '.join(cols)})"
    
    def get_column_names(self) -> List[str]:
        return [col.name for col in self.columns]



@dataclass
class ProcessingResult:
    """Stores both raw response and extracted data"""
    success: bool
    raw_response: str
    extracted_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class Database:
    def __init__(self, config: ExtractorConfig): # This is init of the db object, not the db file
        self.config = config
        self.connection = None

    def __enter__(self):
        self.connect()
        self.schema = self._create_schema()
        self.init_tables()
        self.create_indexes() # Create indexes after connecting to the database.
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.connection:
            self.connection.close()
            self.connection = None
            
    def connect(self):
        db_path = self.config.results_db

        try:
            # Initial connection attempt
            self.connection = sqlite3.connect(db_path)
            self._debug_log_busy_timeout()

            # Check database integrity immediately after connection
            cursor = self.connection.cursor()
            cursor.execute("PRAGMA integrity_check;")
            result = cursor.fetchone()
            if result[0] != 'ok':
                self.connection.close()
                logger.critical_exit(f"The file '{db_path}' is not a valid SQLite database (integrity check failed). Error: {result[0]}")

            return self.connection  # Return connection only if successful and integrity check passes

        except sqlite3.OperationalError as e:  # Catch specific OperationalErrors
            self.connection = None # Ensure connection is None if it failed.
            if os.path.isdir(db_path):
                logger.critical_exit(f"The path '{db_path}' is a directory, not a file.")

            try:
                mode = os.stat(db_path).st_mode
                if not (stat.S_IREAD & mode and stat.S_IWRITE & mode):
                    logger.critical_exit(f"The file '{db_path}' does not have read and write permissions.")
            except FileNotFoundError:  # Handle the case where the file doesn't exist
                logger.critical_exit(f"The file '{db_path}' was not found.")
            except Exception as perm_e:
                logger.error(f"An unexpected error occurred when checking file permissions: {perm_e}")
                raise  # Re-raise for higher-level handling

            try:
                parent_dir = os.path.dirname(db_path)
                if not os.access(parent_dir, os.W_OK):
                    logger.critical_exit(f"The directory '{parent_dir}' does not have write permissions.")
            except Exception as dir_perm_e:
                logger.error(f"An unexpected error occurred when checking directory permissions: {dir_perm_e}")
                raise  # Re-raise

            logger.critical_exit(f"An OperationalError occurred: {e}. SQLite Error Code: {getattr(e, 'sqlite_errorcode', None)}")

        except sqlite3.DatabaseError as e:  # Catch other DatabaseErrors
            logger.critical_exit(f"The file '{db_path}' is not a valid SQLite database. Underlying error: {e}. SQLite Error Code: {getattr(e, 'sqlite_errorcode', None)}")

        except Exception as e:  # Catch any other unexpected exceptions
            logger.exception(f"An unexpected error occurred: {e}") # Use logger.exception to include traceback
            raise  # Re-raise the exception after logging
        
    def _debug_log_busy_timeout(self):  # Private helper method
        if logger.get_log_level_name() == "DEBUG":
            try:
                cursor = self.connection.cursor()
                cursor.execute("PRAGMA busy_timeout;")
                timeout = cursor.fetchone()[0]
                logger.debug(f"SQLite busy_timeout: {timeout} ms")
            except sqlite3.Error as e:
                logger.error(f"Error getting busy_timeout: {e}")
                
    def _execute(self, cursor: sqlite3.Cursor, operation: Callable, query: str, params: Any = None) -> Tuple[bool, Optional[int]]:
        """Generic wrapper for cursor.execute() and cursor.executemany().
           Returns (success, lastrowid) where lastrowid is only available for execute.
        """
        lastrowid = None  # Initialize lastrowid
        try:
            if params is not None:
                operation(query, params)
                if operation == cursor.execute: # Only get lastrowid for single executes
                    lastrowid = cursor.lastrowid
            else:
                operation(query)
                if operation == cursor.execute: # Only get lastrowid for single executes
                    lastrowid = cursor.lastrowid
        except sqlite3.OperationalError as e:
            if hasattr(e, 'sqlite_errorcode') and e.sqlite_errorcode == sqlite3.SQLITE_LOCKED:
                logger.critical_exit(f"Database locked: {e}")
            elif hasattr(e, 'sqlite_errorcode') and e.sqlite_errorcode == sqlite3.SQLITE_BUSY:
                logger.critical_exit(f"The database file is busy, do you have unsaved changes in DB Browser? [Operation returned: {e}]")
            else:
                logger.critical_exit(f"Database OperationalError: {e}")
        except Exception as e:
            logger.critical_exit(f"An unexpected error occurred during database operation: {e}")

        return True, lastrowid  # Return True and lastrowid (or None)

    def _execute_query(self, cursor: sqlite3.Cursor, query: str, params: Any = None) -> Tuple[bool, Optional[int]]:
        """Wrapper for cursor.execute()."""
        return self._execute(cursor, cursor.execute, query, params)

    def _execute_many(self, cursor: sqlite3.Cursor, query: str, params: Any = None) -> bool: # Return just success for executemany
        """Wrapper for cursor.executemany()."""
        success, _ = self._execute(cursor, cursor.executemany, query, params)
        return success

        
    def init_tables(self):
        cursor = self.connection.cursor()
        for table in self.schema.values():
            if not self._execute_query(cursor, table.get_create_statement()):
                raise RuntimeError("Failed to create tables") # Or handle differently
        self.connection.commit()
    
    def _create_schema(self) -> Dict[str, Table]:
        request_log_columns = [
            Column('id', 'INTEGER', primary_key=True),
            Column('file', 'TEXT', nullable=False),
            Column('chunknumber', 'INTEGER', nullable=False),
            Column('timestamp', 'DATETIME', nullable=False),
            Column('model', 'TEXT', nullable=False),
            Column('raw_response', 'TEXT'),
            Column('success', 'BOOLEAN', nullable=False),
            Column('error_message', 'TEXT'),
        ]
        
        results_columns = [
            Column('request_id', 'INTEGER', primary_key=True),
            Column('file', 'TEXT', nullable=False),
            Column('chunknumber', 'INTEGER', nullable=False),
            Column('run_tag', 'TEXT', nullable=True)
        ]
        
        for json_node, db_column in self.config.db_mapping.items():
            results_columns.append(Column(db_column, 'TEXT'))
        
        if self.connection is None:
            self.connect() # connect so cursor can be created.
        
        return {
            'FCHUNKS': Table(
                name='FCHUNKS',
                columns=[
                    Column('file', 'TEXT', primary_key=True),
                    Column('chunknumber', 'INTEGER', primary_key=True),
                    Column('start', 'INTEGER'),
                    Column('end', 'INTEGER')
                ]
            ),
            'REQUEST_LOG': Table(
                name='REQUEST_LOG',
                columns=request_log_columns
            ),
            'RESULTS': Table(
                name=self.config.results_table,
                columns=results_columns
            )
        }
    
    def create_indexes(self):
        cursor = self.connection.cursor()
        try:
            if not self._execute_query(cursor, 'CREATE INDEX IF NOT EXISTS idx_request_log_file_chunk ON REQUEST_LOG(file, chunknumber)'):
                logger.error("Failed to create index idx_request_log_file_chunk")
            if not self._execute_query(cursor, f'CREATE INDEX IF NOT EXISTS idx_results_file_chunk ON {self.config.results_table}(file, chunknumber, run_tag)'):
                logger.error(f"Failed to create index idx_results_file_chunk")
            self.connection.commit()
        except Exception as e:
            logger.error(f"Error creating indexes: {e}")
            logger.warning("Continuing without indexes. Performance may be degraded.")


    def chunk_exists(self, filename: str) -> bool:
        cursor = self.connection.cursor()
        cursor.execute(
            'SELECT COUNT(*) FROM FCHUNKS WHERE file = ?',
            (filename,)
        )
        return cursor.fetchone()[0] > 0
    
    def insert_chunks(self, file: str, chunks: List[Tuple[int, int]]):
        cursor = self.connection.cursor()
        query = 'INSERT INTO FCHUNKS (file, chunknumber, start, end) VALUES (?, ?, ?, ?)'
        params = [(file, i, chunk[0], chunk[1]) for i, chunk in enumerate(chunks)]

        if not self._execute_many(cursor, query, params):  # Use the new _execute_many
            logger.critical_exit("Failed to insert chunks to the db")

        self.connection.commit()
    
    def get_chunk_bounds(self, filename: str, chunk_number: int) -> Optional[Tuple[int, int]]:
        cursor = self.connection.cursor()
        cursor.execute(
            'SELECT start, end FROM FCHUNKS WHERE file = ? AND chunknumber = ?',
            (filename, chunk_number)
        )
        return cursor.fetchone()
    
    def get_unprocessed_chunks(self, filename: str, start_iso: datetime) -> List[Tuple[str, int]]:
        try:
            cursor = self.connection.cursor()
            results_table = self.config.results_table
            run_tag = self.config.run_tag
            max_failures = self.config.inconfig_values.max_failures

            sql_query = f'''
                SELECT c.file, c.chunknumber
                FROM FCHUNKS c
                LEFT JOIN {results_table} r
                    ON c.file = r.file AND c.chunknumber = r.chunknumber
                    {f"AND r.run_tag = ?" if run_tag else ""}
                WHERE r.file IS NULL AND c.file = ?
                AND NOT EXISTS (
                    SELECT 1
                    FROM REQUEST_LOG rl
                    WHERE rl.file = c.file AND rl.chunknumber = c.chunknumber AND rl.success = 0 AND rl.timestamp > ?
                    GROUP BY rl.file, rl.chunknumber
                    HAVING COUNT(*) >= ?
                )
            '''

            params = []
            if run_tag:
                params.append(run_tag)
            params.extend([filename, start_iso, max_failures])

            cursor.execute(sql_query, tuple(params))
            return cursor.fetchall()

        except sqlite3.OperationalError as e:
            logger.exception(f"Database error: {e}")
            return []
    
    def log_request(self, file: str, chunk_number: int, result: ProcessingResult) -> int:
        cursor = self.connection.cursor()
        query = 'INSERT INTO REQUEST_LOG (file, chunknumber, timestamp, model, raw_response, success, error_message) VALUES (?, ?, ?, ?, ?, ?, ?)'
        params = (file, chunk_number, datetime.now(timezone.utc).isoformat(), self.config.inconfig_values.model, result.raw_response, result.success, result.error_message)

        success, lastrowid = self._execute_query(cursor, query, params)

        if not success:
            logger.error("Failed to log request. Exiting.")
            raise RuntimeError("Failed to log request: {e}")

        self.connection.commit()
        return lastrowid if lastrowid is not None else -1 # Return lastrowid or -1 on failure

    def store_results(self, request_id: int, file: str, chunk_number: int, data: Dict[str, Any]):
        cursor = self.connection.cursor()

        columns = ['request_id', 'file', 'chunknumber']
        values = [request_id, file, chunk_number]

        for json_node, db_column in self.config.db_mapping.items():
            value_to_append = data.get(json_node)

            if self.config.node_configs.get(json_node).get('required') is True: # was that node requested as required in the config?
                if value_to_append is None: # yaml didn't say that node was optional, but llm did not return it
                    logger.warning(f"Required node '{json_node}' missing from LLM response for file '{file}', chunk {chunk_number}.")

            columns.append(db_column)
            values.append(value_to_append)

        # Add run_tag if it exists
        if self.config.run_tag is not None:
            columns.append('run_tag')
            values.append(self.config.run_tag)

        placeholders = ','.join(['?' for _ in values])
        query = f'INSERT INTO {self.config.results_table} ({",".join(columns)}) VALUES ({placeholders})'

        if not self._execute_query(cursor, query, values):  # Use the wrapper
            return  # Or raise an exception if you prefer

        self.connection.commit()

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def get_all_skipped_chunks_for_run(self, start_iso: datetime, end_iso: datetime) -> List[Tuple[str, int]]:
        """Get all chunks that are currently in failure timeout for a specific run."""
        cursor = self.connection.cursor()

        cursor.execute('''
            SELECT file, chunknumber, COUNT(*) as failures
            FROM REQUEST_LOG
            WHERE success = 0
            AND timestamp >= ? AND timestamp <= ?
            GROUP BY file, chunknumber
            HAVING failures >= ?
            ''', (start_iso, end_iso, self.config.inconfig_values.max_failures))

        return cursor.fetchall()
    
    def get_run_summary(self, start_iso: str, end_iso: str) -> str:
        """Retrieves and formats the run summary details."""
        all_skipped = self.get_all_skipped_chunks_for_run(start_iso, end_iso)
        summary = ""
        if all_skipped:
            summary += "\nFinal summary of skipped chunks:\n"
            for file, chunk, failures in all_skipped:
                summary += f"- {file} chunk {chunk} ({failures} failures)\n"

        try:
            if self.connection:
                cursor = self.connection.cursor()
                cursor.execute("SELECT COUNT(*) FROM REQUEST_LOG WHERE timestamp >= ? AND timestamp <= ?", (start_iso, end_iso))
                llm_calls = cursor.fetchone()[0]

                cursor.execute(f"""SELECT COUNT(*) 
                            FROM {self.config.results_table}
                            WHERE request_id IN (SELECT id from REQUEST_LOG where timestamp >= ? AND timestamp <= ?)""",
                            (start_iso, end_iso))
                successes = cursor.fetchone()[0]

                summary += f"\nSuccessful data extractions: {successes} out of {llm_calls} LLM calls"
            else:
                    summary += "\nDatabase not initialized or connection closed."
        except sqlite3.OperationalError as e:
            summary += f"\nError retrieving stats from database: {e}"
        except AttributeError as e:
            summary += f"\nAttributeError: {e}. Possible db initialization issues."

        start_datetime = datetime.fromisoformat(start_iso.replace('Z', '+00:00'))
        end_datetime = datetime.fromisoformat(end_iso.replace('Z', '+00:00'))
        duration = end_datetime - start_datetime
        summary += f"\nRun duration: {duration}"

        return summary

class DocumentAnalyzer:
    def __init__(self, config: ExtractorConfig, db: Database):
        self.config = config
        self.db = db

    def get_llm_response(self, content: str, prompt: str) -> Tuple[Optional[str], str]:
        global signal_received
        if signal_received:
            return None, "Request skipped due to interrupt."

        try:
            headers = {
                "Authorization": f"Bearer {self.config.key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": self.config.inconfig_values.model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": content}
                ],
                "temperature": self.config.inconfig_values.temperature
            }

            response = requests.post(
                f"{self.config.inconfig_values.provider}/chat/completions",
                headers=headers,
                json=data,
                timeout=self.config.inconfig_values.timeout
            )

            response.raise_for_status()

            if signal_received:
                return None, "Request interrupted after response, during processing"

            logger.debug(f"Status code: {response.status_code}")
            logger.debug(f"Raw response: {response.text.strip()}")

            if not response.text.strip():
                return None, ""

            response_data = response.json()

            if 'choices' not in response_data or not response_data['choices']:
                return None, json.dumps(response_data)

            choice = response_data['choices'][0]
            if 'message' not in choice or 'content' not in choice['message']:
                return None, json.dumps(response_data)

            return choice['message']['content'], json.dumps(response_data)

        except requests.exceptions.HTTPError as e:
            error_message = None
            try:
                error_message = f". Error message: {e.response.json().get('error', {}).get('message')}"
            except:
                pass #Ignore any error during json parsing.
            logger.error(f"HTTP error making request to {self.config.inconfig_values.provider}: {e}{error_message or ''}")
            return None, f"Request error: {e}{error_message or ''}"
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making request to {self.config.inconfig_values.provider}: {e}")
            return None, f"Request error: {e}"
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON response: {e}")
            return None, f"JSON decode error: {e}"
        except KeyError as e:
            logger.error(f"KeyError in JSON response: {e}")
            return None, f"Key error: {e}"
        except requests.exceptions.HTTPError as e:
            logger.exception(f"HTTP Error: {e}")
            return None, f"HTTP Error: {e}"
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            return None, f"Unexpected error: {e}"
        

    def _aggressive_json_cleaning(self, response: str) -> str:
        """Attempts aggressive ```json extraction."""
        match = re.search(r"```json\s*([\s\S]*?)\s*```", response)
        if match:
            try:
                json_string = match.group(1).strip()
                json.loads(json_string)  # Just check if it's valid JSON
                logger.debug("Aggressive JSON extraction from ```json block successful.")
                return json_string
            except json.JSONDecodeError as e:
                logger.debug(f"Aggressive JSON decode error: {e}. First {self.config.excerpt} characters of raw response: {response}")
                return response  # Return original response if aggressive cleaning fails
            except Exception as e:
                logger.error(f"Unexpected error during aggressive ```json extraction: {e}")
                return response  # Return original response on any other exception
        else:
            return response  # Return original response if no ```json block is found

    def _super_aggressive_json_cleaning(self, response: str) -> str:
        """Attempts super-aggressive curly braces cleaning."""
        try:
            start = response.find('{')
            end = response.rfind('}')
            if start != -1 and end != -1:
                super_aggressive_cleaned_response = response[start:end + 1]
                try:
                    json.loads(super_aggressive_cleaned_response)
                    logger.debug("Super-aggressive JSON cleaning helped.")
                    logger.debug(f"First {self.config.excerpt} characters of super-aggressively cleaned response: {super_aggressive_cleaned_response}")
                    return super_aggressive_cleaned_response
                except json.JSONDecodeError as e:
                    logger.error(f"Super-aggressive JSON cleaning failed: {e}. First {self.config.excerpt} characters of raw response: {response}")
                    return response
            else:
                logger.warning("Could not find JSON braces in the response.")
                return response
        except Exception as e:
            logger.error(f"Unexpected error during super-aggressive cleaning: {e}")
            return response


    def clean_json_response(self, response: str) -> Optional[dict]: # -> str:
        """Cleans the LLM response to extract JSON, using aggressive and super-aggressive cleaning as fallbacks."""

        if not response:
            return response

        try:
            cleaned_response = re.sub(r'^```json\s*', '', response.strip(), flags=re.MULTILINE)
            cleaned_response = re.sub(r'^```\s*', '', cleaned_response, flags=re.MULTILINE)
            cleaned_response = re.sub(r'\s*```$', '', cleaned_response, flags=re.MULTILINE)
            cleaned_response = cleaned_response.strip()
            return json.loads(cleaned_response)
            # return cleaned_response
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug(f"Initial JSON decode error: {e}. Response: {response}")

            # Attempt aggressive cleaning
            aggressive_cleaned = self._aggressive_json_cleaning(response)  # Call aggressive cleaning
            try:
                json_response = json.loads(aggressive_cleaned)
                logger.debug("Aggressive cleaning succeeded.")
                return json_response
            except json.JSONDecodeError as e:
                logger.debug(f"Aggressive cleaning failed: {e}. Aggressively cleaned response: {aggressive_cleaned}")

                # Attempt super-aggressive cleaning
                super_aggressive_cleaned = self._super_aggressive_json_cleaning(response) # Call super-aggressive cleaning
                try:
                    json_response = json.loads(super_aggressive_cleaned)
                    logger.debug("Super-aggressive cleaning succeeded.")
                    return json_response
                except json.JSONDecodeError as e:
                    logger.warning(f"All cleaning attempts failed, even super-aggressive: {e}. Super-aggressively cleaned response: {super_aggressive_cleaned}")
                    return None  # Return None only after all attempts fail

        except Exception as e:
            logger.error(f"Unexpected error during JSON cleaning: {e}. Response: {response}")
            return None  # Return None on any other exception

    def calculate_chunks(self, filename: str) -> List[Tuple[int, int]]:
        try:
            with open(filename, 'r', encoding='utf-8') as file:
                content = file.read()
        except UnicodeDecodeError:
            logger.exception(f"File {filename} is not valid UTF-8")
            raise
        
        if not content:
            return []
        
        if len(content) <= self.config.inconfig_values.chunk_size:
            return [(0, len(content))]  # Single chunk if it fits
        
        chunks = []
        start = 0
        
        while start < len(content):
            window = content[start:start + self.config.inconfig_values.chunk_size]
            match = list(re.finditer(r'[\.\!\?]\s', window))
            
            if not match: 
                end = min(start + self.config.inconfig_values.chunk_size, len(content))
            else:
                end = start + match[-1].end()
            
            chunks.append((start, end))
            start = end
        
        return chunks

    def get_chunk_content(self, filename: str, chunk_bounds: Tuple[int, int]) -> str:
        with open(filename, 'r', encoding='utf-8') as file:
            content = file.read()
            return content[chunk_bounds[0]:chunk_bounds[1]]

    def process_chunk(self, db: Database, filename: str, chunk_number: int) -> bool:
        """Invokes LLM call function and stores results"""
        chunk_bounds = db.get_chunk_bounds(filename, chunk_number)
        if not chunk_bounds:
            return False

        content = self.get_chunk_content(filename, chunk_bounds)

        try:
            response, full_response = self.get_llm_response(
                content,
                self.config.prompt
            )

            if response is None:
                result = ProcessingResult(
                    success=False,
                    raw_response=full_response,
                    error_message="Empty response from model"
                )
            else:
                # cleaned_response = self.clean_json_response(response)
                json_response = self.clean_json_response(response)

                if json_response is None: # Check if json_response is None
                    result = ProcessingResult(
                        success=False,
                        raw_response=full_response,
                        error_message="Failed to extract valid JSON"  # Clearer error message
                    )
                else:
                    missing_nodes = [
                        node for node in self.db.config.expected_json_nodes
                        if node not in json_response
                    ]

                    if missing_nodes:
                        result = ProcessingResult(
                            success=False,
                            raw_response=full_response,
                            error_message=f"Missing expected nodes: {missing_nodes}"
                        )
                    else:
                        result = ProcessingResult(
                            success=True,
                            raw_response=full_response,
                            extracted_data=json_response
                        )

            request_id = db.log_request(filename, chunk_number, result)

            if result.success and result.extracted_data:
                try:
                    db.store_results(
                        request_id, filename, chunk_number, result.extracted_data
                    )
                except sqlite3.OperationalError as e:
                    logger.critical_exit(f"Error storing results: {e}. Check the {db.config.results_table} table schema. File: {filename}, Chunk: {chunk_number}")

            return result.success
        except Exception as e:
            result = ProcessingResult(
                success=False,
                raw_response=full_response,
                error_message=f"Error processing chunk: {str(e)}"
            )

            db.log_request(filename, chunk_number, result)

            if logger.get_log_level_name == "DEBUG":
                logger.exception("Error processing chunk (DEBUG mode):") # Log with traceback
            else:
                return False # Continue execution (as before)
    
def main():
    global signal_received
    start_iso = get_current_timestamp_iso()

    check_duplicate_args(sys.argv)
    args = parse_arguments()
    
    logger.set_log_level(args.log_level)
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
    if args.llm_debug_excerpt_length is not None: config.excerpt = args.llm_debug_excerpt_length

    load_dotenv()
    key = os.getenv('OPENROUTER_API_KEY')
    if key is not None: config.key = key

    try:
        ConfigLoader.validate_config_values(config)
    except ValueError as e:
        logger.critical_exit(f"Configuration error: {e}")

    # OK, settings are good, let's proceed

    logger.set_excerpt_length(config.excerpt)

    logger.info("Welcome! Check README at Github for useful prompt engineering tips")
    logger.info(f"Version {VERSION} started run at UTC {start_iso}")
    if config.run_tag:  # Use config object
        logger.info(f"Run Tag: {config.run_tag}")
    logger.info("\n=== Using configuration:")
    logger.info(f"Database: {config.results_db}")
    logger.info(f"Context window: {config.inconfig_values.chunk_size}")
    logger.info(f"Temperature: {config.inconfig_values.temperature}")
    logger.info(f"LLM Excerpt Length: {config.excerpt}")
    logger.info(f"Timeout: {config.inconfig_values.timeout}")
    logger.info(f"Data folder: {config.inconfig_values.data_folder}")
    logger.info(f"Max failures: {config.inconfig_values.max_failures}")
    logger.debug(f"LLM prompt: {config.prompt}")
    logger.info(f"Model: {config.inconfig_values.model}\n\nPress Ctrl-C to stop the run (you can continue later)\n")
 
    with Database(config) as db:
        analyzer = DocumentAnalyzer(config, db)
        signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, db, start_iso))
        
        try:
            while True:
                files = [f for f in os.listdir(config.inconfig_values.data_folder)
                        if os.path.isfile(os.path.join(config.inconfig_values.data_folder, f))]

                unprocessed = []
                for file in files:
                    full_path = os.path.join(config.inconfig_values.data_folder, file)

                    if not db.chunk_exists(full_path):
                        chunks = analyzer.calculate_chunks(full_path)
                        db.insert_chunks(full_path, chunks)

                    chunks = db.get_unprocessed_chunks(
                        full_path,
                        start_iso
                    )
                    unprocessed.extend(chunks)

                if not unprocessed:
                    logger.info("\nAll chunks processed or skipped!")
                    break

                file, chunk_number = random.choice(unprocessed)
                logger.info(f"Processing {file} chunk {chunk_number}")

                analyzer.process_chunk(
                    db=db,
                    filename=file,
                    chunk_number=chunk_number
                )

                if signal_received:
                    logger.info("Loop interrupted by user.")
                    break

        finally:
            end_iso = get_current_timestamp_iso()
            if not signal_received:
                logger.info(db.get_run_summary(start_iso, end_iso))

if __name__ == "__main__":
    main()