# RAG Prism: Batch LLM Extractor Tool

This LLM Extractor Tool helps you extract specific information from large collections of text files and organizes it into a structured database. Whether you're working with data that was once structured but is now in plain text, or you're seeking to derive new insights from unstructured information, this tool is designed to assist you.

## Not Quite RAG: Unfolding Insights, Not Just Answers

This tool was created for a project that originally expected to use RAG. RAG is an acronym for Retrieval-Augmented Generation, a technique for mitigating model hallucinations by grounding models with context information extracted from a variety of source materials relevant to a given question. While the way this tool is used shares similarities with typical RAG applications, it's fundamentally different.

Most people associate RAG with asking a question and having the system fetch relevant documents to help answer it. But what if you already have the questions and need to systematically extract answers from an entire collection of documents? What this tool does can be described as RAG Prism.

Think of it this way:

* **Traditional RAG:** "Hey LLM, here's a question; let me find some relevant documents to help you answer it." (Focuses on answering a specific query with retrieved context.)
* **RAG Prism:** "Hey LLM, here's a document; please answer these standard questions about it." (Focuses on systematically extracting predefined information from each document.)

It's the difference between:

* A librarian who finds specific books to answer your unique question (RAG).
* A researcher who meticulously reads every book and fills out the same detailed questionnaire for each (RAG Prism).

While RAG helps you explore and answer specific queries within your document collection, RAG Prism acts like a prism, refracting your data into structured, actionable insights. It systematically analyzes each document, extracting key information according to your predefined criteria, and organizing it into a database.

**Specifically, RAG Prism:**

* Extracts both originally structured data that may have been lost in plain text conversions (like addresses or titles).
* Constructs new, structured fields from fuzzy descriptions. For example, in our Vancouver Public Art Explorer demo, it identifies First Nations artworks and assigns "Instagrammability" ratings from descriptive text.
* Processes large collections of text files, turning them into a searchable SQLite database.

In essence, RAG Prism doesn't just retrieve; it distills. And, by creating a structured database, it actually *enhances* future RAG capabilities. Imagine being able to ask, "Show me all First Nations artworks rated 8+ for Instagram appeal within 1km of my location," powered by the data RAG Prism has meticulously extracted.

This tool is designed for analysts, researchers, and anyone who needs to transform a collection of text documents into a structured, searchable, and insightful database.

## Key Features

* **Versatile Data Extraction**: Retrieve both clearly defined data (e.g., addresses) and subtle, subjective details inferred from text (e.g., visual appeal ratings).
* **User-Friendly Configuration**: Easily specify what information to extract by editing a simple `config.yaml` file.
* **Support for Multiple Models and Providers**: Compatible with various language models and providers, including options for local deployment to suit different needs.
* **Parallel Processing with Checkpointing**: Process text files in parallel with automatic checkpointing, allowing for interruption and resumption.
* **SQLite Database Storage**: Store results in an SQLite database for easy analysis and export.

## Conceptual Example: Predefined vs. Constructed Properties

The difference between clearly defined data and new, fuzzy fields is important. Imagine you're analyzing crime news articles, and they have clearly presented location and reporter name. But you also want to extract additional details, such as the age range of suspects. Traditional methods might miss this nuanced information, but this tool can identify and extract it effectively.

For instance, from the sentence:

>   "The suspect, described as a man in his late twenties, was seen fleeing the scene."

The tool can extract:

* **Suspect Age Range**: 25-30 years old

This is how this task can be described in the `nodes` section of its configuration:

```yaml
nodes:
  suspect_age_range:
    description: >
      The age range of the suspect mentioned in the report,
      use standard ranges: <18, 18-25, 25-30, 30-40, 40-50, 50-65, 65+.
    format: text
    db_column: suspect_age_range
```

This configuration tells the tool to look for information about the suspect's age range in each text file and store it in a column named suspect_age_range in the database.

This capability is invaluable for researchers, journalists, and analysts who need to gather specific insights from extensive text data. A tool for extracting structured information from text files using Large Language Models (LLMs). Ideal for data analysts and researchers who need to convert unstructured or semi-structured text into analyzable data.

