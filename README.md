# GAR: Generation-Augmented Retrieval

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![Supported Formats: pdf|docx|pptx|md|txt](https://img.shields.io/badge/formats-pdf%7Cdocx%7Cpptx%7Cmd%7Ctxt-brightgreen)](https://github.com/gagin/gar_tool)
[![Lines of Code](https://tokei.rs/b1/github/gagin/gar_tool)](https://github.com/gagin/gar_tool)

This command-line tool helps you extract specific information from large collections of documents (PDF, DOCX, PPTX, Markdown, Text) and organizes it into a structured SQLite database using Large Language Models (LLMs). Whether you're working with data that was once structured but is now in various document formats, or you're seeking to derive new insights from unstructured information, this tool is designed to assist you. Ideal for data analysts and researchers who need to convert unstructured or semi-structured documents into analyzable data.

#DataExtraction #LLM #RetrievalAugmentedGeneration #AI #NLP #MachineLearning #TextProcessing #DataAnalysis #SQLite #Automation #OpenSource #SemanticParsing

## Table of Contents

*   [Key Features](#key-features)
*   [Conceptual Overview: Generation Augmented Retrieval (GAR)](#conceptual-overview-generation-augmented-retrieval-gar)
*   [Example: Vancouver Public Art Explorer](#example-vancouver-public-art-explorer)
    *   [Source Data](#source-data)
    *   [Configuration (`config.yaml`)](#configuration-configyaml)
*   [Installation](#installation)
*   [Extraction Process](#extraction-process)
*   [Sample LLM JSON Output (for one chunk)](#sample-llm-json-output-for-one-chunk)
*   [Results in SQLite (`public_art_vancouver.db`, `DATA` table)](#results-in-sqlite-public_art_vancouverdb-data-table)
*   [Tips for Efficient Field Extraction (Prompt-Engineering)](#tips-for-efficient-field-extraction-prompt-engineering)
*   [Supported File Formats](#supported-file-formats)
*   [Models](#models)
    *   [Local Models (Ollama)](#local-models-ollama)
*   [Execution & Checkpointing](#execution--checkpointing)
*   [Project Structure](#project-structure)
*   [Command-Line Options](#command-line-options)
*   [Troubleshooting](#troubleshooting)
*   [Credits](#credits)
*   [Alternative Solutions](#alternative-solutions)
*   [To-Do / Future Enhancements](#to-do--future-enhancements)

## Key Features

*   **Multi-Format Input**: Processes `.pdf`, `.docx`, `.pptx`, `.md`, and `.txt` files using the `markitdown` library for conversion to text.
*   **Explicit and Implicit Data Extraction**: Retrieve both clearly defined data (e.g., addresses) and subtle, subjective details inferred from text (e.g., visual appeal ratings).
*   **Single-point Configuration**: Define what to extract and how to store it using a single YAML file (`config.yaml`). This configuration instructs the LLM and structures the database storage.
*   **Multiple Models and Providers Support**: Compatible with various language models and providers (e.g., OpenRouter, local Ollama instances) via OpenAI-compatible APIs.
*   **Efficient Processing with Checkpointing**: Processes documents sequentially, handling large files by chunking. Automatic checkpointing allows interruption (`Ctrl+C`) and resumption.
*   **SQLite Database Storage**: Stores structured results in an SQLite database for easy querying, analysis, and export.
*   **Test Labelling Capabilities**: Add run tags via the `--run_tag` command-line parameter to database entries, allowing for comparison of different configurations, models, or prompts.
*   **Modular Codebase**: Organized into logical Python modules within the `gar_tool` package for better maintainability.

## Conceptual Overview: Generation Augmented Retrieval (GAR)

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

## Example: Vancouver Public Art Explorer

Let's walk through analyzing Vancouver's public art collection to find First Nations artworks and Instagram-worthy locations.

### Source Data

We start with data about Vancouver's public art. This might originally be in PDF reports, Word documents, or, as in this simplified example, Markdown files. The tool converts PDF/DOCX/PPTX to Markdown internally before processing.

Here's a sample entry (`Fusion.md`):

