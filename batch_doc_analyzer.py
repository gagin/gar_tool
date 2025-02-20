import sqlite3
import os
import signal
import sys
import stat
import yaml
import textwrap
import argparse
from argparse import Namespace
import json
import random
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple, SupportsFloat
from dotenv import load_dotenv
import requests
import requests.exceptions
import threading
import time
import logging

VERSION = '0.1.11' # requires major.minor.patch notation for auto-increment on commits via make command

@dataclass
class ExtractorDefaults:
    chunk_size: int
    temperature: float
    timeout: int
    data_folder: str
    max_failures: int
    model: str
    provider: str

@dataclass
class ExtractorConfig:
    name: str
    defaults: ExtractorDefaults
    prompt: str
    expected_json_nodes: List[str]
    db_mapping: Dict[str, str]
    results_table: str = "DATA"

class ConfigLoader:
    @staticmethod
    def validate_config(config_data: Dict[str, Any]) -> None:
        """Validate configuration parameters"""
        if not isinstance(config_data, dict):
            raise ValueError("Configuration must be a dictionary")
            
        # Validate required sections
        required_sections = ['name', 'defaults', 'nodes', 'prompt_template']
        for section in required_sections:
            if section not in config_data:
                raise ValueError(f"Missing required section: {section}")
        
        # Validate defaults
        defaults = config_data['defaults']
        if not isinstance(defaults, dict):
            raise ValueError("'defaults' must be a dictionary")
            
        # Values check is done after CLI overrides
            
        # Validate nodes
        nodes = config_data['nodes']
        if not isinstance(nodes, dict):
            raise ValueError("'nodes' must be a dictionary")
        for node_name, node_config in nodes.items():
            if not isinstance(node_config, dict):
                raise ValueError(f"Node '{node_name}' configuration must be a dictionary")
            if 'description' not in node_config:
                raise ValueError(f"Node '{node_name}' missing required 'description' field")

    @staticmethod
    def load_config(config_path: str) -> ExtractorConfig:
        """Load and validate configuration from YAML file"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            
            # Validate configuration
            ConfigLoader.validate_config(config_data)
            
            # Load defaults
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
            for name, node in config_data['nodes'].items():
                description = f"- {name}: {node['description']}"
                if node.get('format'):
                    description += f" ({node['format']})"
                node_descriptions.append(description)
                
                if 'db_column' in node:
                    db_mapping[name] = node['db_column']

            # Format prompt with node descriptions
            prompt = config_data['prompt_template'].format(
                node_descriptions='\n'.join(node_descriptions)
            )

            return ExtractorConfig(
                name=config_data['name'],
                defaults=defaults,
                prompt=prompt,
                expected_json_nodes=list(config_data['nodes'].keys()),
                db_mapping=db_mapping
            )
            
        except FileNotFoundError:
            raise ValueError(f"Configuration file not found: {config_path}")
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in configuration file: {e}")

def check_duplicate_args(argv): # Checks for duplicate named arguments and exits with an error if found.
    seen_args = set()

    for arg in argv[1:]:  # Start from index 1 to skip the script name
        if arg.startswith('--'):  # Named argument
            if arg in seen_args:
                logging.error(f"Error: Duplicate argument '{arg}' found.")
                sys.exit(1)
                seen_args.add(arg)

def parse_arguments() -> Namespace:
    parser = argparse.ArgumentParser(description="Process data with configurable constants.")

    # Configuration file
    parser.add_argument('--config', type=str, default='config.yaml', help=textwrap.dedent("""
        Path to the YAML configuration file containing extraction
        parameters (default: %(default)s).
    """))

    # Configuration from YAML file
    config_group = parser.add_argument_group("Input and output (command line overwrites values from configuration YAML file)")

    config_group.add_argument('--data_folder', type=str, help=textwrap.dedent("""
        Path to the directory containing the text files to process.
    """))

    config_group.add_argument('--chunk_size', type=int, help=textwrap.dedent("""
        Chunk size (in characters). Files exceeding this size will be
        split into chunks. The combined chunk and prompt must fit within
        the model's context window (measured in tokens, not characters).
        Token length varies by language. See the README for details.
    """))

    parser.add_argument('--results_db', type=str, help=textwrap.dedent("""
        Name of the SQLite database file to store results. If not
        specified, the project name from the YAML configuration file
        is used.
    """))

    config_group = parser.add_argument_group("AI parameters (command line overwrites values from configuration YAML file)")

    config_group.add_argument('--model', type=str, help=textwrap.dedent("""
        Name of the LLM to use for analysis (e.g., 'deepseek/deepseek-chat:floor').
    """))

    config_group.add_argument('--provider', type=str, help=textwrap.dedent("""
        Base URL of the LLM provider API (e.g., 'https://api.openrouter.ai/v1').
        Default: OpenRouter.
    """))

    parser.add_argument('--skip_key_check', action='store_true', help=textwrap.dedent("""
        Skip API key check (use for models that don't require keys, or
        set OPENROUTER_API_KEY in .env to any non-empty value).
    """))

    config_group.add_argument('--temperature', type=float, help=textwrap.dedent("""
        Temperature for model generation (0.0 to 1.0). Higher values
        increase creativity.  A value of 0 is recommended for predictable document processing.
    """))

    config_group = parser.add_argument_group("Run parameters (command line overwrites values from configuration YAML file)")
  
    parser.add_argument('--run_tag', type=str, help=textwrap.dedent("""
        Tags records in the DATA table's 'run_tag' column with a run
        label for comparison testing (allowing duplication of
        file and chunk combinations).  Use this to differentiate
        runs based on model name, field order, temperature, or other variations.
    """))
    
    config_group.add_argument('--timeout', type=int, help=textwrap.dedent("""
        Timeout (in seconds) for requests to the LLM API.
    """))

    config_group.add_argument('--max_failures', type=int, help=textwrap.dedent("""
        Maximum number of consecutive failures allowed for a chunk before it
        is skipped.
    """))

    config_group = parser.add_argument_group("Script control")

    parser.add_argument('--llm_debug_excerpt_length', type=int, default=200, help=textwrap.dedent("""
        Maximum length (in characters) of LLM response excerpts displayed
        in debug logs (default: %(default)s).
    """))

    parser.add_argument('--log_level', type=str, default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], help=textwrap.dedent("""
        Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        (default: %(default)s).
    """))

    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}", help=textwrap.dedent("""
        Show program's version number and exit.
    """))

    return parser.parse_args()

def setup_logger(log_level: str):  # Takes log level as string
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level) 

    class InfoFormatter(logging.Formatter):
        def format(self, record):
            if record.levelname == 'INFO':
                return record.getMessage()
            return super().format(record)

    handler = logging.StreamHandler()
    handler.setFormatter(InfoFormatter('%(asctime)s - %(levelname)s - %(message)s')) # removed name, there's only root here
    root_logger.addHandler(handler)

def validate_params(
    temperature: SupportsFloat,
    chunk_size: int,
    timeout: int,
    max_failures: int,
    llm_debug_excerpt_length: int,
    data_folder: str,
    model: str,
    provider: str,
    openrouter_api_key: Optional[str] = None,
    skip_key_check: bool = False,
    max_failures_limit: int = 5 # Default limit
):
    """Validates input parameters, raising an exception on the first error.
       Includes superficial API key validation.
    Raises:
        TypeError: If a parameter is of the wrong type.
        ValueError: If a parameter's value is invalid.
        FileNotFoundError: If the data folder does not exist.
        NotADirectoryError: If the provided path is not a directory.
        PermissionError: If the data folder is not readable.
        ValueError: If API key is missing and not skipped.
    """

    if not isinstance(temperature, (int, float)):
        raise TypeError(f"Temperature must be a number, got {type(temperature)}")
    if not (0 <= temperature <= 1):
        raise ValueError(f"Temperature must be between 0 and 1, got {temperature}")

    if not isinstance(chunk_size, int):
        raise TypeError(f"Context window must be an integer, got {type(chunk_size)}")
    if chunk_size <= 0:
        raise ValueError(f"Context window must be positive, got {chunk_size}")

    if not isinstance(timeout, int):
        raise TypeError(f"Timeout must be an integer, got {type(timeout)}")
    if timeout <= 0:
        raise ValueError(f"Timeout must be positive, got {timeout}")

    if not isinstance(max_failures, int):
        raise TypeError(f"Max failures must be an integer, got {type(max_failures)}")
    if max_failures < 1:
        raise ValueError(f"Max failures must be at least 1, got {max_failures}")
    if max_failures > max_failures_limit:  # Use the parameter here
        raise ValueError(f"Max failures cannot exceed {max_failures_limit}, got {max_failures}")

    if not isinstance(llm_debug_excerpt_length, int):
        raise TypeError(f"LLM debug excerpt length must be an integer, got {type(llm_debug_excerpt_length)}")
    if llm_debug_excerpt_length <= 0:
        raise ValueError(f"LLM debug excerpt length must be positive, got {llm_debug_excerpt_length}")

    if not isinstance(data_folder, str):
        raise TypeError(f"Data folder must be a string, got {type(data_folder)}")
    if not data_folder:  # Check for empty string
        raise ValueError("Data folder must be specified")
    if not os.path.exists(data_folder):
        raise FileNotFoundError(f"Data folder '{data_folder}' does not exist")
    if not os.path.isdir(data_folder):
        raise NotADirectoryError(f"'{data_folder}' is not a directory")
    if not os.access(data_folder, os.R_OK):
        raise PermissionError(f"Data folder '{data_folder}' is not readable")
    
    if not isinstance(model, str):
        raise TypeError(f"Model must be a string, got {type(model)}")
    if not model:  # Check for empty string
        raise ValueError("Model cannot be empty")

    if not isinstance(provider, str):
        raise TypeError(f"Provider must be a string, got {type(provider)}")
    if not provider:  # Check for empty string
        raise ValueError("Provider cannot be empty")

    if not openrouter_api_key and not skip_key_check:
        error_message = textwrap.dedent("""
            API key is missing. Either set the OPENROUTER_API_KEY environment variable,
            or use --skip_key_check if the model does not require an API key.
            """)
        logging.error(error_message)  # Log the error
        raise ValueError(error_message) # Raise an exception to stop execution

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

class DocumentAnalyzer:
    def __init__(self, db_path: str, query_config: ExtractorConfig):
        self.db_path = db_path
        self.query_config = query_config

class Database:
    def __init__(self, analyzer: DocumentAnalyzer, run_tag: str = None):
        self.analyzer = analyzer
        self.run_tag = run_tag
        self.connection = None


    def __enter__(self):
        self.connect()
        self.schema = self._create_schema()
        self.init_tables()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.connection:
            self.connection.close()
            self.connection = None
            
    def connect(self):
        db_path = self.analyzer.db_path

        try:
            self.connection = sqlite3.connect(db_path)
            return self.connection

        except sqlite3.OperationalError as e:
            if hasattr(e, 'sqlite_errorcode') and e.sqlite_errorcode == sqlite3.SQLITE_LOCKED:
                msg = f"The database file '{db_path}' is locked. Underlying error: {e}"
                logging.error(msg)
                raise sqlite3.OperationalError(msg)

            elif hasattr(e, 'sqlite_errorcode') and e.sqlite_errorcode == sqlite3.SQLITE_CORRUPT:
                msg = f"The file '{db_path}' is not a valid SQLite database. Underlying error: {e}"
                logging.error(msg)
                raise sqlite3.DatabaseError(msg)

            if os.path.isdir(db_path):
                msg = f"The path '{db_path}' is a directory, not a file."
                logging.error(msg)
                raise IsADirectoryError(msg)

            try:  # Check permissions on the file using os.stat
                mode = os.stat(db_path).st_mode
                if not (stat.S_IREAD & mode and stat.S_IWRITE & mode):
                    msg = f"The file '{db_path}' does not have read and write permissions."
                    logging.error(msg)
                    raise PermissionError(msg)
            except Exception as perm_e:  # Catch any exception during permission check
                msg = f"An unexpected error occurred when checking file permissions: {perm_e}"
                logging.error(msg)
                raise perm_e


            try:  # Check permissions on the *parent* directory (using os.access)
                parent_dir = os.path.dirname(db_path)
                if not os.access(parent_dir, os.W_OK):  # Check write access to parent
                    msg = f"The directory '{parent_dir}' does not have write permissions."
                    logging.error(msg)
                    raise PermissionError(msg)
            except Exception as dir_perm_e:
                msg = f"An unexpected error occurred when checking directory permissions: {dir_perm_e}"
                logging.error(msg)
                raise dir_perm_e


            # If none of the above, re-raise the original OperationalError
            msg = f"An OperationalError occurred: {e}"
            logging.error(msg)
            raise

        except sqlite3.DatabaseError as e:
            msg = f"The file '{db_path}' is not a valid SQLite database. Underlying error: {e}"
            logging.error(msg)
            raise sqlite3.DatabaseError(msg)

        except Exception as e:
            msg = f"An unexpected error occurred: {e}"
            logging.exception(msg)  # Log traceback
            raise
        
    def init_tables(self):
        cursor = self.connection.cursor()
        for table in self.schema.values():
            cursor.execute(table.get_create_statement())
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
        
        for json_node, db_column in self.analyzer.query_config.db_mapping.items():
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
                name='DATA',
                columns=results_columns
            )
        }
    
    def create_indexes(self):
        cursor = self.connection.cursor()
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_request_log_file_chunk ON REQUEST_LOG(file, chunknumber)')
            cursor.execute(f'CREATE INDEX IF NOT EXISTS idx_results_file_chunk ON {self.analyzer.query_config.results_table}(file, chunknumber, run_tag)')
            self.connection.commit()
        except sqlite3.OperationalError as e:
            logging.error(f"Error creating indexes: {e}")
            logging.warning("Continuing without indexes. Performance may be degraded.")

    def chunk_exists(self, filename: str) -> bool:
        cursor = self.connection.cursor()
        cursor.execute(
            'SELECT COUNT(*) FROM FCHUNKS WHERE file = ?',
            (filename,)
        )
        return cursor.fetchone()[0] > 0
    
    def insert_chunks(self, file: str, chunks: List[Tuple[int, int]]):
        cursor = self.connection.cursor()
        cursor.executemany(
            'INSERT INTO FCHUNKS (file, chunknumber, start, end) VALUES (?, ?, ?, ?)',
            [(file, i, chunk[0], chunk[1]) for i, chunk in enumerate(chunks)]
        )
        self.connection.commit()
    
    def get_chunk_bounds(self, filename: str, chunk_number: int) -> Optional[Tuple[int, int]]:
        cursor = self.connection.cursor()
        cursor.execute(
            'SELECT start, end FROM FCHUNKS WHERE file = ? AND chunknumber = ?',
            (filename, chunk_number)
        )
        return cursor.fetchone()
    
    def get_unprocessed_chunks(self, filename: str, results_table: str, start_iso: datetime, max_failures: int, run_tag: str = None) -> List[Tuple[str, int]]:
        try:
            cursor = self.connection.cursor()
            results_table = self.analyzer.query_config.results_table

            if run_tag is not None:
                # If run_tag is provided, check for file+chunk+run_tag duplicates and failure counts
                sql_query = f'''
                    SELECT c.file, c.chunknumber
                    FROM FCHUNKS c
                    LEFT JOIN {results_table} r
                        ON c.file = r.file AND c.chunknumber = r.chunknumber AND r.run_tag = ?
                    WHERE r.file IS NULL AND c.file = ?
                    AND NOT EXISTS (
                        SELECT 1
                        FROM REQUEST_LOG rl
                        WHERE rl.file = c.file AND rl.chunknumber = c.chunknumber AND rl.success = 0 AND rl.timestamp > ?
                        GROUP BY rl.file, rl.chunknumber
                        HAVING COUNT(*) >= ?
                    )
                '''
                cursor.execute(sql_query, (run_tag, filename, start_iso, max_failures))
            else:
                # If no run_tag, perform the original file+chunk duplicate check and failure counts
                sql_query = f'''
                    SELECT c.file, c.chunknumber
                    FROM FCHUNKS c
                    LEFT JOIN {results_table} r
                        ON c.file = r.file AND c.chunknumber = r.chunknumber
                    WHERE r.file IS NULL AND c.file = ?
                    AND NOT EXISTS (
                        SELECT 1
                        FROM REQUEST_LOG rl
                        WHERE rl.file = c.file AND rl.chunknumber = c.chunknumber AND rl.success = 0 AND rl.timestamp > ?
                        GROUP BY rl.file, rl.chunknumber
                        HAVING COUNT(*) >= ?
                    )
                '''
                cursor.execute(sql_query, (filename, start_iso, max_failures))

            return cursor.fetchall()
        except sqlite3.OperationalError as e:
            logging.exception(f"Database error: {e}")
            return []
    
    def log_request(self, file: str, chunk_number: int, 
                   model: str, result: ProcessingResult) -> int:
        cursor = self.connection.cursor()
        cursor.execute(
            'INSERT INTO REQUEST_LOG '
            '(file, chunknumber, timestamp, model, raw_response, success, error_message) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (file, chunk_number, datetime.now(timezone.utc).isoformat(), model, 
             result.raw_response, result.success, result.error_message)
        )
        self.connection.commit()
        return cursor.lastrowid
    
    def store_results(self, request_id: int, file: str, 
                     chunk_number: int, data: Dict[str, Any]):
        cursor = self.connection.cursor()
        
        columns = ['request_id', 'file', 'chunknumber']
        values = [request_id, file, chunk_number]
        
        for json_node, db_column in self.analyzer.query_config.db_mapping.items():
            if json_node in data:
                columns.append(db_column)
                values.append(data[json_node])

        # Add run_tag if it exists
        if self.run_tag is not None:
            columns.append('run_tag')
            values.append(self.run_tag)
        
        placeholders = ','.join(['?' for _ in values])
        cursor.execute(
            f'INSERT INTO {self.analyzer.query_config.results_table} '
            f'({",".join(columns)}) VALUES ({placeholders})',
            values
        )
        self.connection.commit()
    
    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def get_all_skipped_chunks_for_run(self, start_iso: datetime, end_iso: datetime, max_failures: int) -> List[Tuple[str, int]]:
        """Get all chunks that are currently in failure timeout for a specific run."""
        cursor = self.connection.cursor()

        cursor.execute('''
            SELECT file, chunknumber, COUNT(*) as failures
            FROM REQUEST_LOG
            WHERE success = 0
            AND timestamp >= ? AND timestamp <= ?
            GROUP BY file, chunknumber
            HAVING failures >= ?
            ''', (start_iso, end_iso, max_failures))

        return cursor.fetchall()

def get_llm_response(content: str, prompt: str, key: str, model: str, provider: str, temp: str, timeout: str, excerpt: int) -> Tuple[Optional[str], str]:
    global signal_received
    if signal_received:
        return None, "Request skipped due to interrupt."
    
    try:
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": content}
            ],
            "temperature": temp
        }

        response = requests.post(
            f"{provider}/chat/completions",
            headers=headers,
            json=data,
            timeout=timeout
        )

        response.raise_for_status()

        if signal_received:
            return None, "Request interrupted after response, during processing"

        logging.debug(f"Status code: {response.status_code}")
        logging.debug(f"Raw response: {response.text.strip()[:excerpt]}")

        if not response.text.strip():
            return None, ""

        response_data = response.json()

        if 'choices' not in response_data or not response_data['choices']:
            return None, json.dumps(response_data)

        choice = response_data['choices'][0]
        if 'message' not in choice or 'content' not in choice['message']:
            return None, json.dumps(response_data)

        return choice['message']['content'], json.dumps(response_data)

    except requests.exceptions.RequestException as e:
        logging.exception(f"Error making request to {provider}: {e}")
        return None, f"Request error: {e}"
    except json.JSONDecodeError as e:
        logging.exception(f"Error decoding JSON response: {e}")
        return None, f"JSON decode error: {e}"
    except KeyError as e:
        logging.exception(f"KeyError in JSON response: {e}")
        return None, f"Key error: {e}"
    except requests.exceptions.HTTPError as e:
        logging.exception(f"HTTP Error: {e}")
        return None, f"HTTP Error: {e}"
    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
        return None, f"Unexpected error: {e}"
    

def _aggressive_json_cleaning(response: str, excerpt: int) -> str:
    """Attempts aggressive ```json extraction, falling back to super-aggressive cleaning."""
    match = re.search(r"```json\s*([\s\S]*?)\s*```", response)
    if match:
        try:
            json_string = match.group(1).strip()
            json.loads(json_string)
            logging.debug("Aggressive JSON extraction from ```json block successful.")
            return json_string
        except json.JSONDecodeError as e:
            logging.debug(f"Aggressive JSON decode error: {e}. Falling back to super-aggressive cleaning. Raw response: {response[:excerpt]}")
            return _super_aggressive_json_cleaning(response, excerpt)  # Call super-aggressive
        except Exception as e:
            logging.error(f"Unexpected error during aggressive ```json extraction: {e}")
            return response
    else: # If no match for ```json block
        return _super_aggressive_json_cleaning(response, excerpt)  # Call super-aggressive

