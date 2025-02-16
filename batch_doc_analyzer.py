import sqlite3
import os
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

@dataclass
class ExtractorDefaults:
    context_window: int
    temperature: float
    debug_sample_length: int
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
    def load_config(config_path: str) -> ExtractorConfig:
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)

        # Load defaults
        defaults = ExtractorDefaults(
            context_window=config_data['defaults']['context_window'],
            temperature=config_data['defaults']['temperature'],
            debug_sample_length=config_data['defaults']['debug_sample_length'],
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

        # Create config object
        return ExtractorConfig(
            name=config_data['name'],
            defaults=defaults,
            prompt=prompt,
            expected_json_nodes=list(config_data['nodes'].keys()),
            db_mapping=db_mapping
        )
# to overwrite constants
parser = argparse.ArgumentParser(description="Process data with configurable constants.")

parser.add_argument('--context_window', type=int, help="Context window size - longer file will be cut to chunks.")
parser.add_argument('--temperature', type=float, help="Temperature for model generation - 0.6 is recommended by DeepSeek, higher means more creativity.")
parser.add_argument('--debug_sample_length', type=int, help="Length of model response in console for debug.")
parser.add_argument('--timeout', type=int, help="Timeout for requests to llm.")
parser.add_argument('--data_folder', type=str, help="Path to the data folder, no trailing slash.")
parser.add_argument('--results_db', type=str, help="Name of sqlite file with results.")
parser.add_argument('--config', type=str, default='config.yaml', help="Name of the file with extractor configuration in YAML format.")
parser.add_argument('--max_failures', type=str, help="Maximum failures for a chunk in this run before it skipped.")
parser.add_argument('--model', type=str, help="Model name to use for analysis.")
parser.add_argument('--provider', type=str, help="Base URL for LLM provider, openrouter by default.")

args = parser.parse_args()

# Load config
config = ConfigLoader.load_config(args.config)

    # Override defaults with command line arguments if provided
CONTEXT_WINDOW = args.context_window or config.defaults.context_window
TEMPERATURE = args.temperature or config.defaults.temperature
DEBUG_SAMPLE_LENGTH = args.debug_sample_length or config.defaults.debug_sample_length
TIMEOUT = args.timeout or config.defaults.timeout
DATA_FOLDER = args.data_folder or config.defaults.data_folder
RESULTS_DB = args.results_db or f"{config.name}.db"
MAX_FAILURES = args.max_failures or config.defaults.max_failures
MODEL = args.model or config.defaults.model
PROVIDER = args.provider or config.defaults.provider

# Load environment variables
load_dotenv()

# Get environment variables
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')


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
        self.schema = self._create_schema()
        
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
        ]
        
        for json_node, db_column in self.query_config.db_mapping.items():
            results_columns.append(Column(db_column, 'TEXT'))
        
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

