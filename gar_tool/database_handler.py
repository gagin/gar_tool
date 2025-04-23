import sqlite3
import os
import stat
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple, Callable

from .config_handler import ExtractorConfig
from .analyzer import ProcessingResult # Use relative import
from .logging_wrapper import logger

# Define isolation level for connections
# Using DEFERRED (default) is usually fine for single-process access
# If using threads/multiple processes later, might need IMMEDIATE or EXCLUSIVE
DB_ISOLATION_LEVEL = None # Use SQLite's default
DB_TIMEOUT_MS = 5000 # Default busy timeout


@dataclass
class Column:
    """Represents a database column definition."""
    name: str
    type: str
    primary_key: bool = False
    nullable: bool = True
    default: Optional[str] = None


@dataclass
class Table:
    """Represents a database table definition."""
    name: str
    columns: List[Column]

    def get_create_statement(self) -> str:
        """Generates the SQL CREATE TABLE statement."""
        cols = []
        pk_cols = []

        for col in self.columns:
            col_def = f'"{col.name}" {col.type}' # Quote column names
            if not col.primary_key and not col.nullable:
                col_def += " NOT NULL"
            if col.default is not None:
                 # Correctly quote default string values
                 default_val = f"'{col.default}'" if isinstance(col.default, str) else col.default
                 col_def += f" DEFAULT {default_val}"
            if col.primary_key:
                pk_cols.append(f'"{col.name}"') # Quote PK column names
            cols.append(col_def)

        if pk_cols:
            cols.append(f"PRIMARY KEY ({', '.join(pk_cols)})")

        # Use IF NOT EXISTS for safety
        return f'CREATE TABLE IF NOT EXISTS "{self.name}" ({", ".join(cols)})'

    def get_column_names(self) -> List[str]:
        """Returns a list of column names for the table."""
        return [col.name for col in self.columns]


