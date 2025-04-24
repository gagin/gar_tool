====================================
 GAR: Generation-Augmented Retrieval
====================================

.. image:: https://img.shields.io/badge/python-3.9%2B-blue.svg
   :target: https://www.python.org/downloads/
   :alt: Python 3.9+

.. |Supported Formats| image:: https://img.shields.io/badge/formats-pdf%7Cdocx%7Cpptx%7Cmd%7Ctxt-brightgreen
   :alt: Supported Formats: pdf|docx|pptx|md|txt

  .. image:: https://tokei.rs/b1/github/gagin/gar_tool
  :alt: Lines of Code
  :target: https://github.com/gagin/gar_tool

|Supported Formats|

This command-line tool helps you extract specific information from large collections of documents (PDF, DOCX, PPTX, Markdown, Text) and organizes it into a structured SQLite database using Large Language Models (LLMs). Whether you're working with data that was once structured but is now in various document formats, or you're seeking to derive new insights from unstructured information, this tool is designed to assist you. Ideal for data analysts and researchers who need to convert unstructured or semi-structured documents into analyzable data.

#DataExtraction #LLM #RetrievalAugmentedGeneration #AI #NLP #MachineLearning #TextProcessing #DataAnalysis #SQLite #Automation #OpenSource #SemanticParsing

.. contents:: Table of Contents
   :local:
   :depth: 2

Key Features
============

*   **Multi-Format Input**: Processes `.pdf`, `.docx`, `.pptx`, `.md`, and `.txt` files using the `markitdown` library for conversion to text.
*   **Explicit and Implicit Data Extraction**: Retrieve both clearly defined data (e.g., addresses) and subtle, subjective details inferred from text (e.g., visual appeal ratings).
*   **Single-point Configuration**: Define what to extract and how to store it using a single YAML file (`config.yaml`). This configuration instructs the LLM and structures the database storage.
*   **Multiple Models and Providers Support**: Compatible with various language models and providers (e.g., OpenRouter, local Ollama instances) via OpenAI-compatible APIs.
*   **Efficient Processing with Checkpointing**: Processes documents sequentially, handling large files by chunking. Automatic checkpointing allows interruption (`Ctrl+C`) and resumption.
*   **SQLite Database Storage**: Stores structured results in an SQLite database for easy querying, analysis, and export.
*   **Test Labelling Capabilities**: Add run tags via the ``--run_tag`` command-line parameter to database entries, allowing for comparison of different configurations, models, or prompts.
*   **Modular Codebase**: Organized into logical Python modules within the `gar_tool` package for better maintainability.

Conceptual Overview: Generation Augmented Retrieval (GAR)
========================================================

This tool was developed for a project that initially considered Retrieval-Augmented Generation (RAG), a method that enriches language model responses with relevant source documents. However, this tool adopts a fundamentally different approach, focusing on generating structured data to enhance future retrieval. We call this approach **Generation Augmented Retrieval (GAR)**.

Essentially, GAR prioritizes the systematic extraction and organization of data, enabling more sophisticated and efficient future retrieval. In contrast to traditional RAG, which retrieves documents to answer a specific query, GAR uses language models to generate data that can then be retrieved. This "inversion" of the typical RAG flow can be thought of as "Inverse RAG." Another helpful metaphor is the "RAG Prism," where unstructured documents are "refracted" into their component insights, creating structured, searchable data.

Think of it this way:

*   **Traditional RAG:** "Here's a question; find relevant documents to help answer it." (Query-driven retrieval)
*   **GAR:** "Here's a document; extract these specific pieces of information from it." (Data-driven generation)

Specifically, GAR:

*   Extracts data that might have been originally structured but was lost in various document formats (e.g., addresses, titles from reports).
*   Creates new, structured fields from descriptive text (e.g., categorizing items, assigning ratings).
*   Processes large document collections, producing an SQLite database for analysis.

By creating this structured database, GAR enhances future retrieval capabilities. For example, you could then perform complex queries like, "Show me all First Nations artworks with high 'Instagrammability' ratings near my location."

In essence, this tool doesn't just retrieve; it distills. And, by creating a structured database, it can actually *enhance* future RAG capabilities by providing structured metadata alongside the original text.

Example: Vancouver Public Art Explorer
=====================================

Let's walk through analyzing Vancouver's public art collection to find First Nations artworks and Instagram-worthy locations.

Source Data
-----------

