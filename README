# LLM Extractor Tool

This tool runs a model over multiple text files, extracting structured fields and storing them in a database file.

All configuration parameters, including the structured data to extract, are in `config.yaml`.
Most script-related parameters can be overridden via the command line. See `--help` for details.

Your OpenRouter API key is secret and should be stored in a `.env` file like this:

```
OPENROUTER_API_KEY="sk-or-v1-............................"
```

## Models Suitable for This Task

- `deepseek/deepseek-chat:floor`
- `qwen/qwen-2.5-72b-instruct:floor` (faster and three times cheaper)
- `google/gemini-2.0-flash-001:floor` (similarly cheap, even faster, and often makes better choices)

The `:floor` suffix instructs OpenRouter to use the cheapest providers for the model. You can remove it or use `:nitro` for better speed.

A full list of potentially usable models is available here: [OpenRouter Models](https://openrouter.ai/models).

However, smaller models may fail to follow instructions and might return improperly formatted JSON with extra text. This results in missing data (though the raw model response is still logged in `REQUEST_LOG`).

## Free Local Models

If your machine can run sufficiently powerful local models via [Ollama](https://ollama.com/search), you can use them for free. Example command:

```
--provider http://localhost:11434/v1 --model deepseek-r1:7b --timeout 60
```

Adjust the model and timeout as needed to ensure it correctly populates the `DATA` table.

## Customization

To modify the extracted fields, edit the list of nodes in `config.yaml`. The `description` field in each node guides the model on what to extract.

The `Notes` field is not saved in the database—it acts as a mini chain-of-thought workspace for the model.

## Parallel Execution

The tool processes random files from the source directory until all are completed (i.e., `DATA` table contains records for all file-chunk pairs). You can interrupt it with `Ctrl-C` and resume later.

It appears to run fine with two parallel instances and even while inspecting the database with DB Browser. Editing and saving changes in DB Browser does not interfere with execution.

## Example Project

Sample data comes from a public dataset from Vancouver, BC:

[Public Art Dataset](https://opendata.vancouver.ca/explore/dataset/public-art/information/)

The dataset is originally in CSV format, with some cells containing large text blocks. Since this tool processes plain text files, there is a utility to convert CSV files into the required format.

This example aims to identify public art pieces related to First Nations and those considered "Instagrammable." However, the model struggles with relevance filtering—I need to refine the prompt. This example demonstrates potential applications of the tool.

## Working with Results

1. Use the free [DB Browser for SQLite](https://sqlitebrowser.org/) to open the `.db` file, browse data, and export it to CSV for use in Excel or Google Sheets.
2. The `Chunk` field is used for breaking up large files that exceed the model’s context window. For sufficiently large context windows, the entire file fits in a single chunk (`chunk=0`).
   - You can overwrite this field in DB Browser with a comment instead of a number (don't forget to **Write Changes!**).
   - The script will then treat this file/chunk as unprocessed and run it again.
   - This allows for comparing results across different models.

## Credits

Most of the coding was done by Sonnet 3.5, with some contributions from Gemini. There may be errors—I am not a professional developer, but an analyst.

## To-Do

- Remove the `src` directory name from filenames in the database? (Useful for debugging when testing on different file sets.)
- Handle cases where a model prefixes responses with "Here's your JSON" (e.g., Nemotron does this).
- Improve help documentation to show default values.
- Clarify how the `format` field from YAML nodes is used.
- Support direct reading from CSV sources.

