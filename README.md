# GAR: Generation Augmented Retrieval Tool

This tool helps you extract specific information from large collections of text files and organizes it into a structured database, using Large Language Models (LLMs). Whether you're working with data that was once structured but is now in plain text, or you're seeking to derive new insights from unstructured information, this tool is designed to assist you. Ideal for data analysts and researchers who need to convert unstructured or semi-structured text into analyzable data.

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
- [To-Do](#to-do)

## <a id="key-features"></a>Key Features

* **Versatile Data Extraction**: Retrieve both clearly defined data (e.g., addresses) and subtle, subjective details inferred from text (e.g., visual appeal ratings).
* **Single-point Configuration**: Define what to extract and how to store it using a single record in config.yaml. This dual-purpose configuration instructs the LLM and structures the database storage, eliminating the need for separate definitions and making the setup more streamlined.
* **Support for Multiple Models and Providers**: Compatible with various language models and providers, including options for local deployment to suit different needs.
* **Parallel Processing with Checkpointing**: Process text files in parallel with automatic checkpointing, allowing for interruption and resumption.
* **SQLite Database Storage**: Store results in an SQLite database for easy analysis and export.

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
name: public_art_vancouver
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
    db_column: instagramability
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

1. Create `.env` with your OpenRouter API key:
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

| name    | address                    | first_nations | first_nations_quote                                      | instagramability |
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


1. Use [DB Browser for SQLite](https://sqlitebrowser.org/) to view and export data as CSV and process in Excel and Google Sheets.
2. You can overwrite the `Chunk` field in DB Browser with a comment instead of a number (don't forget to click **Write Changes!**).
    * The script will then treat this file/chunk as unprocessed and run it again.
    * This allows for comparing results across different models.

You can query the database to find interesting artworks:
```sql
SELECT name, address, instagramability 
FROM data 
WHERE first_nations = 1 
ORDER BY instagramability DESC 
LIMIT 10;
```

## <a id="tips"></a>Tips for Efficient Field Extraction (Prompt-Engineering)

### Use Boolean Markers

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
**In my tests, the Quote -> Boolean -> Label (QBL) order seemed to work best.**

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

The tool processes random files from the source directory until all are completed (i.e., `DATA` table contains records for all file-chunk pairs). You can interrupt it with `Ctrl-C` and resume later.

It appears to run fine with two parallel instances and even while inspecting the database with DB Browser. Editing and saving changes in DB Browser does not interfere with execution.

## <a id="cli"></a>Command-Line Options

Here are the available command-line options:

```bash
python batch_doc_analyzer.py --help
usage: batch_doc_analyzer.py [-h] [--context_window CONTEXT_WINDOW] [--temperature TEMPERATURE] [--debug_sample_length DEBUG_SAMPLE_LENGTH] [--timeout TIMEOUT] [--data_folder DATA_FOLDER] [--results_db RESULTS_DB]
                            [--config CONFIG] [--max_failures MAX_FAILURES] [--model MODEL] [--provider PROVIDER]

Process data with configurable constants.

options:
  -h, --help            show this help message and exit
  --context_window CONTEXT_WINDOW
                        Context window size (in tokens). Files exceeding this size will be split into chunks.
  --temperature TEMPERATURE
                        Temperature for model generation (0.0 to 1.0). Higher values increase creativity. Defaults to 0 for predictable categorization. DeepSeek recommends 0.6 for more creative tasks.
  --debug_sample_length DEBUG_SAMPLE_LENGTH
                        Maximum length of model response displayed in the console for debugging.
  --timeout TIMEOUT     Timeout (in seconds) for requests to the LLM API.
  --data_folder DATA_FOLDER
                        Path to the directory containing the text files to process (no trailing slash).
  --results_db RESULTS_DB
                        Name of the SQLite database file to store results. If not specified, the project name from config.yaml is used.
  --config CONFIG       Path to the YAML configuration file containing extraction parameters.
  --max_failures MAX_FAILURES
                        Maximum number of failures allowed for a chunk before it is skipped.
  --model MODEL         Name of the LLM to use for analysis (e.g., 'deepseek/deepseek-chat:floor').
  --provider PROVIDER   Base URL of the LLM provider API (e.g., '[https://api.openrouter.ai/v1](https://api.openrouter.ai/v1)'). Defaults to OpenRouter.
```

## <a id="trouble"></a>Troubleshooting

* **Some of my categories are not in the database:**
    * **Check indentation:** Ensure that the indentation of your category definitions in `config.yaml` is aligned with other nodes and that you are using consistent spaces for indentation. Mixing tabs and spaces, or using inconsistent numbers of spaces, will cause nodes to be skipped, resulting in them not appearing in the database. While this may not always result in a visible error message, it will lead to incomplete data extraction.

## <a id="credits"></a>Credits

Claude 3.5 Sonnet handled most of the coding, with Google Gemini contributing small portions. Expect potential code problems. This is an analyst's tool, not professional software. Gemini was also hugely helpful with this document.

## <a id="to-do"></a>To-Do

- Handle model response prefixes, such as "Here's the JSON:"
- Include default values in the `--help` output
- Support direct CSV input
- The `format` field is now shown to the model, but in the db booleans are still created as TEXT
- Use structured outputs for supported models instead of manually prompting models for JSON output https://openrouter.ai/docs/features/structured-outputs
- Process Ctrl-C with a reasonable completion message and summary
- yaml indentation problems are annoying, should I use JSON for config?
- Accept a CLI parameter of how to label this batch in the chunk field, so that comparison test between different orders/prompt versions would be easier?