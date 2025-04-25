# gar_tool/database_handler.py

# --- Imports needed for Database, Column, Table ---
import sqlite3
import os, sys, stat # Keep sys if critical_exit is used within DB class methods
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple, Callable

# --- Imports needed from other modules in your package ---
from .logging_wrapper import logger
from .config_handler import ExtractorConfig
from .processing_result import ProcessingResult

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

        # Create a list of columns from your schema
        results_columns_names = self.schema['RESULTS'].get_column_names()

        for col_name in results_columns_names: # Iterate directly through column names from schema.
          if col_name in ('request_id', 'file', 'chunknumber', 'run_tag'):
            continue # Skip these columns, they were already added before the loop.
          
          json_node = next((k for k, v in self.config.db_mapping.items() if v == col_name), None)
          if json_node is None:
            logger.error(f"Column '{col_name}' not found in the db_mapping. This could be a problem in the YAML configuration file. Skipping.")
            continue # Skip the column

          value_to_append = data.get(json_node) # Retrieve value for optional nodes
          columns.append(col_name)
          values.append(value_to_append)

        # Add run_tag if it exists and required
        if self.config.run_tag is not None:
            columns.append('run_tag')
            values.append(self.config.run_tag)

        placeholders = ','.join(['?' for _ in values])
        query = f'INSERT INTO {self.config.results_table} ({",".join(columns)}) VALUES ({placeholders})'

        if not self._execute_query(cursor, query, values):  # Use the wrapper
            logger.exception(f"Error storing results into the database file: {e}. Check the {self.config.results_table} table schema. File: {file}, Chunk: {chunk_number}")
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