We start with data about Vancouver's public art. This might originally be in PDF reports, Word documents, or, as in this simplified example, Markdown files. The tool converts PDF/DOCX/PPTX to Markdown internally before processing.

Here's a sample entry (`Fusion.md`):

.. code-block:: markdown

    ## Title of Work
    Fusion

    ## ArtistProjectStatement
    "Fusion" is an artwork that marries mediums and cultures...as well as legends.
    The sculpture is contemporary yet unmistakably Salish. As this development sits
    in traditional Musqueam territory...

    ## SiteAddress
    70th Avenue & Cornish Street

    ## DescriptionOfwork
    This sculpture sits in the heart of Marpole... The 14' high water-jet cut
    aluminum sculpture, powder coated in copper and silver paint, is a contemporary
    Coast Salish design depicting salmon and river grass...

Configuration (`config.yaml`)
---------------------------

Define the fields to extract in `config.yaml`. Within the `nodes` section, list each piece of information:

*   **description**: Instruction for the LLM on what to look for and how to format the finding.
*   **format**: Expected data type (e.g., text, number, boolean) - currently informational for the prompt, schema uses TEXT.
*   **db_column**: (Optional) Name of the column in the SQLite `DATA` table. If omitted, the node data is not stored in the default results table.
*   **required**: (Optional, boolean, defaults to `false`) Whether the LLM *must* provide a value for this node for the extraction to be considered successful.

.. code-block:: yaml
    :emphasize-lines: 3, 33

    # Extraction configuration
    name: public_art_vancouver # Used as a base name for SQLite file (<name>.db)

    # LLM configuration defaults, can be overridden by command line parameters
    defaults:
      chunk_size: 50000
      temperature: 0
      timeout: 30
      data_folder: ./art-source # Default source directory
      max_failures: 2  # Max consecutive LLM failures per chunk
      model: google/gemini-2.0-flash-001:floor
      provider: https://openrouter.ai/api/v1
      max_log_length: 200 # Limit log excerpt length

    # Node definitions (what to extract)
    nodes:
      art_name:
        description: Name of the art
        format: text
        db_column: name
        required: true # Example: Name is required

      location:
        description: Physical address or location of the artwork
        format: text
        db_column: address

      is_first_nations:
        description: Is it a first nations art? (Respond 1 for true, 0 for false)
        format: boolean
        db_column: first_nations

      is_first_nations_quote:
        description: >
          Provide a full sentence from the document that was base for determination whether
          it's first nations art. Leave empty if not applicable.
        format: text
        db_column: first_nations_quote

      visually_interesting:
        description: How interesting it looks on scale of 0 to 10, as in being instagrammable?
        format: number
        db_column: instagrammability

      # Example of a node NOT stored in the DB by default
      internal_notes:
         description: Your brief analysis notes for the LLM only (not stored).
         format: text
         required: false

    # Prompt template sent to the LLM
    prompt_template: |
      # Overall task
      Analyze the provided text chunk to extract structured details.
      Return a valid JSON object containing the following nodes:
      {node_descriptions}
      Ensure JSON is strictly formatted, paying attention to escapes. Do not add notes outside the JSON structure.

      # Grounding & Persona (Customize based on your data)
      Use only information within the document. Treat placeholders like 'n/a' as unavailable data unless context implies otherwise.
      Act as a knowledgeable city resident interested in public art.
      If a required field cannot be found, use 'null' as its value in the JSON.

      # Definitions & Formatting (Customize)
      Boolean fields should be 1 (true) or 0 (false).
      Instagrammability: Rate 1-10 based on visual appeal for social media.
      Provide quotes verbatim.


**Note on YAML**: Pay close attention to indentation (use spaces, not tabs). Incorrect indentation can cause nodes or settings to be ignored. Use ``>`` for multi-line strings that should be treated as a single line.

Installation
------------

1.  **Prerequisites**: Python 3.9+ and `pip`.
2.  **Virtual Environment (Recommended)**:
    .. code-block:: 

        python -m venv venv
        source venv/bin/activate  # On Windows use `venv\Scripts\activate`
3.  **Install Dependencies**:
    Create a `requirements.txt` file (or use the one provided if available) with contents like:
    .. code-block::

        PyYAML>=6.0,<7.0
        python-dotenv>=1.0,<2.0
        requests>=2.30,<3.0
        markitdown-python>=0.4.0,<0.5.0

    Then install:
    .. code-block:: 

        pip install -r requirements.txt

