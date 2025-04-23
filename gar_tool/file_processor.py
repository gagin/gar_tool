import os
import re
from typing import List, Tuple

try:
    import markitdown
except ImportError:
    print(
        "Warning: 'markitdown' library not found. "
        "PDF/DOCX/PPTX conversion will be unavailable."
    )
    print("Install it using: pip install markitdown-python")
    markitdown = None

from .logging_wrapper import logger


def get_text_content(filepath: str) -> str:
    """
    Reads or converts a file to text content (Markdown for supported types).

    Args:
        filepath: Path to the file.

    Returns:
        The text content of the file, or an empty string if conversion fails
        or the format is unsupported. Returns None if file not found.
    """
    if not os.path.exists(filepath):
        logger.error(f"File not found: {filepath}")
        return None # Indicate file not found distinctly from empty file

    _, extension = os.path.splitext(filepath)
    extension = extension.lower()

    try:
        if extension in ['.md', '.txt']:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        elif markitdown and extension in ['.pdf', '.docx', '.pptx']:
            logger.debug(f"Converting {filepath} using markitdown...")
            try:
                # Instantiate the MarkItDown class
                # Keep plugins disabled for predictability unless needed
                md_converter = markitdown.MarkItDown(enable_plugins=False)

                # Call the convert method on the instance
                result = md_converter.convert(filepath)

                # Access the text content from the result object
                markdown_content = result.text_content

                # Check if conversion actually produced content
                if markdown_content is None:
                     logger.warning(f"Markitdown conversion resulted in None content for {filepath}.")
                     markdown_content = "" # Treat None as empty string
                elif not isinstance(markdown_content, str):
                     logger.warning(f"Markitdown conversion did not return a string for {filepath} (type: {type(markdown_content)}). Treating as empty.")
                     markdown_content = ""


                logger.debug(f"Conversion successful for {filepath}. Content length: {len(markdown_content)}")
                return markdown_content
            except Exception as conversion_error:
                # Catch potential markitdown instantiation or conversion errors
                logger.error(f"Markitdown conversion failed for {filepath}: {conversion_error}", exc_info=False)
                if logger.get_log_level_name() == "DEBUG":
                    logger.exception("Full traceback for markitdown conversion error:")
                return "" # Return empty string on error
        else:
            if not markitdown and extension in ['.pdf', '.docx', '.pptx']:
                logger.error(
                    f"Cannot process {filepath}: "
                    "markitdown library is not available."
                )
            else:
                logger.warning(
                    f"Unsupported file format '{extension}' for {filepath}. "
                    "Skipping."
                )
            return ""
    except UnicodeDecodeError:
        logger.error(
            f"Could not decode {filepath} as UTF-8. "
            "Ensure file is UTF-8 encoded."
        )
        return ""
    except Exception as e:
        logger.error(
            f"Failed to read or convert file {filepath}: {e}", exc_info=False
        )
        if logger.get_log_level_name() == "DEBUG":
            logger.exception("Full traceback for conversion/read error:")
        return ""


def calculate_chunks(
    text_content: str, chunk_size: int
) -> List[Tuple[int, int]]:
    """
    Calculates character-based chunk boundaries for the given text content,
    attempting to split at sentence endings or structural markdown elements.

    Args:
        text_content: The text content to chunk.
        chunk_size: The target maximum size for each chunk in characters.

    Returns:
        A list of (start_index, end_index) tuples for each chunk.
    """
    if not text_content:
        return []

    content_len = len(text_content)
    if content_len <= chunk_size:
        return [(0, content_len)]

    chunks = []
    start = 0
    safety_counter = 0
    max_safety_count = content_len + 100 # Prevent infinite loops

    while start < content_len and safety_counter < max_safety_count:
        safety_counter += 1
        potential_end = min(start + chunk_size, content_len)
        window = text_content[start:potential_end]

        # Regex to find sentence endings or markdown structural elements
        # Prioritize double newlines, then single newlines near the end,
        # then sentence punctuation, then markdown list/headers.
        # Use reversed finditer to get the *last* suitable split point.
        split_point = -1
        # Look for double newline first (paragraph break)
        matches = list(re.finditer(r'\n\s*\n', window))
        if matches:
             # Take the end of the last double newline sequence
             split_point = start + matches[-1].end()

        # If no double newline, look for single newline near the end
        if split_point == -1:
            matches = list(re.finditer(r'\n', window))
            if matches:
                 # Prefer newline closer to the end of the window
                 split_point = start + matches[-1].end()

        # If still no newline, look for sentence terminators
        if split_point == -1:
             # Find last sentence terminator followed by space or end of window
             matches = list(re.finditer(r'[\.\!\?]\s|[\.\!\?]$', window))
             if matches:
                 split_point = start + matches[-1].end()

        # If still no good split point, consider markdown elements
        if split_point == -1:
             matches = list(re.finditer(r'\n\s*([\-\*\#]+\s|\d+\.\s)', window))
             if matches:
                  # Split *before* the markdown element starts
                  split_point = start + matches[-1].start()


        # Determine the final end point for the chunk
        if split_point > start:
             end = split_point
        else:
             # If no suitable boundary found, or only at the very start,
             # take the full window potential_end to ensure progress.
             end = potential_end

        # Ensure end is strictly greater than start if possible, unless at end
        if end <= start and start < content_len:
             end = potential_end # Force progress if stuck


        # Add the chunk
        # print(f"Chunk: ({start}, {end}) Len: {end-start}") # Debug print
        chunks.append((start, end))

        # Prepare for the next iteration
        start = end

    if safety_counter >= max_safety_count:
         logger.error("Chunk calculation safety limit reached. Check for loops.")

    # Final check: ensure the last chunk reaches the end of the content
    if chunks and chunks[-1][1] < content_len:
        last_start = chunks[-1][1]
        chunks.append((last_start, content_len))
    elif not chunks and content_len > 0:
         # Handle case where loop didn't run but content exists (shouldn't happen)
         chunks.append((0, content_len))


    return chunks
