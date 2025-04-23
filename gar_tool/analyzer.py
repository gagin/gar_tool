import json
import re
import requests
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple

# Use relative imports assuming modules are in the same package
from .config_handler import ExtractorConfig
# Avoid circular import with database_handler, pass db instance where needed
# from .database_handler import Database
from .logging_wrapper import logger


@dataclass
class ProcessingResult:
    """Stores the outcome of processing a single chunk."""
    success: bool
    raw_response: Optional[str] = None
    extracted_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class DocumentAnalyzer:
    """Handles interaction with the LLM and processing of responses."""

    def __init__(self, config: ExtractorConfig):
        self.config = config

    def _make_llm_request(self, content: str) -> Tuple[Optional[str], str]:
        """Sends request to the LLM API and returns the response content and raw text."""
        provider_url = self.config.inconfig_values.provider
        api_key = self.config.key
        model = self.config.inconfig_values.model
        temperature = self.config.inconfig_values.temperature
        timeout = self.config.inconfig_values.timeout
        prompt = self.config.prompt

        headers = {
            "Content-Type": "application/json",
            'HTTP-Referer': 'https://github.com/gagin/batch_doc_analyzer/',
            'X-Title': 'GAR: batch-doc-analyzer' # Optional header
        }
        if not self.config.skip_key_check and api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": content}
            ],
            "temperature": temperature,
            # Add response_format for JSON mode if provider supports it
            # "response_format": {"type": "json_object"}, # Example for OpenAI compatible APIs
        }

        # Remove temperature if it's None or not applicable
        if data["temperature"] is None:
             del data["temperature"]


        logger.debug(f"Sending request to {provider_url} with model {model}")
        full_response_text = "Error: Request not sent"
        try:
            response = requests.post(
                f"{provider_url}/chat/completions",
                headers=headers,
                json=data,
                timeout=timeout
            )
            response.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)

            full_response_text = response.text # Store raw response text
            logger.debug(f"LLM Raw Response Status: {response.status_code}")
            logger.debug(f"LLM Raw Response Body: {full_response_text[:500]}...") # Log excerpt

            response_data = response.json()

            if 'choices' not in response_data or not response_data['choices']:
                logger.warning("LLM response missing 'choices' array or it's empty.")
                return None, full_response_text

            choice = response_data['choices'][0]
            if 'message' not in choice or 'content' not in choice['message']:
                logger.warning("LLM response choice missing 'message' or 'content'.")
                return None, full_response_text

            message_content = choice['message'].get('content')
            if not message_content:
                 logger.warning("LLM response message content is empty.")
                 return None, full_response_text

            return message_content, full_response_text

        except requests.exceptions.Timeout as e:
            logger.error(f"LLM request timed out after {timeout}s: {e}")
            full_response_text = f"Error: Timeout ({timeout}s)"
            return None, full_response_text
        except requests.exceptions.HTTPError as e:
             full_response_text = f"Error: HTTPError - {e.response.status_code} {e.response.reason}. Body: {e.response.text[:500]}..."
             logger.error(f"LLM request failed: {full_response_text}")
             # Log specific provider error messages if available
             try:
                  err_detail = e.response.json().get("error", {}).get("message", "")
                  if err_detail: logger.error(f"Provider error detail: {err_detail}")
             except: pass # Ignore errors parsing error detail
             return None, full_response_text
        except requests.exceptions.RequestException as e:
            logger.error(f"LLM request failed: {e}", exc_info=True)
            full_response_text = f"Error: RequestException - {e}"
            return None, full_response_text
        except json.JSONDecodeError as e:
             logger.error(f"Failed to decode LLM JSON response: {e}. Response text: {full_response_text[:500]}...")
             # Return the raw text, maybe cleaning can salvage it
             return full_response_text, full_response_text
        except Exception as e:
            logger.error(f"Unexpected error during LLM request: {e}", exc_info=True)
            full_response_text = f"Error: Unexpected error - {e}"
            return None, full_response_text


    def _clean_json_response(self, response_text: str) -> Optional[Dict[str, Any]]:
        """Attempts to extract and parse JSON from the LLM response text."""
        if not response_text:
            return None

        text_to_parse = response_text.strip()

        # 1. Check if the entire string is valid JSON
        try:
            return json.loads(text_to_parse)
        except json.JSONDecodeError:
            logger.debug("Raw response is not valid JSON, attempting cleaning.")

        # 2. Try extracting from ```json ... ``` block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text_to_parse, re.DOTALL)
        if match:
            try:
                json_str = match.group(1)
                # Basic sanity check for braces, might need more robust validation
                if json_str.count('{') == json_str.count('}'):
                    logger.debug("Found JSON within ```json block.")
                    return json.loads(json_str)
                else:
                    logger.debug("Mismatched braces in json block.")
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON from ```json block: {e}")
            except Exception as e:
                 logger.warning(f"Error processing json block: {e}")


        # 3. Try extracting JSON enclosed in curly braces (most aggressive)
        start_brace = text_to_parse.find('{')
        end_brace = text_to_parse.rfind('}')
        if start_brace != -1 and end_brace > start_brace:
            potential_json = text_to_parse[start_brace : end_brace + 1]
            try:
                parsed = json.loads(potential_json)
                logger.debug("Successfully parsed JSON via aggressive brace finding.")
                return parsed
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse JSON via aggressive brace finding: {e}")

        logger.error("Failed to extract valid JSON after all cleaning attempts.")
        logger.debug(f"Original text was: {response_text[:500]}...")
        return None


    def _validate_extracted_data(self, json_data: Dict[str, Any]) -> Optional[str]:
         """Checks if required nodes are present in the extracted JSON data."""
         missing_required = []
         for node_name, node_cfg in self.config.node_configs.items():
              is_required = node_cfg.get('required', False)
              if is_required and node_name not in json_data:
                   missing_required.append(node_name)

         if missing_required:
              error_msg = f"Missing required JSON nodes: {', '.join(missing_required)}"
              logger.warning(error_msg)
              return error_msg
         return None # No errors


    def analyze_chunk_content(self, chunk_content: str) -> ProcessingResult:
        """
        Analyzes a chunk of text content using the configured LLM.

        Args:
            chunk_content: The text content of the chunk to analyze.

        Returns:
            A ProcessingResult object containing the outcome.
        """
        if not chunk_content:
            logger.info("Skipping analysis for empty chunk content.")
            return ProcessingResult(
                success=False,
                error_message="Chunk content was empty, skipped LLM call."
            )

        llm_response_content, raw_response = self._make_llm_request(chunk_content)

        if llm_response_content is None:
            return ProcessingResult(
                success=False,
                raw_response=raw_response,
                error_message="LLM request failed or returned no content."
            )

        extracted_data = self._clean_json_response(llm_response_content)

        if extracted_data is None:
            return ProcessingResult(
                success=False,
                raw_response=raw_response,
                error_message="Failed to extract valid JSON from LLM response."
            )

        validation_error = self._validate_extracted_data(extracted_data)
        if validation_error:
             return ProcessingResult(
                  success=False, # Mark as failure if required fields are missing
                  raw_response=raw_response,
                  extracted_data=extracted_data, # Keep partial data for logging
                  error_message=validation_error
             )

        # If we reach here, JSON is valid and required fields are present
        return ProcessingResult(
            success=True,
            raw_response=raw_response,
            extracted_data=extracted_data
        )