4.  **Install `markitdown` Extras**: For PDF, DOCX, and PPTX support, install the necessary optional dependencies:
    .. code-block:: 

        # Install support for specific formats you need:
        pip install "markitdown[pdf,docx,pptx]"

        # Or install all optional dependencies:
        # pip install "markitdown[all]"

5.  **API Key**: Create a `.env` file in the project root directory (where you run the command from) with your LLM provider API key (e.g., for OpenRouter):
    .. code-block:: 

        # .env file
        OPENROUTER_API_KEY="sk-or-v1-..."

    *Tip*: Set usage limits on your API key via the provider's dashboard.

Extraction Process
------------------

1.  **Place Source Files**: Put your documents (`.pdf`, `.docx`, `.pptx`, `.md`, `.txt`) into the directory specified by `--data_folder` (or the default `./art-source`).
2.  **Run the Extractor**: Execute the main module from the project root directory.
    .. code-block:: 
        python -m gar_tool.main --config config.yaml --data_folder ./art-source

    *   Use `--help` to see all command-line options which can override `config.yaml` settings.
3.  **Processing**: The tool will:
    *   Identify files needing processing (new files or files with unprocessed chunks).
    *   Convert PDF/DOCX/PPTX files to text using `markitdown`.
    *   Calculate character-based chunk boundaries if the file is new.
    *   For each required chunk:
        *   Send the chunk content and the prompt (from `config.yaml`) to the configured LLM.
        *   Attempt to parse a JSON object from the LLM response.
        *   Log the request details and outcome to the `REQUEST_LOG` table.
        *   If successful (valid JSON, required fields present), store the extracted data in the `DATA` table (or the table name defined in `config.yaml`).
4.  **Output**: The tool generates an SQLite database file (e.g., `public_art_vancouver.db`) in the directory where you run the command.

Sample LLM JSON Output (for one chunk)
--------------------------------------

.. code-block:: json

    {
      "art_name": "Fusion",
      "location": "70th Avenue & Cornish Street",
      "is_first_nations": 1,
      "is_first_nations_quote": "The sculpture is contemporary yet unmistakably Salish.",
      "visually_interesting": 7,
      "internal_notes": null
    }

Results in SQLite (`public_art_vancouver.db`, `DATA` table)
----------------------------------------------------------