def _super_aggressive_json_cleaning(response: str, excerpt: int) -> str:
    """Attempts super-aggressive curly braces cleaning."""
    try:
        start = response.find('{')
        end = response.rfind('}')
        if start != -1 and end != -1:
            super_aggressive_cleaned_response = response[start:end + 1]
            try:
                json.loads(super_aggressive_cleaned_response)
                logging.debug("Super-aggressive JSON cleaning helped.")
                logging.debug(f"Super-aggressively cleaned response: {super_aggressive_cleaned_response[:excerpt]}...")
                return super_aggressive_cleaned_response
            except json.JSONDecodeError as e:
                logging.error(f"Super-aggressive JSON cleaning failed: {e}. Raw response: {response[:excerpt]}")
                return response
        else:
            logging.error("Could not find JSON braces in the response.")
            return response
    except Exception as e:
        logging.error(f"Unexpected error during super-aggressive cleaning: {e}")
        return response


def clean_json_response(response: str, excerpt: int) -> str:
    """Cleans the LLM response to extract JSON, using aggressive and super-aggressive cleaning as fallbacks."""

    if not response:
        return response

    # 1. Original Extraction
    cleaned_response = re.sub(r'^```json\s*', '', response.strip(), flags=re.MULTILINE)
    cleaned_response = re.sub(r'^```\s*', '', cleaned_response, flags=re.MULTILINE)
    cleaned_response = re.sub(r'\s*```$', '', cleaned_response, flags=re.MULTILINE)
    cleaned_response = cleaned_response.strip()

    try:
        json.loads(cleaned_response)
        return cleaned_response
    except json.JSONDecodeError as e:
        logging.debug(f"Initial JSON decode error: {e}. Attempting aggressive cleaning. Raw response: {response[:excerpt]}")
        return _aggressive_json_cleaning(response, excerpt)  # Call aggressive cleaning


    except Exception as e:
        logging.error(f"Unexpected error during initial cleaning: {e}")
        return response

