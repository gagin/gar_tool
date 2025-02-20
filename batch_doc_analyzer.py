import sqlite3
import os
import signal
import sys
import yaml
import argparse
import json
import random
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
from dotenv import load_dotenv
import requests
import requests.exceptions
import threading
import time
import logging

VERSION = '0.1.7' # requires major.minor.patch notation for auto-increment on commits via make command

@dataclass
class ExtractorDefaults:
    context_window: int
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
            
        # Validate specific default values
        if not (0 <= defaults.get('temperature', 0) <= 1):
            raise ValueError("Temperature must be between 0 and 1")
        if defaults.get('context_window', 0) <= 0:
            raise ValueError("Context window must be positive")
        if defaults.get('timeout', 0) <= 0:
            raise ValueError("Timeout must be positive")
        if not defaults.get('data_folder'):
            raise ValueError("Data folder must be specified")
        if defaults.get('max_failures', 0) < 0:
            raise ValueError("Max failures must be non-negative")
            
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
                context_window=config_data['defaults']['context_window'],
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
                sys.exit(1)  # Exit with an error code
            else:
                seen_args.add(arg)

check_duplicate_args(sys.argv)
parser = argparse.ArgumentParser(description="Process data with configurable constants.")

parser.add_argument('--context_window', type=int, help="Context window size (in tokens). Files exceeding this size will be split into chunks.")
parser.add_argument('--temperature', type=float, help="Temperature for model generation (0.0 to 1.0). Higher values increase creativity. Defaults to 0 for predictable categorization. DeepSeek recommends 0.6 for more creative tasks.")
parser.add_argument('--llm_debug_excerpt_length', type=int, default=200, help="Maximum length (characters) of LLM response excerpt displayed in debug logs (default: %(default)s).")
parser.add_argument('--timeout', type=int, help="Timeout (in seconds) for requests to the LLM API.")
parser.add_argument('--data_folder', type=str, help="Path to the directory containing the text files to process.")
parser.add_argument('--results_db', type=str, help="Name of the SQLite database file to store results. If not specified, the project name from config.yaml is used.")
parser.add_argument('--config', type=str, default='config.yaml', help="Path to the YAML configuration file containing extraction parameters (default: %(default)s).")
parser.add_argument('--max_failures', type=int, help="Maximum number of failures allowed for a chunk before it is skipped.")
parser.add_argument('--model', type=str, help="Name of the LLM to use for analysis (e.g., 'deepseek/deepseek-chat:floor').")
parser.add_argument('--provider', type=str, help="Base URL of the LLM provider API (e.g., 'https://api.openrouter.ai/v1'). Defaults to OpenRouter.")
parser.add_argument('--run_tag', type=str, help="Tags records in the DATA table's 'run_tag' column with a run label for comparison testing (allows duplication of file+chunk).")
parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
parser.add_argument(
    '--log_level',
    type=str,
    default='INFO',  # Default is INFO
    choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],  # Valid choices
    help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) (default: %(default)s)."
)
parser.add_argument(
    '--skip_key_check',
    action='store_true',
    help="Skip API key check (use for models that don't require keys, alternatively you can set OPENROUTER_API_KEY in .env to any non-empty value)."
)

args = parser.parse_args()

# Configure logging based on the command-line argument
log_level = getattr(logging, args.log_level.upper())

# Get the root logger
root_logger = logging.getLogger()
root_logger.setLevel(log_level) 

class InfoFormatter(logging.Formatter):
    def format(self, record):
        if record.levelname == 'INFO':
            return record.getMessage()
        return super().format(record)

handler = logging.StreamHandler()
handler.setFormatter(InfoFormatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
root_logger.addHandler(handler)


config = ConfigLoader.load_config(args.config)

# Override defaults with command line arguments if provided
CONTEXT_WINDOW = args.context_window or config.defaults.context_window
TEMPERATURE = args.temperature or config.defaults.temperature
LLM_DEBUG_EXCERPT_LENGTH = args.llm_debug_excerpt_length
TIMEOUT = args.timeout or config.defaults.timeout
DATA_FOLDER = args.data_folder or config.defaults.data_folder
RESULTS_DB = args.results_db or f"{config.name}.db"
MAX_FAILURES = args.max_failures or config.defaults.max_failures
MODEL = args.model or config.defaults.model
PROVIDER = args.provider or config.defaults.provider

def validate_config():
    if TEMPERATURE < 0 or TEMPERATURE > 1:
        raise ValueError(f"Temperature must be between 0 and 1, got {TEMPERATURE}")
    if CONTEXT_WINDOW <= 0:
        raise ValueError(f"Context window must be positive, got {CONTEXT_WINDOW}")
    if TIMEOUT <= 0:
        raise ValueError(f"Timeout must be positive, got {TIMEOUT}")
    if MAX_FAILURES < 1:
        raise ValueError("Max failures must be positive number")
    if MAX_FAILURES > 10:
        raise ValueError("Doesn't make sense to allow more than 10 failures, edit script if you are certain")
    
# Load environment variables
load_dotenv()

# Get environment variables
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')

if not OPENROUTER_API_KEY and not args.skip_key_check:
    error_message = (
        "API key is missing. Either set the OPENROUTER_API_KEY environment variable, "
        "or use --skip_key_check if the model does not require an API key."
    )
    logging.error(error_message)
    sys.exit(1)  # Or handle differently

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
        self.schema = self._create_schema() #Create schema here.

    def __enter__(self):
        self.connect()
        self.init_tables()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.connection:
            self.connection.close()
            self.connection = None
            
    def connect(self):
        self.connection = sqlite3.connect(self.analyzer.db_path)
        return self.connection
        
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
            self.connect() #connect so cursor can be created.
            
        #cursor = self.connection.cursor()
        #cursor.execute('CREATE INDEX IF NOT EXISTS idx_request_log_file_chunk ON REQUEST_LOG(file, chunknumber)')
        #cursor.execute('CREATE INDEX IF NOT EXISTS idx_results_file_chunk ON DATA(file, chunknumber)')
        
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

def get_llm_response(content: str, prompt: str) -> Tuple[Optional[str], str]:
    global signal_received
    if signal_received:
        return None, "Request skipped due to interrupt."
    
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }

        data = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": content}
            ],
            "temperature": TEMPERATURE
        }

        response = requests.post(
            f"{PROVIDER}/chat/completions",
            headers=headers,
            json=data,
            timeout=TIMEOUT
        )

        response.raise_for_status()

        if signal_received:
            return None, "Request interrupted after response, during processing"

        logging.debug(f"Status code: {response.status_code}")
        logging.debug(f"Raw response: {response.text.strip()[:LLM_DEBUG_EXCERPT_LENGTH]}")

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
        logging.exception(f"Error making request to {PROVIDER}: {e}")
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
    
