# gar_tool/config_handler.py

from typing import Dict, Optional, Any, List
import os
import yaml
from dataclasses import dataclass

from .logging_wrapper import logger
from .helpers import collapse_whitespace

MAX_LLM_EXTRACTION_FAILURES_LIMIT_PER_CHUNK = 5 # limit on maximum accepted value provided by the user

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
#    excerpt: int = 100
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
        
        if not isinstance(config.results_db, str): 
            logger.critical_exit(f"Database name must be a string, got {type(config.results_db)}") 
        if not config.results_db:  # Check for empty string 
            logger.critical_exit("Database name cannot be empty") 
        if os.path.isdir(config.results_db):
            logger.critical_exit(f"Database name '{config.results_db}' is a directory, not a file.")
        if os.path.exists(config.results_db): # if db file already exists, then check for permissions.
          if not os.access(config.results_db, os.W_OK):
              logger.critical_exit(f"Database file '{config.results_db}' is not writable. Check file permissions.")
        else: # otherwise, db file will be created, but its parent folder should have permissions
            parent_dir = os.path.dirname(config.results_db)
            if parent_dir: # if not empty, check for permissions.
                if not os.access(parent_dir, os.W_OK):
                    logger.critical_exit(f"The directory '{parent_dir}' does not have write permissions to create the database file.")
                else: # parent dir is empty, it means we write in current dir, so we need to check it.
                    if not os.access(".", os.W_OK):
                        logger.critical_exit("The current directory does not have write permissions to create the database file.")


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