def calculate_chunks(filename: str, chunk_size: int) -> List[Tuple[int, int]]:
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            content = file.read()
    except UnicodeDecodeError:
        logging.exception(f"File {filename} is not valid UTF-8")
        raise
    
    if not content:
        return []
    
    if len(content) <= chunk_size:
        return [(0, len(content))]  # Single chunk if it fits
    
    chunks = []
    start = 0
    
    while start < len(content):
        window = content[start:start + chunk_size]
        match = list(re.finditer(r'[\.\!\?]\s', window))
        
        if not match: 
            end = min(start + chunk_size, len(content))
        else:
            end = start + match[-1].end()
        
        chunks.append((start, end))
        start = end
    
    return chunks

def get_chunk_content(filename: str, chunk_bounds: Tuple[int, int]) -> str:
    with open(filename, 'r', encoding='utf-8') as file:
        content = file.read()
        return content[chunk_bounds[0]:chunk_bounds[1]]

def process_chunk(db: Database, filename: str, chunk_number: int, key: str, model: str, provider: str, temp: str, timeout: str, excerpt: int) -> bool:
    """Invokes LLM call function and stores results"""
    chunk_bounds = db.get_chunk_bounds(filename, chunk_number)
    if not chunk_bounds:
        return False

    content = get_chunk_content(filename, chunk_bounds)

    try:
        response, full_response = get_llm_response(
            content,
            db.analyzer.query_config.prompt,
            key=key,
            model=model,
            provider=provider,
            temp=temp,
            timeout=timeout,
            excerpt=excerpt
        )

        if response is None:
            result = ProcessingResult(
                success=False,
                raw_response=full_response,
                error_message="Empty response from model"
            )
        else:
            cleaned_response = clean_json_response(response, excerpt)
            json_response = json.loads(cleaned_response)

            missing_nodes = [
                node for node in db.analyzer.query_config.expected_json_nodes
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

        request_id = db.log_request(filename, chunk_number, model, result)

        if result.success and result.extracted_data:
            try:
                db.store_results(
                    request_id, filename, chunk_number, result.extracted_data
                )
            except sqlite3.OperationalError as e:
                logging.error(f"Error storing results: {e}. Check the DATA table schema. File: {filename}, Chunk: {chunk_number}")
                sys.exit(1) # instead of raise, as it's a standalone script and nothing will process the escalated error

        return result.success

    except Exception as e:
        result = ProcessingResult(
            success=False,
            raw_response=full_response,
            error_message=f"Error processing chunk: {str(e)}"
        )
        db.log_request(filename, chunk_number, model, result)
        return False
    
def get_current_timestamp_iso():
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()

signal_received = False  # Add this global flag to avoid failures message duplication on terminal kill

def get_run_summary(db_instance, start_iso, end_iso, max_failures):
    """Retrieves and formats the run summary details."""

    all_skipped = db_instance.get_all_skipped_chunks_for_run(start_iso, end_iso, max_failures)
    summary = ""
    if all_skipped:
        summary += "\nFinal summary of skipped chunks:\n"
        for file, chunk, failures in all_skipped:
            summary += f"- {file} chunk {chunk} ({failures} failures)\n"

    try:
        if db_instance and db_instance.connection:
            cursor = db_instance.connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM REQUEST_LOG WHERE timestamp >= ? AND timestamp <= ?", (start_iso, end_iso))
            llm_calls = cursor.fetchone()[0]

            cursor.execute(f"""SELECT COUNT(*) 
                           FROM {db_instance.analyzer.query_config.results_table}
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

def signal_handler(sig, frame, db_instance, start_iso, max_failures):
    """Handles Ctrl+C interrupt and prints a graceful message with stats."""
    global signal_received
    signal_received = True
    logging.info('\nCtrl+C detected. Gracefully exiting...')
    end_iso = get_current_timestamp_iso()

    try:
        if db_instance and db_instance.connection:
            logging.info(get_run_summary(db_instance, start_iso, end_iso, max_failures))
        else:
            logging.error("Database not initialized or connection closed.")
    except Exception as e:
        logging.exception(f"Error in signal handler: {e}")

    if db_instance and db_instance.connection:
        db_instance.close()

    sys.exit(0)
    
def main():
    global signal_received
    start_iso = get_current_timestamp_iso()

    check_duplicate_args(sys.argv)
    args = parse_arguments()
    
    setup_logger(args.log_level)
    
    config = ConfigLoader.load_config(args.config)

    # Override defaults with command line arguments if provided
    CHUNK_SIZE = args.chunk_size or config.defaults.chunk_size
    TEMPERATURE = args.temperature or config.defaults.temperature
    LLM_DEBUG_EXCERPT_LENGTH = args.llm_debug_excerpt_length
    TIMEOUT = args.timeout or config.defaults.timeout
    DATA_FOLDER = args.data_folder or config.defaults.data_folder
    RESULTS_DB = args.results_db or f"{config.name}.db"
    MAX_FAILURES = args.max_failures or config.defaults.max_failures
    MODEL = args.model or config.defaults.model
    PROVIDER = args.provider or config.defaults.provider


    logging.info("Welcome! Check README at Github for useful prompt engineering tips")
    logging.info(f"Version {VERSION} started run at UTC {start_iso}")
    if args.run_tag:
        logging.info(f"Run Tag: {args.run_tag}")
    logging.info("\nUsing configuration:")
    logging.info(f"Database: {RESULTS_DB}")
    logging.info(f"Context window: {CHUNK_SIZE}")
    logging.info(f"Temperature: {TEMPERATURE}")
    logging.info(f"LLM Excerpt Length: {LLM_DEBUG_EXCERPT_LENGTH}")
    logging.info(f"Timeout: {TIMEOUT}")
    logging.info(f"Data folder: {DATA_FOLDER}")
    logging.info(f"Max failures: {MAX_FAILURES}")
    logging.info(f"Model: {MODEL}\n\nPress Ctrl-C to stop the run (you can continue later)\n")# Load environment variables

    load_dotenv()
    OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')

    validate_params(
        temperature=TEMPERATURE,
        chunk_size=CHUNK_SIZE,
        timeout=TIMEOUT,
        max_failures=MAX_FAILURES,
        llm_debug_excerpt_length=LLM_DEBUG_EXCERPT_LENGTH,
        data_folder=DATA_FOLDER,
        model=MODEL,
        provider=PROVIDER,
        openrouter_api_key=OPENROUTER_API_KEY,
        skip_key_check=args.skip_key_check
    )         

    analyzer = DocumentAnalyzer(
        RESULTS_DB,
        ExtractorConfig(
            name=config.name,
            prompt=config.prompt,
            defaults=config.defaults,
            expected_json_nodes=config.expected_json_nodes,
            db_mapping=config.db_mapping,
            results_table=config.results_table
        )
    )

    with Database(analyzer, args.run_tag) as db:
        db.create_indexes() # Create indexes after connecting to the database.
        signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, db, start_iso, MAX_FAILURES))
        
        try:
            while True:
                files = [f for f in os.listdir(DATA_FOLDER)
                        if os.path.isfile(os.path.join(DATA_FOLDER, f))]

                unprocessed = []
                for file in files:
                    full_path = os.path.join(DATA_FOLDER, file)

                    if not db.chunk_exists(full_path):
                        chunks = calculate_chunks(full_path, CHUNK_SIZE)
                        db.insert_chunks(full_path, chunks)

                    chunks = db.get_unprocessed_chunks(
                        full_path, 
                        analyzer.query_config.results_table, 
                        start_iso, 
                        MAX_FAILURES, 
                        args.run_tag
                    )
                    unprocessed.extend(chunks)

                if not unprocessed:
                    logging.info("\nAll chunks processed or skipped!")
                    break

                file, chunk_number = random.choice(unprocessed)
                logging.info(f"Processing {file} chunk {chunk_number}")

                process_chunk(
                    db=db,
                    filename=file,
                    chunk_number=chunk_number,
                    key=OPENROUTER_API_KEY,
                    model=MODEL,
                    provider=PROVIDER,
                    temp=TEMPERATURE,
                    timeout=TIMEOUT,
                    excerpt=LLM_DEBUG_EXCERPT_LENGTH,
                )

                if signal_received:
                    logging.info("Loop interrupted by user.")
                    break

        finally:
            end_iso = get_current_timestamp_iso()
            if not signal_received:
                logging.info(get_run_summary(db, start_iso, end_iso, MAX_FAILURES))

if __name__ == "__main__":
    main()