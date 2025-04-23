# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Nothing yet.

### Changed
- Nothing yet.

### Fixed
- Nothing yet.

## [0.2.0] - YYYY-MM-DD

*Note: Version bumped significantly due to major refactoring and feature additions.*

### Added
- **Multi-Format Support:** Added processing for `.pdf`, `.docx`, and `.pptx` files using the `markitdown-python` library.
- **Modular Structure:** Refactored the entire project into a Python package named `gar_tool` with distinct modules (`main`, `cli`, `config_handler`, `database_handler`, `analyzer`, `file_processor`, `logging_wrapper`).
- **File Processing Module:** Introduced `file_processor.py` to abstract file reading, format conversion (via `markitdown`), and chunk calculation.
- **Installation Extras:** Updated installation requirements and instructions to include necessary `markitdown` extras (e.g., `pip install "markitdown[pdf,docx,pptx]"`).
- **Changelog:** This `CHANGELOG.md` file was created.
- **Documentation:** Switched primary documentation file to `README.rst` (reStructuredText).
- **CLI Enhancements:** Command-line help (`--help`) now displays default values for arguments. Added `--version` flag.
- **Central Version:** Version defined centrally in `gar_tool/__init__.py`.

### Changed
- **Execution:** The tool is now run as a module: `python -m gar_tool.main [args...]`.
- **Efficiency:** File conversion (`markitdown`) or reading now occurs only once per file during a run, with the content reused for processing all necessary chunks. This significantly speeds up processing for convertible formats.
- **Processing Flow:** The main loop now identifies files requiring work based on DB state and folder contents, then processes chunks for one file at a time, rather than selecting randomly from a global chunk list.
- **Configuration:** Updated default `data_folder` in example `config.yaml`. Refined config loading and validation in `config_handler.py`.
- **Database:** Refined schema definition and query logic in `database_handler.py`. Improved error handling and index creation.
- **Logging:** Enhanced `logging_wrapper.py` with slightly more structured formatting based on level.
- **README:** Extensively updated `README.rst` to reflect the new structure, features, installation, and usage.

### Fixed
- Corrected the usage of the `markitdown` library API for file conversion, resolving previous `AttributeError`.
- Addressed potential issues with file path handling (using absolute paths internally where appropriate).

## [0.1.x] - Previous Versions (Implicit)

*(Based on the state before the 0.2.0 refactor)*

### Added
- Initial version implemented as a single script (`batch_doc_analyzer.py`).
- Core functionality for LLM-based structured data extraction from text files (`.txt`, `.md`).
- Configuration via `config.yaml` for defining extraction nodes and LLM parameters.
- SQLite database storage for results (`DATA` table) and request logs (`REQUEST_LOG`).
- Chunking mechanism for large files based on character count.
- Checkpointing and resumption capability using the database state.
- Command-line argument parsing to override configuration defaults.
- Support for API keys via `.env` file (specifically `OPENROUTER_API_KEY`).
- Basic logging to console.
- Run tagging feature (`--run_tag`) for comparative experiments.