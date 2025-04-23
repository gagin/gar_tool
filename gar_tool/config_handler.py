import os
import yaml
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from .logging_wrapper import logger

# Default values for configuration settings
DEFAULT_CHUNK_SIZE = 50000
DEFAULT_TEMPERATURE = 0.0
DEFAULT_TIMEOUT = 30
DEFAULT_DATA_FOLDER = "./src"
DEFAULT_MAX_FAILURES = 2
DEFAULT_MODEL = "google/gemini-2.0-flash-001:floor"
DEFAULT_PROVIDER = "https://openrouter.ai/api/v1"
DEFAULT_RESULTS_TABLE = "DATA"
DEFAULT_MAX_LOG_LENGTH = 200


@dataclass
class ExtractorDefaults:
    """Stores default configuration values."""
    chunk_size: int = DEFAULT_CHUNK_SIZE
    temperature: float = DEFAULT_TEMPERATURE
    timeout: int = DEFAULT_TIMEOUT
    data_folder: str = DEFAULT_DATA_FOLDER
    max_failures: int = DEFAULT_MAX_FAILURES
    model: str = DEFAULT_MODEL
    provider: str = DEFAULT_PROVIDER
    max_log_length: int = DEFAULT_MAX_LOG_LENGTH


@dataclass
class ExtractorConfig:
    """Holds the complete, validated configuration for an extraction run."""
    name: str
    inconfig_values: ExtractorDefaults
    prompt: str
    expected_json_nodes: List[str] = field(default_factory=list)
    db_mapping: Dict[str, str] = field(default_factory=dict)
    node_configs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    results_table: str = DEFAULT_RESULTS_TABLE
    results_db: Optional[str] = None
    key: Optional[str] = None
    skip_key_check: bool = False
    run_tag: Optional[str] = None