class Database:
    def __init__(self, analyzer: DocumentAnalyzer):
        self.analyzer = analyzer
        self.connection = None
        
    def connect(self):
        self.connection = sqlite3.connect(self.analyzer.db_path)
        return self.connection
        
    def init_tables(self):
        cursor = self.connection.cursor()
        for table in self.analyzer.schema.values():
            cursor.execute(table.get_create_statement())
        self.connection.commit()
    
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
    
    def get_unprocessed_chunks(self, filename: str, results_table: str) -> List[Tuple[str, int]]:
        try:
            cursor = self.connection.cursor()
            results_table = self.analyzer.query_config.results_table
            sql_query = f'''
                SELECT c.file, c.chunknumber 
                FROM FCHUNKS c 
                LEFT JOIN {results_table} r 
                    ON c.file = r.file AND c.chunknumber = r.chunknumber
                WHERE r.file IS NULL AND c.file = ?
            '''
            cursor.execute(sql_query, (filename,))
            return cursor.fetchall()
        except sqlite3.OperationalError as e:
            print(f"Database error: {e}")
            print("Make sure the database and tables are properly initialized")
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

    def get_recent_failures(self, filename: str, chunk_number: int, 
                        window_start_iso: datetime, max_failures: int) -> bool:
        """
        Check if chunk has had too many failures in recent time window
        Returns True if chunk should be skipped
        """
        cursor = self.connection.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) 
            FROM REQUEST_LOG 
            WHERE file = ? 
            AND chunknumber = ? 
            AND success = 0
            AND timestamp > ?
            ''', (filename, chunk_number, window_start_iso))
        
        failure_count = cursor.fetchone()[0]
        #print(f"Skip count for chunk {chunk_number} of {filename}: {failure_count}")
        return failure_count >= max_failures

    def get_all_skipped_chunks(self, window_start_iso: datetime, max_failures: int) -> List[Tuple[str, int]]:
        """Get all chunks that are currently in failure timeout"""
        cursor = self.connection.cursor()
        
        cursor.execute('''
            SELECT file, chunknumber, COUNT(*) as failures
            FROM REQUEST_LOG 
            WHERE success = 0 
            AND timestamp > ?
            GROUP BY file, chunknumber
            HAVING failures >= ?
            ''', (window_start_iso, max_failures))
        
        return cursor.fetchall()

def get_llm_response(content: str, prompt: str) -> Tuple[Optional[str], str]:
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
        
        print(f"Status code: {response.status_code}")
        print(f"Raw response: {response.text.strip()[:DEBUG_SAMPLE_LENGTH]}")
        
        response.raise_for_status()
        
        if not response.text.strip():
            print("Empty response received from API")
            return None, ""
            
        response_data = response.json()
        
        if 'choices' not in response_data or not response_data['choices']:
            print("No choices in response")
            return None, json.dumps(response_data)
            
        choice = response_data['choices'][0]
        if 'message' not in choice or 'content' not in choice['message']:
            print("No message content in response")
            return None, json.dumps(response_data)
            
        return choice['message']['content'], json.dumps(response_data)
        
    except Exception as e:
        print(f"API request failed: {str(e)}")
        return None, str(e)

def clean_json_response(response: str) -> str:
    if not response:
        return response
        
    response = re.sub(r'^```json\s*', '', response.strip())
    response = re.sub(r'^```\s*', '', response.strip())
    response = re.sub(r'\s*```$', '', response.strip())
    
    return response.strip()

def calculate_chunks(filename: str) -> List[Tuple[int, int]]:
    with open(filename, 'r', encoding='utf-8') as file:
        content = file.read()
    
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
            db.store_results(
                request_id, filename, chunk_number, result.extracted_data
            )
        
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

def main():

    iso_timestamp = get_current_timestamp_iso()

    print(f"Start run at UTC {iso_timestamp}")
    print("Using configuration:")
    print(f"Database: {RESULTS_DB}")
    print(f"Context window: {CONTEXT_WINDOW}")
    print(f"Temperature: {TEMPERATURE}")
    print(f"Debug sample length: {DEBUG_SAMPLE_LENGTH}")
    print(f"Timeout: {TIMEOUT}")
    print(f"Data folder: {DATA_FOLDER}")
    print(f"Max failures: {MAX_FAILURES}")
    print(f"Model: {MODEL}")

    # Your script's logic here, using the configured constants...
    if os.path.exists(DATA_FOLDER):
        print("Data folder exists")
    else:
        print("Data folder does not exist")
    
    analyzer = DocumentAnalyzer(RESULTS_DB,
                            ExtractorConfig(
                                name=config.name,
                                prompt=config.prompt,
                                defaults=config.defaults,
                                expected_json_nodes=config.expected_json_nodes,
                                db_mapping=config.db_mapping,
                                results_table=config.results_table
                            ))

    db = Database(analyzer)
    db.connect()  # Make sure this is called
    db.init_tables()  # Make sure this is called to create all necessary tables


    skipped_chunks = set()
    
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
                    
                    chunks = db.get_unprocessed_chunks(full_path, analyzer.query_config.results_table)
                    for chunk in chunks:
                        if not db.get_recent_failures(chunk[0], chunk[1], 
                                                    iso_timestamp, MAX_FAILURES):
                            unprocessed.append(chunk)
                        else:
                            skipped_chunks.add((chunk[0], chunk[1]))
                
                if not unprocessed:
                    if skipped_chunks:
                        print("\nSkipped chunks due to excessive failures:")
                        for file, chunk in sorted(skipped_chunks):
                            print(f"- {file} chunk {chunk}")
                    print("\nAll chunks processed or skipped!")
                    break
                
                file, chunk_number = random.choice(unprocessed)
                print(f"Processing {file} chunk {chunk_number}")
                process_chunk(db, file, chunk_number)
        
    finally:
        # Print final summary
        all_skipped = db.get_all_skipped_chunks(iso_timestamp, MAX_FAILURES)
        if all_skipped:
            print("\nFinal summary of skipped chunks:")
            for file, chunk, failures in all_skipped:
                print(f"- {file} chunk {chunk} ({failures} failures)")
            
        db.close()


if __name__ == "__main__":
    main()