## Example Use Case: Vancouver Public Art Explorer
Let's walk through a complete example of analyzing Vancouver's public art collection to find First Nations artworks and Instagram-worthy locations.

### 1. Source Data
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

### 2. Configuration

**Define the Fields to Extract** in `config.yaml`: Within the `nodes` section of the file, list each piece of information you want to extract. For each field, provide:

   - **description**: A brief explanation of the information, an instruction for LLM of what to look for, and how to express findings.
   - **format**: The type of data (e.g., text, number, boolean).
   - **db_column**: The name of the column in the database where this information will be stored.


By customizing the `config.yaml` file in this way, you can tailor the tool to extract the exact information you need for your analysis.

Here's how to extract in our public art example:

```yaml
name: public_art_vancouver
...

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
Edit the prompt section below with content-specific notes and a description of the role/expertise of the LLM persona.

```
prompt_template: |
 ...
  Do your best to make subjective choices.
  Treat it as a regular resident of the city.
```

### 3. Extraction Process
1. Create `.env` with your OpenRouter API key:
   ```
   OPENROUTER_API_KEY="sk-or-v1-...."
   ```

2. Run the extractor:
You need to have Python installed, with the YAML library.

All configuration parameters are also in `config.yaml`.
Most script-related parameters can be overridden via the command line. See `--help` for details.
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

### 4. Results in SQLite
The data is stored in a SQLite database (`public_art_vancouver.db`):

| name    | address                    | first_nations | first_nations_quote                                      | instagramability |
|---------|----------------------------|---------------|----------------------------------------------------------|------------------|
| Fusion  | 70th Avenue & Cornish St. | 1             | The sculpture is contemporary yet unmistakably Salish... | 7                |

1. Use [DB Browser for SQLite](https://sqlitebrowser.org/) to view and export data as CSV and process in Excel and Google Sheets.
2. The `Chunk` field is used for breaking up large files that exceed the model’s context window, which would be important if your documents are very long, although in this case you may need to rethink your analysis strategy. For sufficiently large context windows of modern models, the entire file fits in a single chunk (`chunk=0`).
   - You can overwrite this field in DB Browser with a comment instead of a number (don't forget to click **Write Changes!**).
   - The script will then treat this file/chunk as unprocessed and run it again.
   - This allows for comparing results across different models.

You can query the database to find interesting artworks:
```sql
SELECT name, address, instagramability 
FROM data 
WHERE first_nations = 1 
ORDER BY instagramability DESC 
LIMIT 10;
```


## Models Suitable for This Task

- `deepseek/deepseek-chat:floor`
- `qwen/qwen-2.5-72b-instruct:floor` (faster and three times cheaper)
- `google/gemini-2.0-flash-001:floor` (similarly cheap, even faster, and often makes better choices)

The `:floor` suffix instructs OpenRouter to use the cheapest providers for the model. You can remove it or use `:nitro` for better speed.

A full list of potentially usable models is available here: [OpenRouter Models](https://openrouter.ai/models).

However, smaller models may fail to follow instructions and might return improperly formatted JSON with extra text. This results in missing data (though the raw model response is still logged in `REQUEST_LOG`).

## Local Models (Optional)

Local models are slower but offer better privacy and no per-use cost. Use [Ollama](https://ollama.com/) for free local processing, if your computer can handle sufficiently powerful models (mine can't, and it's not worth it for public data, as it's cheap to run via APIs).
```bash
python batch_doc_analyzer.py --provider http://localhost:11434/v1 --model deepseek-r1:7b --timeout 60
```
Adjust the model and timeout as needed to ensure it correctly populates the `DATA` table.

## Parallel Execution

The tool processes random files from the source directory until all are completed (i.e., `DATA` table contains records for all file-chunk pairs). You can interrupt it with `Ctrl-C` and resume later.

It appears to run fine with two parallel instances and even while inspecting the database with DB Browser. Editing and saving changes in DB Browser does not interfere with execution.


## Credits

Claude 3.5 Sonnet handled most of the coding, with Google Gemini contributing small portions. Expect potential code problems. This is an analyst's tool, not professional software.

## To-Do

- Handle model response prefixes, such as "Here's the JSON:"
- Include default values in the `--help` output.
- Support direct CSV input
- Clarify `format` field usage