class ConfigLoader:
    """Handles loading and validation of the YAML configuration."""

    @staticmethod
    def load_config_file(config_path: str) -> Optional[ExtractorConfig]:
        """Load and validate configuration from YAML file."""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)

            if not config_data:
                 logger.critical_exit(f"Config file '{config_path}' is empty.")
                 return None # Should be unreachable due to exit

            if not ConfigLoader._validate_yaml_structure(config_data):
                return None # Error message already logged

            defaults = ExtractorDefaults(
                chunk_size=config_data.get('defaults', {}).get(
                    'chunk_size', DEFAULT_CHUNK_SIZE),
                temperature=config_data.get('defaults', {}).get(
                    'temperature', DEFAULT_TEMPERATURE),
                timeout=config_data.get('defaults', {}).get(
                    'timeout', DEFAULT_TIMEOUT),
                data_folder=config_data.get('defaults', {}).get(
                    'data_folder', DEFAULT_DATA_FOLDER),
                max_failures=config_data.get('defaults', {}).get(
                    'max_failures', DEFAULT_MAX_FAILURES),
                model=config_data.get('defaults', {}).get(
                    'model', DEFAULT_MODEL),
                provider=config_data.get('defaults', {}).get(
                    'provider', DEFAULT_PROVIDER),
                max_log_length=config_data.get('defaults', {}).get(
                    'max_log_length', DEFAULT_MAX_LOG_LENGTH)
            )

            nodes_data = config_data.get('nodes', {})
            expected_nodes, db_mapping, node_configs, node_descriptions = \
                ConfigLoader._parse_nodes(nodes_data)

            prompt_template = config_data.get('prompt_template', '')
            if not prompt_template:
                 logger.warning("Config warning: 'prompt_template' is missing or empty.")

            prompt = prompt_template.format(
                node_descriptions='\n'.join(node_descriptions)
            )

            return ExtractorConfig(
                name=config_data.get('name', 'default_project'),
                inconfig_values=defaults,
                prompt=prompt,
                expected_json_nodes=expected_nodes,
                db_mapping=db_mapping,
                node_configs=node_configs,
            )

        except FileNotFoundError:
            logger.critical_exit(f"Configuration file not found: {config_path}")
            return None
        except yaml.YAMLError as e:
            logger.critical_exit(f"Invalid YAML in configuration file: {e}")
            return None
        except KeyError as e:
             logger.critical_exit(f"Missing expected key in config: {e}")
             return None
        except Exception as e:
             logger.critical_exit(f"Error loading config: {e}", exc_info=True)
             return None

    @staticmethod
    def _validate_yaml_structure(config_data: Any) -> bool:
        """Basic validation of the loaded YAML structure."""
        if not isinstance(config_data, dict):
            logger.critical_exit("Configuration must be a dictionary.")
            return False

        required_sections = ['name', 'nodes', 'prompt_template']
        for section in required_sections:
            if section not in config_data:
                logger.warning(f"Config missing recommended section: '{section}'.")
                # Allow missing for flexibility, but warn. Name defaults later.

        if 'defaults' in config_data and not isinstance(config_data['defaults'], dict):
            logger.critical_exit("'defaults' section must be a dictionary.")
            return False

        if 'nodes' in config_data and not isinstance(config_data['nodes'], dict):
            logger.critical_exit("'nodes' section must be a dictionary.")
            return False

        return True


    @staticmethod
    def _parse_nodes(nodes_data: Dict[str, Any]):
        """Parses the 'nodes' section of the config."""
        expected_nodes = []
        db_mapping = {}
        node_configs = {}
        node_descriptions = []

        if not nodes_data:
            logger.warning("Config: 'nodes' section is empty or missing.")
            return [], {}, {}, []

        for name, node in nodes_data.items():
            if not isinstance(node, dict):
                logger.warning(f"Skipping node '{name}': configuration must be a dictionary.")
                continue

            if 'description' not in node:
                logger.warning(f"Node '{name}' missing 'description'. Adding placeholder.")
                node['description'] = "(No description provided)"

            desc_line = f"- {name}"
            is_required = node.get('required', False) # Default to not required

            if not isinstance(is_required, bool):
                logger.warning(f"Node '{name}': 'required' value is not boolean. Treating as False.")
                is_required = False

            if is_required:
                desc_line += " (required)"
            # else:
                # desc_line += " (optional)" # Optionally make optional explicit

            desc_line += f": {node['description']}"
            if node.get('format'):
                desc_line += f" (format: {node['format']})"

            node_descriptions.append(desc_line)
            expected_nodes.append(name)

            # Use node name as db_column if 'db_column' is missing or empty
            db_col = node.get('db_column')
            if db_col: # Handles None or empty string
                db_mapping[name] = db_col
            else:
                 # Only map if it's intended to be stored implicitly
                 # We assume if db_column isn't specified, it's not stored by default
                 # To store with node name, explicitly set db_column: node_name
                 # logger.debug(f"Node '{name}' has no 'db_column', won't be stored in default DATA table.")
                 pass # Don't map if db_column is missing

            node_configs[name] = node # Store full node config

        return expected_nodes, db_mapping, node_configs, node_descriptions


    @staticmethod
    def validate_runtime_config(config: ExtractorConfig) -> bool:
        """
        Validates combined config values after CLI overrides.
        Includes checks for paths and basic API key presence.
        Returns True if valid, False otherwise (errors logged).
        """
        settings = config.inconfig_values
        valid = True # Assume valid initially

        # Validate numeric settings
        if not isinstance(settings.temperature, (int, float)) or not (0 <= settings.temperature <= 2.0):
            logger.error(f"Invalid temperature: {settings.temperature}. Must be float between 0.0 and 2.0.")
            valid = False
        if not isinstance(settings.chunk_size, int) or settings.chunk_size <= 0:
            logger.error(f"Invalid chunk_size: {settings.chunk_size}. Must be positive integer.")
            valid = False
        if not isinstance(settings.timeout, int) or settings.timeout <= 0:
            logger.error(f"Invalid timeout: {settings.timeout}. Must be positive integer.")
            valid = False
        if not isinstance(settings.max_failures, int) or settings.max_failures < 0:
            logger.error(f"Invalid max_failures: {settings.max_failures}. Must be non-negative integer.")
            valid = False
        if not isinstance(settings.max_log_length, int) or settings.max_log_length < 0:
            logger.error(f"Invalid max_log_length: {settings.max_log_length}. Must be non-negative integer.")
            valid = False

        # Validate paths and permissions
        df = settings.data_folder
        if not isinstance(df, str) or not df:
            logger.error("Data folder path must be a non-empty string.")
            valid = False
        elif not os.path.exists(df):
            logger.error(f"Data folder does not exist: {df}")
            valid = False
        elif not os.path.isdir(df):
            logger.error(f"Data folder path is not a directory: {df}")
            valid = False
        elif not os.access(df, os.R_OK):
            logger.error(f"Data folder is not readable: {df}")
            valid = False

        db_path = config.results_db
        if not isinstance(db_path, str) or not db_path:
            logger.error("Results database path must be a non-empty string.")
            valid = False
        else:
            db_dir = os.path.dirname(db_path)
            # If db_dir is empty, it means current directory
            write_dir = db_dir if db_dir else "."
            if os.path.exists(db_path):
                if os.path.isdir(db_path):
                    logger.error(f"Results database path exists but is a directory: {db_path}")
                    valid = False
                elif not os.access(db_path, os.W_OK):
                    logger.error(f"Results database file exists but is not writable: {db_path}")
                    valid = False
            elif not os.access(write_dir, os.W_OK):
                 # Check if parent directory is writable for new file creation
                 logger.error(f"Cannot create results database: Directory '{write_dir}' is not writable.")
                 valid = False

        # Validate model/provider strings
        if not isinstance(settings.model, str) or not settings.model:
            logger.error("Model name must be a non-empty string.")
            valid = False
        if not isinstance(settings.provider, str) or not settings.provider:
            logger.error("Provider URL must be a non-empty string.")
            valid = False

        # Validate API key presence (if not skipped)
        if not config.key and not config.skip_key_check:
            logger.error(
                "API key is missing. Set OPENROUTER_API_KEY environment "
                "variable or use --skip_key_check."
            )
            valid = False

        if not valid:
             logger.critical_exit("Configuration validation failed. Please check errors above.")

        return valid # Return status (though exit might have occurred)