class Database:
    """Handles all interactions with the SQLite database."""

    def __init__(self, config: ExtractorConfig):
        self.config = config
        self.connection: Optional[sqlite3.Connection] = None
        self.schema: Optional[Dict[str, Table]] = None

    def __enter__(self):
        """Establishes connection and initializes the database on entering context."""
        if self.connect():
            self.schema = self._define_schema()
            self.init_tables()
            self.create_indexes()
            return self
        else:
            # Connection failed, raise an exception to prevent use
            raise RuntimeError("Failed to connect to the database.")

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Closes the database connection on exiting context."""
        self.close()

    def connect(self) -> bool:
        """Establishes the database connection."""
        db_path = self.config.results_db
        if not db_path:
             logger.critical_exit("Database path is not configured.")
             return False # Should be unreachable

        try:
            self.connection = sqlite3.connect(
                db_path,
                isolation_level=DB_ISOLATION_LEVEL,
                timeout=DB_TIMEOUT_MS / 1000.0 # Convert ms to seconds for connect
            )
            self.connection.execute(f"PRAGMA busy_timeout = {DB_TIMEOUT_MS}")
            # Basic integrity check on connect
            cursor = self.connection.cursor()
            cursor.execute("PRAGMA integrity_check;")
            result = cursor.fetchone()
            if result is None or result[0].lower() != 'ok':
                 logger.critical_exit(f"Database integrity check failed for '{db_path}': {result[0] if result else 'Unknown error'}")
                 self.connection.close()
                 self.connection = None
                 return False
            logger.debug(f"Successfully connected to database: {db_path}")
            return True

        except sqlite3.OperationalError as e:
            logger.critical_exit(f"Failed to connect to database '{db_path}': {e}", exc_info=True)
            self.connection = None
            return False
        except Exception as e:
            logger.critical_exit(f"Unexpected error connecting to database '{db_path}': {e}", exc_info=True)
            self.connection = None
            return False


    def _execute_query(self, query: str, params: Any = None) -> Optional[sqlite3.Cursor]:
        """Executes a single SQL query, handling common errors."""
        if not self.connection:
            logger.error("Database not connected. Cannot execute query.")
            return None
        try:
            cursor = self.connection.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor
        except sqlite3.IntegrityError as e:
             logger.error(f"Database Integrity Error: {e}. Query: {query[:100]}...")
             # Often duplicate primary keys, log and potentially continue? Or rollback?
             self.connection.rollback() # Rollback on integrity error
             return None
        except sqlite3.OperationalError as e:
            logger.error(f"Database Operational Error: {e}. Query: {query[:100]}...")
            # Could be locked, table missing etc. Maybe rollback is safer?
            try:
                self.connection.rollback()
            except sqlite3.Error as rb_e:
                logger.error(f"Rollback failed after operational error: {rb_e}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error executing query: {query[:100]}...")
            try:
                self.connection.rollback()
            except sqlite3.Error as rb_e:
                logger.error(f"Rollback failed after unexpected error: {rb_e}")
            return None

    def _execute_many(self, query: str, params: List[Any]) -> bool:
        """Executes a SQL query for multiple sets of parameters."""
        if not self.connection:
            logger.error("Database not connected. Cannot execute many.")
            return False
        try:
            cursor = self.connection.cursor()
            cursor.executemany(query, params)
            # Commit is usually handled separately after a logical unit of work
            # self.connection.commit() # Removed auto-commit here
            return True
        except sqlite3.IntegrityError as e:
             logger.error(f"Database Integrity Error during executemany: {e}. Query: {query[:100]}...")
             self.connection.rollback()
             return False
        except sqlite3.OperationalError as e:
            logger.error(f"Database Operational Error during executemany: {e}. Query: {query[:100]}...")
            try:
                 self.connection.rollback()
            except sqlite3.Error as rb_e:
                 logger.error(f"Rollback failed after operational error: {rb_e}")
            return False
        except Exception as e:
            logger.exception(f"Unexpected error during executemany: {query[:100]}...")
            try:
                 self.connection.rollback()
            except sqlite3.Error as rb_e:
                 logger.error(f"Rollback failed after unexpected error: {rb_e}")
            return False


    def init_tables(self):
        """Creates database tables based on the schema if they don't exist."""
        if not self.schema:
            logger.error("Schema not defined. Cannot initialize tables.")
            return
        logger.debug("Initializing database tables...")
        for table in self.schema.values():
            create_sql = table.get_create_statement()
            logger.debug(f"Executing: {create_sql}")
            if self._execute_query(create_sql) is None:
                logger.critical_exit(f"Failed to create table {table.name}. See error above.")
                return # Should be unreachable
        self.connection.commit() # Commit after creating all tables
        logger.debug("Table initialization complete.")


    def _define_schema(self) -> Dict[str, Table]:
        """Defines the database schema structure."""
        request_log_columns = [
            Column('id', 'INTEGER', primary_key=True),
            Column('file', 'TEXT', nullable=False),
            Column('chunknumber', 'INTEGER', nullable=False),
            Column('timestamp', 'TEXT', nullable=False), # Store ISO strings
            Column('model', 'TEXT', nullable=False),
            Column('raw_response', 'TEXT'),
            Column('success', 'INTEGER', nullable=False), # Use INTEGER for bool
            Column('error_message', 'TEXT'),
        ]

        results_columns = [
            Column('request_id', 'INTEGER', primary_key=True),
            Column('file', 'TEXT', nullable=False),
            Column('chunknumber', 'INTEGER', nullable=False),
            Column('run_tag', 'TEXT', nullable=True)
        ]

        # Dynamically add columns based on config's db_mapping
        for db_column in self.config.db_mapping.values():
            # Ensure no duplicates with base columns
            if db_column not in [c.name for c in results_columns]:
                 # Assume TEXT type for simplicity, could refine based on node 'format' if needed
                 results_columns.append(Column(db_column, 'TEXT', nullable=True))

        # Define table for file chunk boundaries
        fchunks_columns = [
            Column('file', 'TEXT', nullable=False),
            Column('chunknumber', 'INTEGER', nullable=False),
            Column('start', 'INTEGER', nullable=False),
            Column('end', 'INTEGER', nullable=False),
            # Add PRIMARY KEY constraint here
        ]

        return {
            'FCHUNKS': Table(
                name='FCHUNKS',
                columns=fchunks_columns + [Column('', '', primary_key=True)] # Placeholder for PK def
            ),
            'REQUEST_LOG': Table(
                name='REQUEST_LOG',
                columns=request_log_columns
            ),
            self.config.results_table: Table(
                name=self.config.results_table,
                columns=results_columns
            )
        }


    def create_indexes(self):
        """Creates indexes for faster queries."""
        if not self.connection: return
        logger.debug("Creating database indexes...")
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_fchunks_file ON FCHUNKS(file)",
            "CREATE INDEX IF NOT EXISTS idx_request_log_file_chunk ON REQUEST_LOG(file, chunknumber)",
            f"CREATE INDEX IF NOT EXISTS idx_results_file_chunk_tag ON \"{self.config.results_table}\"(file, chunknumber, run_tag)"
        ]
        for index_sql in indexes:
            logger.debug(f"Executing: {index_sql}")
            if self._execute_query(index_sql) is None:
                logger.warning(f"Failed to create index using: {index_sql}")
        self.connection.commit() # Commit after creating indexes
        logger.debug("Index creation complete.")


    def chunk_exists(self, filename: str) -> bool:
        """Checks if any chunk boundaries are stored for the given filename."""
        query = "SELECT 1 FROM FCHUNKS WHERE file = ? LIMIT 1"
        cursor = self._execute_query(query, (filename,))
        return cursor is not None and cursor.fetchone() is not None

    def insert_chunks(self, file: str, chunks: List[Tuple[int, int]]):
        """Inserts chunk boundaries for a file."""
        logger.debug(f"Inserting {len(chunks)} chunk boundaries for {file}...")
        query = 'INSERT INTO FCHUNKS (file, chunknumber, start, end) VALUES (?, ?, ?, ?)'
        params = [(file, i, chunk[0], chunk[1]) for i, chunk in enumerate(chunks)]

        if not self._execute_many(query, params):
             logger.error(f"Failed to insert chunks for file {file}")
             # Rollback might have happened in _execute_many
        else:
             self.connection.commit() # Commit successful chunk insertions


    def get_chunk_bounds(self, filename: str, chunk_number: int) -> Optional[Tuple[int, int]]:
        """Retrieves the start and end boundaries for a specific chunk."""
        query = 'SELECT start, end FROM FCHUNKS WHERE file = ? AND chunknumber = ?'
        cursor = self._execute_query(query, (filename, chunk_number))
        if cursor:
            result = cursor.fetchone()
            return result if result else None
        return None


    def get_unprocessed_chunks(self, filename: str, start_iso: str) -> List[Tuple[str, int]]:
        """
        Finds chunk numbers for a SPECIFIC file that need processing in this run.
        Considers RESULTS table misses and REQUEST_LOG failure counts.
        """
        results_table = self.config.results_table
        run_tag = self.config.run_tag
        max_failures = self.config.inconfig_values.max_failures

        # Query construction needs careful handling of run_tag being None
        run_tag_filter_results = f'AND r.run_tag = ?' if run_tag else 'AND r.run_tag IS NULL' if run_tag is None else '' # Handle potential None for run_tag

        # This query checks FCHUNKS for the given file...
        # ... for chunks NOT present in the RESULTS table (matching run_tag)...
        # ... AND ALSO not having excessive failures in REQUEST_LOG since the run started.
        sql_query = f'''
            SELECT c.file, c.chunknumber
            FROM FCHUNKS c
            WHERE c.file = ?
            AND NOT EXISTS (
                SELECT 1
                FROM "{results_table}" r
                WHERE r.file = c.file
                  AND r.chunknumber = c.chunknumber
                  {run_tag_filter_results}
            )
            AND NOT EXISTS (
                SELECT 1
                FROM REQUEST_LOG rl
                WHERE rl.file = c.file
                  AND rl.chunknumber = c.chunknumber
                  AND rl.success = 0
                  AND rl.timestamp >= ? -- Only count failures since this run started
                GROUP BY rl.file, rl.chunknumber
                HAVING COUNT(*) >= ?
            )
            ORDER BY c.chunknumber -- Process chunks sequentially for a file
        '''

        params = [filename]
        if run_tag is not None: # Add parameter only if run_tag is used in query
             params.append(run_tag)
        params.extend([start_iso, max_failures])

        cursor = self._execute_query(sql_query, tuple(params))
        return cursor.fetchall() if cursor else []


    def get_files_with_potential_unprocessed_chunks(self, start_iso: str) -> List[str]:
        """
        Gets distinct file paths from FCHUNKS that might have unprocessed chunks
        based on RESULTS misses and REQUEST_LOG failure counts for the current run.
        """
        results_table = self.config.results_table
        run_tag = self.config.run_tag
        max_failures = self.config.inconfig_values.max_failures

        run_tag_filter_results = f'AND r.run_tag = ?' if run_tag else 'AND r.run_tag IS NULL' if run_tag is None else ''

        # Query finds distinct files from FCHUNKS...
        # ...where at least one chunk is NOT in RESULTS (for the tag)...
        # ...AND that chunk has NOT hit the failure limit since start_iso.
        # Uses LEFT JOIN and WHERE IS NULL check for broader compatibility/performance
        sql_query = f'''
            SELECT DISTINCT c.file
            FROM FCHUNKS c
            LEFT JOIN "{results_table}" r ON c.file = r.file AND c.chunknumber = r.chunknumber {run_tag_filter_results}
            LEFT JOIN (
                SELECT file, chunknumber, COUNT(*) as failure_count
                FROM REQUEST_LOG
                WHERE success = 0 AND timestamp >= ?
                GROUP BY file, chunknumber
            ) rl ON c.file = rl.file AND c.chunknumber = rl.chunknumber
            WHERE r.request_id IS NULL -- Chunk not successfully processed
            AND (rl.failure_count IS NULL OR rl.failure_count < ?) -- Chunk hasn't failed too much
        '''

        params = []
        if run_tag is not None:
            params.append(run_tag)
        params.extend([start_iso, max_failures])

        cursor = self._execute_query(sql_query, tuple(params))
        return [row[0] for row in cursor.fetchall()] if cursor else []


    def get_all_files_in_fchunks(self) -> List[str]:
        """Returns a list of all unique file paths currently stored in FCHUNKS."""
        query = "SELECT DISTINCT file FROM FCHUNKS"
        cursor = self._execute_query(query)
        return [row[0] for row in cursor.fetchall()] if cursor else []

    def log_request(self, file: str, chunk_number: int, timestamp:str, result: ProcessingResult) -> int:
        """Logs the outcome of an LLM request attempt."""
        query = '''
            INSERT INTO REQUEST_LOG
            (file, chunknumber, timestamp, model, raw_response, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        '''
        params = (
            file,
            chunk_number,
            timestamp,
            self.config.inconfig_values.model,
            result.raw_response,
            1 if result.success else 0, # Store boolean as integer
            result.error_message
        )
        cursor = self._execute_query(query, params)
        last_id = cursor.lastrowid if cursor else -1
        if last_id != -1:
             self.connection.commit() # Commit successful log
        else:
             logger.error(f"Failed to log request for {file} chunk {chunk_number}")
        return last_id


    def store_results(self, request_id: int, file: str, chunk_number: int, data: Dict[str, Any]):
        """Stores successfully extracted data."""
        results_table = self.config.results_table
        results_columns = self.schema[results_table].get_column_names()

        cols_to_insert = ['request_id', 'file', 'chunknumber']
        vals_to_insert = [request_id, file, chunk_number]

        if 'run_tag' in results_columns:
            cols_to_insert.append('run_tag')
            vals_to_insert.append(self.config.run_tag)

        # Add dynamically mapped columns
        for json_node, db_column in self.config.db_mapping.items():
            if db_column in results_columns and db_column not in cols_to_insert:
                cols_to_insert.append(db_column)
                # Get value, defaulting to None if node missing (for optional nodes)
                vals_to_insert.append(data.get(json_node))

        cols_str = ', '.join([f'"{c}"' for c in cols_to_insert]) # Quote column names
        placeholders = ', '.join(['?'] * len(vals_to_insert))
        query = f'INSERT INTO "{results_table}" ({cols_str}) VALUES ({placeholders})'

        if self._execute_query(query, tuple(vals_to_insert)) is not None:
             self.connection.commit() # Commit successful result storage
        else:
             logger.error(f"Failed to store results for request_id {request_id} ({file} chunk {chunk_number})")


    def close(self):
        """Closes the database connection if open."""
        if self.connection:
            try:
                # Optional: Commit any pending transaction before closing
                # self.connection.commit()
                self.connection.close()
                logger.debug("Database connection closed.")
                self.connection = None
            except Exception as e:
                logger.error(f"Error closing database connection: {e}")


    def get_all_skipped_chunks_for_run(self, start_iso: str, end_iso: str) -> List[Tuple[str, int, int]]:
        """Gets chunks that hit the failure limit during the specified run period."""
        query = '''
            SELECT file, chunknumber, COUNT(*) as failures
            FROM REQUEST_LOG
            WHERE success = 0
            AND timestamp >= ? AND timestamp <= ?
            GROUP BY file, chunknumber
            HAVING failures >= ?
            ORDER BY file, chunknumber
        '''
        params = (start_iso, end_iso, self.config.inconfig_values.max_failures)
        cursor = self._execute_query(query, params)
        return cursor.fetchall() if cursor else []


    def get_run_summary_stats(self, start_iso: str, end_iso: str) -> Tuple[int, int]:
         """Gets the count of LLM calls and successful results for the run period."""
         llm_calls = 0
         successes = 0

         # Count total LLM calls (requests logged)
         query_calls = "SELECT COUNT(*) FROM REQUEST_LOG WHERE timestamp >= ? AND timestamp <= ?"
         cursor_calls = self._execute_query(query_calls, (start_iso, end_iso))
         if cursor_calls:
             result = cursor_calls.fetchone()
             llm_calls = result[0] if result else 0

         # Count successful extractions (results stored)
         results_table = self.config.results_table
         query_success = f"""
             SELECT COUNT(*)
             FROM "{results_table}"
             WHERE request_id IN (
                 SELECT id FROM REQUEST_LOG WHERE timestamp >= ? AND timestamp <= ?
             )
         """
         # Add run_tag filter if applicable
         params_success = [start_iso, end_iso]
         if self.config.run_tag:
             query_success += " AND run_tag = ?"
             params_success.append(self.config.run_tag)

         cursor_success = self._execute_query(query_success, tuple(params_success))
         if cursor_success:
             result = cursor_success.fetchone()
             successes = result[0] if result else 0

         return llm_calls, successes