Use a tool like [DB Browser for SQLite](https://sqlitebrowser.org/) to view the database.

Create a table with the following structure:

============  ===========================================================  ===========  ===========  ======  =========================  =============  ======================================================  =================
request_id    file                                                         chunknumber  run_tag      name    address                    first_nations  first_nations_quote                                     instagrammability
============  ===========================================================  ===========  ===========  ======  =========================  =============  ======================================================  =================
1             /path/to/art-source/Fusion.md                                0            config.yaml  Fusion  70th Avenue & Cornish St.  1              The sculpture is contemporary yet unmistakably Salish.  7
...           ...                                                          ...          ...          ...     ...                        ...            ...                                                     ...
============  ===========================================================  ===========  ===========  ======  =========================  =============  ======================================================  =================
**Note on Chunking**: Files larger than the `chunk_size` configured in `defaults` or via `--chunk_size` are split into multiple chunks. Each chunk is processed independently by the LLM. The `chunknumber` column indicates which part of the file the extracted data pertains to. The `start` and `end` character indices for each chunk are stored in the `FCHUNKS` table.

Tips for Efficient Field Extraction (Prompt-Engineering)
========================================================

*   **Boolean Markers**: Ask for a boolean (yes/no or 1/0) before asking for related details (like quotes). This helps the LLM focus and simplifies SQL filtering later.
*   **Strategic Order**: The order of fields requested in the prompt (`{node_descriptions}`) can significantly impact LLM accuracy. Experiment with different orderings (e.g., Boolean -> Quote -> Label, Quote -> Boolean -> Label). Use the ``--run_tag`` argument to label test runs for comparison in the database. *Ensure configurations used for comparison have the exact same `db_column` definitions to avoid schema errors.*
*   **Interplay Between Fields**: Consider how one extracted field might influence another (e.g., identifying cultural relevance might affect perceived 'instagrammability'). Test sequences.
*   **Normalize Output Format**: Be explicit in the prompt about desired formats (e.g., "Use 1 for true, 0 for false", "Date format YYYY-MM-DD", "Category must be singular noun, capitalized").
*   **Cautious Examples**: Providing examples *in the prompt* can guide the LLM but risks overfitting (model copies examples instead of analyzing). Focus on clear instructions and format definitions rather than many specific content examples.
*   **Clarity over Brevity**: Ensure descriptions clearly explain what information is needed and how it should be presented.

Supported File Formats
======================

The tool leverages the `markitdown-python` library to handle various input formats:

*   `.pdf` (Requires ``pip install "markitdown[pdf]"``)
*   `.docx` (Requires ``pip install "markitdown[docx]"``)
*   `.pptx` (Requires ``pip install "markitdown[pptx]"``)
*   `.md` (Markdown)
*   `.txt` (Plain Text, UTF-8 expected)

Install the necessary extras as shown in the Installation section.

Models
======

LLMs suitable for structured data extraction from potentially long context are needed. Examples:

*   `deepseek/deepseek-chat:floor`
*   `qwen/qwen-2.5-72b-instruct:floor`
*   `google/gemini-2.0-flash-001:floor` (Fast, cheap, often good quality)
*   `anthropic/claude-3.5-sonnet` (More expensive, potentially higher quality)

The `:floor` suffix via OpenRouter uses the cheapest available provider. Remove or use `:nitro` for potentially faster responses. Check [OpenRouter Models](https://openrouter.ai/models) for more options.

Smaller models may struggle with following complex instructions or adhering strictly to JSON format, leading to extraction failures (check `REQUEST_LOG` table for details).

Local Models (Ollama)
---------------------

You can use locally hosted models via Ollama or similar OpenAI-compatible servers.

1.  Install and run Ollama: [https://ollama.com/](https://ollama.com/)
2.  Download a suitable model: `ollama pull mistral` (or a larger model like `llama3`)
3.  Run the script pointing to your local server:

    .. code-block:: bash

        python -m gar_tool.main --provider http://localhost:11434/v1 \
                                 --model mistral \
                                 --skip_key_check \
                                 --timeout 120 # Increase timeout for local models

Execution & Checkpointing
=========================

*   **Processing Order**: The script identifies files potentially requiring work and processes them sequentially (order determined by `os.listdir` unless shuffled internally). Within a file, chunks are typically processed sequentially.
*   **Checkpointing**: Progress is saved to the SQLite database after each chunk processing attempt. You can stop the script (`Ctrl+C`) and resume it later. It will query the database to find remaining work (based on `run_tag`, successful completions in the results table, and failure counts in `REQUEST_LOG`).
*   **Database Locking**: SQLite handles locking. Brief locks during writes are normal. If the script fails due to `database is locked` or `database is busy`, ensure no other process (like DB Browser for SQLite with unsaved changes) is holding a long-running lock on the database file.
*   **Configuration Consistency**: **Crucially, do not change the `nodes` structure (especially `db_column` names) in `config.yaml` between runs that write to the *same database file*.** Doing so will cause schema mismatches and errors. If you need to change the extracted fields/columns, use a new database file (specify via `--results_db` or change the `name` in `config.yaml`).

Project Structure
=================

The code is organized within the `gar_tool` directory, making it a Python package:

*   `gar_tool/`
    *   `__init__.py`: Makes it a package, holds version.
    *   `main.py`: Main execution script, orchestration.
    *   `cli.py`: Command-line argument parsing.
    *   `config_handler.py`: Loads and validates `config.yaml`.
    *   `database_handler.py`: Handles all SQLite interactions.
    *   `analyzer.py`: Contains LLM interaction logic.
    *   `file_processor.py`: Handles file reading and conversion (`markitdown`).
    *   `logging_wrapper.py`: Custom logging setup.

Command-Line Options
====================

Run `python -m gar_tool.main --help` to see the latest options and their defaults:

.. code-block:: text

    # Output of: python -m gar_tool.main --help
    usage: main.py [-h] [--config CONFIG] [--data_folder DATA_FOLDER] [--results_db RESULTS_DB] [--chunk_size CHUNK_SIZE]
                   [--max_failures MAX_FAILURES] [--run_tag RUN_TAG] [--model MODEL] [--provider PROVIDER]
                   [--temperature TEMPERATURE] [--timeout TIMEOUT] [--skip_key_check] [--max_log_length MAX_LOG_LENGTH]
                   [--log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL}] [--version]

    GAR: Generation-Augmented Retrieval Tool. Extracts structured data from text files (txt, md, pdf, docx, pptx) using
    LLMs. Requires 'markitdown-python' for PDF/DOCX/PPTX. See README for details.

    options:
      -h, --help            show this help message and exit
      --version             Show program's version number and exit.

    Input and Output:
      --config CONFIG       Path to the YAML configuration file. (default: config.yaml)
      --data_folder DATA_FOLDER
                            Path to the directory containing source files. (default: ./src)
      --results_db RESULTS_DB
                            Name of the SQLite DB file. If None, uses '<config_name>.db'. (default: None)

    Processing Control:
      --chunk_size CHUNK_SIZE
                            Target chunk size in characters. (default: 50000)
      --max_failures MAX_FAILURES
                            Max consecutive LLM failures per chunk before skipping. (default: 2)
      --run_tag RUN_TAG     Label for this run in DB (allows reruns). Defaults to config filename. (default: None)

    AI Parameters:
      --model MODEL         Name of the LLM to use (provider-specific). (default: google/gemini-2.0-flash-001:floor)
      --provider PROVIDER   Base URL of the LLM provider API (OpenAI compatible). (default: https://openrouter.ai/api/v1)
      --temperature TEMPERATURE
                            LLM temperature (0.0-2.0). Lower is more deterministic. (default: 0.0)
      --timeout TIMEOUT     Timeout in seconds for LLM API requests. (default: 30)
      --skip_key_check      Skip API key check (e.g., for local models). (default: False)

    Script Behavior:
      --max_log_length MAX_LOG_LENGTH
                            Max length for logged excerpts (LLM prompts/responses). 0=unlimited. (default: 200)
      --log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL}
                            Set the logging level. (default: INFO)


Troubleshooting
===============

*   **PDF/DOCX/PPTX Not Processing**:
    *   Ensure `markitdown` extras are installed: ``pip install "markitdown[pdf,docx,pptx]"``.
    *   Run with `--log_level DEBUG` and check for `markitdown` conversion errors in the log (e.g., file corruption, library issues).
    *   Test conversion directly using the `markitdown` library on the problematic file.
*   **YAML Errors / Nodes Ignored**:
    *   Check `config.yaml` indentation carefully. Use spaces, maintain consistency.
    *   Ensure required sections (`name`, `nodes`, `prompt_template`) exist.
*   **Few Rows in Results Table (`DATA`)**:
    *   Inspect the `REQUEST_LOG` table in the SQLite database. Look for rows where `success = 0`. The `error_message` column will indicate why processing failed (e.g., "Missing required JSON nodes", "Failed to extract valid JSON").
    *   Check if `max_failures` was reached for chunks (query `REQUEST_LOG` where `success = 0` and group by `file`, `chunknumber`).
    *   Increase `--timeout` if requests are timing out.
    *   Try a different (potentially more capable) LLM specified via `--model`.
*   **Database Errors (`OperationalError`, `IntegrityError`)**:
    *   Ensure the directory for the database file is writable.
    *   Check file permissions on the database file if it already exists.
    *   If you changed `nodes`/`db_column` in `config.yaml`, ensure you are using a *new* database file or delete the old one. Schema mismatches cause errors.
    *   Ensure no other application has an exclusive lock on the DB file.

Credits
=======

*   Initial code structure and core logic development assisted by AI models (Claude 3.5 Sonnet, Google Gemini).
*   Uses the `markitdown-python` library for file conversion.
*   README inspiration from various open-source projects.

Alternative Solutions
=====================

*   **Web UI Apps**: Extracta.ai, ExtractNinja offer similar functionality via web interfaces.
*   **Developer Frameworks**: LlamaIndex, LangChain provide building blocks for extraction pipelines but require more coding. Sparrow focuses on VLMs.
*   **Enterprise Tools**: Altair Monarch, Google Cloud Document AI offer robust data preparation and extraction features for enterprise use cases.

To-Do / Future Enhancements
===========================

*   **Structured LLM Output**: Explore using model-specific structured output features (like OpenAI functions/tools) for potentially better reliability and cost-efficiency where available.
*   **Improved Error Handling**: More granular error reporting and potentially configurable retry logic for transient network/API issues.
*   **Schema Type Consistency**: Use `format` from `config.yaml` to potentially define SQLite column types more accurately (though SQLite's dynamic typing is flexible).
*   **True Parallelism**: Investigate using `multiprocessing` or `asyncio` for concurrent processing of *different files* or even chunks (requires careful handling of DB locking and API rate limits).
*   **Direct CSV Input**: Allow direct processing of CSV files where one column contains large text blocks.
*   **More Converters**: Potentially integrate other conversion libraries if `markitdown` doesn't cover all needs.