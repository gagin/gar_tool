# GAR: Generation-Augmented Retrieval Tool

This command-line tool helps you extract specific information from large collections of text files and organizes it into a spreadsheet in a database, using Large Language Models (LLMs). Whether you're working with data that was once structured but is now in plain text, or you're seeking to derive new insights from unstructured information, this tool is designed to assist you. Ideal for data analysts and researchers who need to convert unstructured or semi-structured text into analyzable data.

#DataExtraction #LLM #RetrievalAugmentedGeneration #AI #NLP #MachineLearning #TextProcessing #DataAnalysis #SQLite #Automation #OpenSource #SemanticParsing

## Table of Contents
- [Key Features](#key-features)
- [Conceptual Overview](#conceptual-overview)
- [Example: Vancouver Public Art Explorer](#example)
- [Tips for Efficient Field Extraction (Prompt-Engineering)](#tips)
- [Models](#models)
- [Parallel Execution](#parallel-execution)
- [Command-Line Options](#cli)
- [Troubleshooting](#trouble)
- [Credits](#credits)
- [Alternative Solutions](#alternatives)
- [To-Do](#to-do)

## <a id="key-features"></a>Key Features

* **Explicit and Implicit Data Extraction**: Retrieve both clearly defined data (e.g., addresses) and subtle, subjective details inferred from text (e.g., visual appeal ratings).
* **Single-point Configuration**: Define what to extract and how to store it using a single record in config.yaml. This dual-purpose configuration instructs the LLM and structures the database storage, eliminating the need for separate definitions.
* **Multiple Models and Providers Support**: Compatible with various language models and providers, including options for local deployment to suit different needs.
* **Parallel Processing with Checkpointing**: Process text files in parallel with automatic checkpointing, allowing for interruption and resumption.
* **SQLite Database Storage**: Store results in an SQLite database for easy analysis and export.
* **Test Labelling Capabilities**: Add run tags via command-line parameter to database entries during testing, allowing for comparison of different configurations and detailed analysis.
* **Simplified Design**: Requires no complex LLM frameworks or Pydantic. Relies solely on Python and the `yaml` library (basic indentation knowledge needed). Prioritizes ease of use compared to feature-rich frameworks lacking ready-to-use solutions.

## <a id="conceptual-overview"></a>**Conceptual Overview: Generation Augmented Retrieval (GAR)**

This tool was developed for a project that initially considered Retrieval-Augmented Generation (RAG), a method that enriches language model responses with relevant source documents. However, this tool adopts a fundamentally different approach, focusing on generating structured data to enhance future retrieval. We call this approach **Generation Augmented Retrieval (GAR)**.

Essentially, GAR prioritizes the systematic extraction and organization of data, enabling more sophisticated and efficient future retrieval. In contrast to traditional RAG, which retrieves documents to answer a specific query, GAR uses language models to generate data that can then be retrieved. This "inversion" of the typical RAG flow can be thought of as "Inverse RAG." Another helpful metaphor is the "RAG Prism," where unstructured documents are "refracted" into their component insights, creating structured, searchable data.

Think of it this way:

* **Traditional RAG:** "Here's a question; find relevant documents to help answer it." (Query-driven retrieval)
* **GAR:** "Here's a document; extract these specific pieces of information from it." (Data-driven generation)

Specifically, GAR:

* Extracts data that was originally structured but lost in plain text conversions (e.g., addresses, titles).
* Creates new, structured fields from descriptive text (e.g., categorizing artwork, assigning ratings).
* Processes large text file collections, producing an SQLite database for analysis.

By creating this structured database, GAR enhances future retrieval capabilities. For example, you could then perform complex queries like, "Show me all First Nations artworks with high 'Instagrammability' ratings near my location.

In essence, this tool doesn't just retrieve; it distills. And, by creating a structured database, it actually *enhances* future RAG capabilities. Imagine being able to ask, "Show me all First Nations artworks rated 8+ for Instagram appeal within 1km of my location," powered by the data this tool has meticulously extracted.

## <a id="example"></a>Example: Vancouver Public Art Explorer
Let's walk through a complete example of analyzing Vancouver's public art collection to find First Nations artworks and Instagram-worthy locations.

### Source Data
We start with a public dataset from Vancouver, BC ([Public Art Dataset](https://opendata.vancouver.ca/explore/dataset/public-art/information/)). The dataset is originally in CSV format, with some cells containing large text blocks. Since this tool currently processes plain text files, a utility is provided to convert CSV files into the required text files format.

Here's a sample entry (`Fusion.md`):

```markdown
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
```

### Configuration

**Define the Fields to Extract** in `config.yaml`: Within the `nodes` section of the file, list each piece of information you want to extract. For each field, provide:

   - **description**: A brief explanation of the information, an instruction for LLM of what to look for, and how to express findings.
   - **format**: The type of data (e.g., text, number, boolean).
   - **db_column**: The name of the column in the database where this information will be stored.

Here's how to extract in our public art example:

```yaml
name: public_art_vancouver # This affects how results .db file will be named in the directory 
                           # you run the script. Can be overridden with a command-line option

... # Some configuration is omitted here for brevity, as you typically don't need to change it

nodes:
  art_name:
    description: Name of the art
    format: text
    db_column: name

  location:
    description: Physical address or location of the artwork
    format: text
    db_column: address

  is_first_nations:
    description: Is it a first nations art
    format: boolean
    db_column: first_nations   

  is_first_nations_quote:
    description: >
      Provide a full sentence from the document that was base for determination whether
      it's first nations
    format: text
    db_column: first_nations_quote

  visually_interesting:
    description: How interesting it looks on scale of 0 to 10, as in being instagrammable
    format: number
    db_column: instagrammability
```
> Note: To handle long strings in YAML, which has a practical line width recommendation of 80 characters, the > character after a node name allows you to write multiple indented lines that are then treated as a single, continuous line. This recommendation helps ensure that YAML content remains easily readable without requiring horizontal scrolling or line wrapping on typical displays.
> Also, ensure you use consistent indentation (usually spaces are recommended, although I personally prefer tabs), as mixing tabs and spaces or inconsistent spacing will lead to nodes being skipped or misinterpreted.

**Edit the prompt section** below with content-specific notes and a description of the role/expertise of the LLM persona. The persona you define greatly influences the categorization results. For instance, "instagrammability" ratings will differ if the model acts as a tourist versus an art critic, highlighting the importance of persona selection.

```
prompt_template: |
 ...
  Do your best to make subjective choices.
  Treat it as a regular resident of the city.
```


### Extraction Process

**Prerequisite:** Ensure you have Python installed with the YAML library.

1. Create `.env` with your OpenRouter API key (keep it safe, set a dollar limit on it while generating it in your provider console, e.g., in OpenRouter):
   ```
   OPENROUTER_API_KEY="sk-or-v1-...."
   ```

2. Run the extractor:
   ```bash
   python batch_doc_analyzer.py 
   ```

3. The tool processes each file and generates JSON responses:
   ```json
   {
     "art_name": "Fusion",
     "location": "70th Avenue & Cornish Street",
     "is_first_nations": true,
     "is_first_nations_quote": "The sculpture is contemporary yet unmistakably Salish.",
     "visually_interesting": 7
   }
   ```

### Results in SQLite
The data is stored in a SQLite database (`public_art_vancouver.db`):

| name    | address                    | first_nations | first_nations_quote                                      | instagrammability |
|---------|----------------------------|---------------|----------------------------------------------------------|------------------|
| Fusion  | 70th Avenue & Cornish St. | 1             | The sculpture is contemporary yet unmistakably Salish... | 7                |

> **Note on the `Chunk` Field:** The `Chunk` field is used for breaking up large files that exceed the model's configured context window. This is important when your documents are very long, requiring them to be processed in smaller segments. In such cases, each segment is assigned a sequential chunk number.
>
> **Important Considerations for Context Windows:**
>
> * **Configuration-Based:** The context window size is set within your configuration (and can be overridden via the command-line, see `--help`). It's *not* automatically determined by the model.
> * **Model Limitations:** You must ensure your chosen model has a sufficient context window to handle the configured size. Not all models perform well with very large context windows.
> * **Decreasing Recall:** For *larger* context windows, models experience a decrease in "recall percentage" (the ability to accurately retrieve information). This means the likelihood of missing information increases as the context window grows.
> * **Analysis Strategy:** If your documents are consistently exceeding the context window, you may need to rethink your analysis strategy. For example, if critical fields are always at the top of the file, you might adjust your chunking approach.
>
> However, with sufficiently large context windows of modern models, the entire file often fits within a single chunk (`chunk=0`).


### Managing Data

1. View and Export Data
   * Use [DB Browser for SQLite](https://sqlitebrowser.org/) to examine your data
   * Export results as CSV for analysis in Excel or Google Sheets

2. Modifying Run Tags
   * Edit the `run_tag` field directly in DB Browser 
   * Remember to click "Write Changes" to save your modifications
   * Use tags for:
     * Adding post-processing comments
     * Organizing different test runs
     * Grouping related entries


You can query the database to find interesting artworks:
```sql
SELECT name, address, instagrammability 
FROM data 
WHERE first_nations = 1 
ORDER BY instagrammability DESC 
LIMIT 10;
```

**Note on Boolean Comparisons:** Even though boolean values are stored as TEXT in the database, SQLite's dynamic typing allows you to use boolean-like comparisons (e.g., `WHERE first_nations = TRUE`). SQLite may perform implicit type conversions during comparisons.

## <a id="tips"></a>Tips for Efficient Field Extraction (Prompt-Engineering)

### Use Boolean Markers for Applicability

Before extracting a specific label, it's beneficial to first determine if the label is applicable. By configuring the model to assess applicability with a yes/no question, you encourage it to focus on relevant labels and reduce the chance of generating incorrect information. This approach is also highly useful for subsequent analysis in SQL, as it allows for efficient filtering and querying of data based on the presence or absence of specific attributes.

### Order Fields Strategically
LLMs process information in sequence, and this significantly affects their output quality. Every next word it generates becomes an input for next word generation. Research confirms that changing the order of requested fields can dramatically impact accuracy. Use this to your advantage.

#### Break Down Complex Labels Into Multiple Fields
Instead of requesting a single label, consider using multiple related fields that build upon each other. For example, when identifying artwork characteristics, you might want:
- A boolean flag for presence
- Supporting evidence (quotes from source)
- The actual classification

This multi-field approach helps validate extractions and provides traceable reasoning for downstream analysis.

#### Experiment with Field Order
LLMs process information sequentially, and their performance can vary significantly based on field order. While there’s no universal “best” sequence, consider testing different arrangements:
- Boolean -> Quote -> Label
- Quote -> Boolean -> Label
- Boolean -> Label -> Quote

Your optimal sequence may depend on your specific use case, document structure, and model capabilities. Measure accuracy with different orderings on a sample of your data.
In my initial tests, the Quote -> Boolean -> Label (QBL) order seemed to work best, and that makes logical sense.

##### Using `--run_tag` for Comparison Tests

The `--run_tag` argument allows you to add a run_tag to each record in the results database. This is particularly useful for comparing the effects of different field orders, models, or prompt variations.

For example, you could run the script multiple times with different configurations, using a unique tag for each run:

```bash
python batch_doc_analyzer.py --config qbl.yaml --run_tag "QBL Order" --results_db comparison.db
python batch_doc_analyzer.py --config blq.yaml --run_tag "BLQ Order" --results_db comparison.db
python batch_doc_analyzer.py --config lqb.yaml --run_tag "LQB Order" --results_db comparison.db
python batch_doc_analyzer.py --config qbl.yaml --temperature 1 --run_tag "QBL Temp1" --results_db comparison.db
```
**Note:** Ensure that the configuration files (`qbl.yaml`, `blq.yaml`, `lqb.yaml`) have the exact same columns configured. If the columns do not match, the script will fail because the database schema will not be compatible. The `--results_db` argument is used to specify the output database. It is used here to show that the database name can be changed, and that comparison results can be put in a dedicated file. If all the configs have the same project name, this argument is not needed, and the results will be put in a database named after the project.

The script can only create duplicates of the same file and chunk if they have different run_tags. This allows you to easily compare the results of each run by querying the database using the run_tag as a filter.

**Important**: If you intend to run configurations with different sets of columns (i.e., different schema), please refer to the <a href="#parallel-execution">Parallel Execution section</a> regarding the use of separate database files to avoid conflicts and data corruption.

#### Consider interplay between fields
Consider both the order of fields within a single label and the sequence of different labels. For example, when analyzing public art:

- First Nations identification might affect local relevance assessment
- Both cultural aspects could influence perceived “instagrammability”
Test different sequences to find what works best for your use case.

### Normalize Output Format
For effective analysis, it's crucial that extracted data is consistent in format and content. Providing clear instructions on standardizing outputs ensures uniformity across the dataset.

Explicitly specify formatting requirements:

- Target language for text fields
- Gender and number for languages with grammatical gender
- Standard categories or ranges for classifications
- When asking the model for a free-form category, still provide explicit formatting instructions, such as "Capitalize the word, use a noun in singular form." This prevents inconsistencies like mixing "History" and "historic"
- Target length for text responses

Example:

When categorizing age groups:

```yaml
age_category:
  description: >
   Classify the age of the speaker into one of the following categories:
   0-18, 19-35, 36-50, 51+
  format: text
  db_column: age_category
```
Defining specific categories helps in maintaining consistency, facilitating easier analysis and comparison.

### Be Cautious with Example Prompts

Providing examples can guide the model, but they also have a risk. Less capable models might simply copy the labels from your examples, instead of actually analyzing the content. This means you get outputs that look like your examples, even if they're not correct for your data.

Here's how to manage this:

* **If you want to give examples, giving several reduces chances of overfitting:** Providing multiple examples can help the model generalize better, but be aware that it still might overfit.
* **Focus on the Format:** Show the model the *type* of output you want (e.g., "date in YYYY-MM-DD format," "numerical rating from 1 to 5"), rather than relying solely on specific answer examples (unless you're providing a set list of categories).
* **Check Your Results Carefully:** Review the model's output on a variety of inputs to ensure it's analyzing the data correctly, not just copying examples. If you see it repeating your examples, adjust your prompts or use a stronger model.

By keeping a close eye on how your model uses examples, you can make sure it's doing real analysis.

### <a id="models"></a>Models Suitable for This Task

- `deepseek/deepseek-chat:floor`
- `qwen/qwen-2.5-72b-instruct:floor` (faster and three times cheaper)
- `google/gemini-2.0-flash-001:floor` (similarly cheap, even faster, and often makes better choices)

The `:floor` suffix instructs OpenRouter to use the cheapest providers for the model. You can remove it or use `:nitro` for better speed.

A full list of potentially usable models is available here: [OpenRouter Models](https://openrouter.ai/models).

However, smaller models may fail to follow instructions and might return improperly formatted JSON with extra text. This results in missing data (though the raw model response is still logged in `REQUEST_LOG` table).

### Local Models (Optional)

Local models are slower but offer better privacy and no per-use cost. Use [Ollama](https://ollama.com/) for free local processing, if your computer can handle sufficiently powerful models (mine can't, and it's not worth it for public data, as it's cheap to run via APIs).
```bash
python batch_doc_analyzer.py --provider http://localhost:11434/v1 --model deepseek-r1:7b --timeout 60
```
Adjust the model and timeout as needed to ensure it correctly populates the `DATA` table.

## <a id="parallel-execution"></a>Parallel Execution

Parallel execution is an important consideration, especially when working with large file sets. The tool picks files in no particular order from the source directory until all are completed (i.e., `DATA` table contains records for all file-chunk pairs with the current `--run_tag` label). You can interrupt it with `Ctrl-C` and resume later.

If the script tries to write to the database and finds it locked by other instance, it will try for 5 seconds. With quick writes and long waits for LLM concurrent database access doesn't seem to be a realistic problem. Even editing and saving changes in DB Browser does not interfere with execution if done quickly enough. The problem arises when several copies of the script randomly pick the same file for processing. They don't know about each other, so as a result DATA will have duplicate successful extraction for that piece+chunk. It's something that will be addressed later.

**Also:**

* **AI Code:** This code was generated by AI, so I'm not certain on consistency.
* **Database Locking:** If you edit the database with DB Browser, remember to "Write Changes." to remove its lock on the database file.
* **Column Changes:** Do not add or remove columns in the database during a run or between runs of the same configuration. The tool relies on specific column names and structures, partially hardcoded and partially defined in the configuration file, and any alterations will certainly cause it to fail.
* **Config Changes:** If you change the node list in the configuration, use a new results database file. Mixing different configurations with the same results database can lead to unexpected behavior and data corruption.
* **Testing:** It's recommended to test the tool on a subset of files first, especially when running multiple instances. To do this, copy a small subset of your source files to a separate directory and use the `--data_folder` command-line parameter to specify that directory.

## <a id="cli"></a>Command-Line Options

Here are the available command-line options:

```bash
python batch_doc_analyzer.py --help               
usage: batch_doc_analyzer.py [-h] [--config CONFIG] [--llm_debug_excerpt_length LLM_DEBUG_EXCERPT_LENGTH] [--log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL}] [--version]
                             [--data_folder DATA_FOLDER] [--chunk_size CHUNK_SIZE] [--results_db RESULTS_DB] [--model MODEL] [--provider PROVIDER] [--skip_key_check]
                             [--temperature TEMPERATURE] [--run_tag RUN_TAG] [--timeout TIMEOUT] [--max_failures MAX_FAILURES]

This command-line tool extracts specific information from large collections of text files and organizes it into a spreadsheet within a database, using Large Language Models (LLMs). It's designed to assist with data that was once structured but is now in plain text, or when deriving new insights from unstructured information. Ideal for data analysts and researchers who need to convert unstructured or semi-structured text into analyzable data.

options:
  -h, --help            show this help message and exit

Script control:
  --config CONFIG       Path to the YAML configuration file containing extraction parameters (default: config.yaml).
  --llm_debug_excerpt_length LLM_DEBUG_EXCERPT_LENGTH
                        Maximum length (in characters) of LLM response excerpts displayed in debug logs (default: 200).
  --log_level {DEBUG,INFO,WARNING,ERROR,CRITICAL}
                        Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) (default: INFO).
  --version             Show program's version number and exit.

Input and output (command line overwrites values from configuration YAML file):
  --data_folder DATA_FOLDER
                        Path to the directory containing the text files to process.
  --chunk_size CHUNK_SIZE
                        Chunk size (in characters). Files exceeding this size will be split into chunks. The combined chunk and prompt must fit within the model's context window (measured in tokens, not characters). Token length varies by language. See the README for details.
  --results_db RESULTS_DB
                        Name of the SQLite database file to store results. Be careful, the extension '.db' is not added automatically. If this argument is not specified, the project name from the YAML configuration file is used.

AI parameters (command line overwrites values from configuration YAML file):
  --model MODEL         Name of the LLM to use for analysis (e.g., 'deepseek/deepseek-chat:floor').
  --provider PROVIDER   Base URL of the LLM provider API (e.g., 'https://api.openrouter.ai/v1'). Default: OpenRouter.
  --skip_key_check      Skip API key check (use for models that don't require keys, or set OPENROUTER_API_KEY in .env to any non-empty value).
  --temperature TEMPERATURE
                        Temperature for model generation (0.0 to 1.0). Higher values increase creativity. A value of 0 is recommended for predictable document processing.

Run parameters (command line overwrites values from configuration YAML file):
  --run_tag RUN_TAG     Tags records in the DATA table's 'run_tag' column with a run label for comparison testing (allowing duplication of file and chunk combinations). Use this to differentiate runs based on model name, field order, temperature, or other variations. Default: file name of the YAML configuration.
  --timeout TIMEOUT     Timeout (in seconds) for requests to the LLM API.
  --max_failures MAX_FAILURES
                        Maximum number of consecutive failures allowed for a chunk before it is skipped.
```

## <a id="trouble"></a>Troubleshooting

* **Some of my categories are not in the database:**
    * **Check indentation:** Ensure that the indentation of your category definitions in `config.yaml` is aligned with other nodes and that you are using consistent spaces for indentation. Mixing tabs and spaces, or using inconsistent numbers of spaces, will cause nodes to be skipped, resulting in them not appearing in the database. While this may not always result in a visible error message, it will lead to incomplete data extraction.
* **Too few results rows in the database:**
    * **Inspect the `REQUEST_LOG` table:** If you're seeing too few rows in the `DATA` table, check the `REQUEST_LOG` table for errors or incomplete responses from the LLM. This can help identify if the model is failing to process certain files or chunks.

## <a id="credits"></a>Credits

Claude 3.5 Sonnet handled most of the coding, with Google Gemini contributing small portions. Expect potential code problems. This is an analyst's tool, not professional software. Gemini was also hugely helpful with this document.

## <a id="alternatives"></a>Alternative Solutions

### Web UI apps for the Exact Same Use Case

* **Extracta.ai:** [Extracta.ai](https://extracta.ai/extract-data-from-pdf-to-excel-using-ai/) offers a web UI-based solution for data extraction, targeting the same use case as this project. Users can upload batches of files, define fields, and view extracted results in a table. For reference, the field descriptions used with Extracta.ai were derived from the configuration used in this project. Screenshots of the Extracta.ai UI and an example CSV export (run over the same data as our demo) are available in the `competitors_extracta.ai` folder. While convenient, the web-based nature and limited control over configuration compared to local file management and version control make our tool preferable for projects requiring reproducible results and configurable prompts.

* **ExtractNinja:** [ExtractNinja](https://extractninja.org/) is another web UI-based platform for data extraction, with a similar interface and feature set to Extracta.ai. 

### Developer Frameworks

* **KatanaML/Sparrow**: Sparrow ([GitHub](https://github.com/katanaml/sparrow)) is an open-source solution focused on vision-language models (VLMs - models that understand both images and text) and local LLM execution. For streamlined bulk LLM extraction from a large collection of similarly structured text files, its setup and configuration requirements are unclear from a quick glance. Their UI ([https://sparrow.katanaml.io/](https://sparrow.katanaml.io/)) can give you a sense of its capabilities, but full access requires an API key. Local installation is an option for users comfortable managing virtual environments and heavy packages.

* **LlamaIndex:** For developers seeking a more programmatic approach, LlamaIndex ([LlamaIndex Documentation](https://docs.llamaindex.ai/en/stable/understanding/extraction/)) offers tools for structured output extraction. Our script could have been built on it. However, it provides a framework rather than a ready-to-use solution, requiring further development and integration to achieve a complete extraction pipeline.

### Enterprise-Level Solutions

* **Altair Monarch:** [Monarch](https://web.altair.com/monarch-free-trial) is an enterprise-level self-service data preparation tool designed for business users. It connects to various data sources (PDFs, spreadsheets, databases, cloud data, big data) and provides functions to prepare and transform data from disparate sources into rows and columns for use in reporting and analytics.

* **Google Cloud Document AI:** Google Cloud Document AI ([cloud.google.com/document-ai](https://cloud.google.com/document-ai)) is another enterprise-grade solution targeting this use case, among others.

## <a id="to-do"></a>To-Do

- **Use structured model output where possible:** We should also explore using [structured outputs](https://platform.openai.com/docs/guides/function-calling) for models that support them for better reliability and potentially fewer tokens / lower cost. Right now, our JSON prompting works and supports more models (including local ones). 
- **Show defaults in `--help`:** Make the `--help` output show default values for command-line options.
- **Direct CSV input:** Let users input CSV files directly, without needing to convert them to text first.
- **Database Schema Type Consistency:** Ensure that the database schema is created using the type declarations from the `config.yaml` file. Currently, all fields are stored as TEXT, even when `format` specifies other types (e.g., number, boolean). While SQLite's dynamic typing allows for some flexibility in queries, maintaining schema consistency will improve data integrity and clarity.
- **YAML vs. JSON for config:** YAML indentation is annoying and leads to unexpected behavior (see Troubleshooting). Should we switch to JSON for the config file?
- **Default db_column to Node Name:** Make clear that if `db_column` node isn't present, it will not be recorded to `DATA`. But to avoid repeated typing, allow it to be left empty, and then the node name should be used.

### Unstructured and not thought through notes and ideas on further improvements

#### Documentation improvements
- update example workflow with latest prompt structure
- reordering test - make sure the descriptions don't refer to previous nodes, as reordering will confuse it
- instead, move common descriptions to generic prompt rather than repeat it in b,q,l
- if there are formatting rules for several fields, you can put them to the overall prompt with persona info (update example according to latest config structure)
- order is important mostly for deduced fields
- tell about a case where models hallucinate an amount field in case where it has a privacy placeholder - despite all my attempts to avoid it; a solution is still unclear
- explain prompts parts - why do i instruct about alternative world and placeholders
- rewrite your prompt with sota models
- boolean: 1, yes or true - tell the model notation to use
- universal value for not found - tell the model notation to use
- Ask the model to do things rather than avoid things (instead of don't hallucinate, say ground answers in the document provided and ignore coincidences with real world)
- advisable to have single-doc directory in default config.yaml, and provide full directory via --data_folder to avoid costs on mistakenly triggered runs
- version_update, pre-commit and install_hooks - don't worry about it unless you change the script and want to have auto-increments to version
- In our approach is document is fed to LLM independently, thus ignoring information that is in commonality between files. For a human eyes, extracting fields from several files will result in next ones being processed faster and with better quality. It unclear though how to technically achieve a similar effect with a model. Idea: after each call, do another call with full response csv (current run or length-limited total) and ask model either to normalise, or to provide a feedback on the last addition if needed - and if there is a feedback, rerun extraction model with this comment. Sounds as a fun agentic trick, worthy to implement just for kicks. Even though it doesn't fully solve the original problem. Another agentic trick - first feeds several documents at once to a strong model with our prompt and ask for prompt improvements based on similarity of these documents, and use the improved one.
- explain that run_tag defailts to config file name, and how it can be used for model name and other parameters

### Technical
- do i want to keep folder name? additional field without folder name for test, so same file in different test folder can be easily identified?
- implement multi-run with N of M?
- investigate Error processing chunk: Invalid \escape: (happened when original doc had several backslashes as a placeholder, and then model was returning it and did not escape properly)
- --structured_output=true/false/test with test is default
- Make a temp table where script instances will register which piece they picked up for processing - this way it'll be much less likely to pick same piece multiple times, as it happens now when between random pick and record there's LLM response wait time
- support usage of free versions of the models until the daily limit exceeded