def clean_json_response(response: str) -> str:
    """Trims JSON response from the model"""
    if not response:
        return response
        
    response = re.sub(r'^```json\s*', '', response.strip())
    response = re.sub(r'^```\s*', '', response.strip())
    response = re.sub(r'\s*```$', '', response.strip())
    
    return response.strip()

def calculate_chunks(filename: str) -> List[Tuple[int, int]]:
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            content = file.read()
    except UnicodeDecodeError:
        logging.exception(f"File {filename} is not valid UTF-8")
        raise
    
    if not content:
        return []
    
    if len(content) <= CONTEXT_WINDOW:
        return [(0, len(content))]  # Single chunk if it fits
    
    chunks = []
    start = 0
    
    while start < len(content):
        window = content[start:start + CONTEXT_WINDOW]
        match = list(re.finditer(r'[\.\!\?]\s', window))
        
        if not match: 
            end = min(start + CONTEXT_WINDOW, len(content))
        else:
            end = start + match[-1].end()
        
        chunks.append((start, end))
        start = end
    
    return chunks

def get_chunk_content(filename: str, chunk_bounds: Tuple[int, int]) -> str:
    with open(filename, 'r', encoding='utf-8') as file:
        content = file.read()
        return content[chunk_bounds[0]:chunk_bounds[1]]

def process_chunk(db: Database, filename: str, chunk_number: int) -> bool:
    """Invokes LLM call function and stores results"""
    chunk_bounds = db.get_chunk_bounds(filename, chunk_number)
    if not chunk_bounds:
        return False

    content = get_chunk_content(filename, chunk_bounds)

    try:
        response, full_response = get_llm_response(
            content,
            db.analyzer.query_config.prompt
        )

        if response is None:
            result = ProcessingResult(
                success=False,
                raw_response=full_response,
                error_message="Empty response from model"
            )
        else:
            cleaned_response = clean_json_response(response)
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

        request_id = db.log_request(filename, chunk_number, MODEL, result)

        if result.success and result.extracted_data:
            try:
                db.store_results(
                    request_id, filename, chunk_number, result.extracted_data
                )
            except sqlite3.OperationalError as e:
                logging.error(f"Error storing results: {e}. Check the DATA table schema. File: {filename}, Chunk: {chunk_number}")
                raise  # Or sys.exit(1) to terminate

        return result.success

    except Exception as e:
        result = ProcessingResult(
            success=False,
            raw_response=full_response,
            error_message=f"Error processing chunk: {str(e)}"
        )
        db.log_request(filename, chunk_number, MODEL, result)
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
            summary += f"- {file} chunk {chunk} ({failures} failures)\n" #corrected here

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

def signal_handler(sig, frame, db_instance, start_iso):
    """Handles Ctrl+C interrupt and prints a graceful message with stats."""
    global signal_received
    signal_received = True
    logging.info('\nCtrl+C detected. Gracefully exiting...')
    end_iso = get_current_timestamp_iso()

    try:
        if db_instance and db_instance.connection:
            logging.info(get_run_summary(db_instance, start_iso, end_iso, MAX_FAILURES))
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

    logging.info("Welcome! Check README at Github for useful prompt engineering tips")
    logging.info(f"Start run at UTC {start_iso}")
    logging.info("Using configuration:")
    logging.info(f"Database: {RESULTS_DB}")
    logging.info(f"Context window: {CONTEXT_WINDOW}")
    logging.info(f"Temperature: {TEMPERATURE}")
    logging.info(f"LLM Excerpt Length: {LLM_DEBUG_EXCERPT_LENGTH}")
    logging.info(f"Timeout: {TIMEOUT}")
    logging.info(f"Data folder: {DATA_FOLDER}")
    logging.info(f"Max failures: {MAX_FAILURES}")
    logging.info(f"Model: {MODEL}")

    if not os.path.exists(DATA_FOLDER):
        logging.error("Data folder does not exist")
        return

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
        signal.signal(signal.SIGINT, lambda sig, frame: signal_handler(sig, frame, db, start_iso))
        
        try:
            while True:
                files = [f for f in os.listdir(DATA_FOLDER)
                        if os.path.isfile(os.path.join(DATA_FOLDER, f))]

                unprocessed = []
                for file in files:
                    full_path = os.path.join(DATA_FOLDER, file)

                    if not db.chunk_exists(full_path):
                        chunks = calculate_chunks(full_path)
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

                process_chunk(db, file, chunk_number)

                if signal_received:
                    logging.info("Loop interrupted by user.")
                    break

        finally:
            end_iso = get_current_timestamp_iso()
            if not signal_received:
                logging.info(get_run_summary(db, start_iso, end_iso, MAX_FAILURES))

if __name__ == "__main__":
    main()