# gar_tool/analyzer.py

# --- Imports needed for DocumentAnalyzer ---
import requests
import json
import re
from typing import Tuple, Optional

# --- Imports needed from other modules in your package ---
from .logging_wrapper import logger
from .config_handler import ExtractorConfig
from .database_handler import Database
from .processing_result import ProcessingResult
from .helpers import signal_received

class DocumentAnalyzer:
    def __init__(self, config: ExtractorConfig, db: Database):
        self.config = config
        self.db = db

    def get_llm_response(self, content: str, prompt: str) -> Tuple[Optional[str], str]:
        global signal_received
        if signal_received:
            return None, "Request skipped due to interrupt."

        try:
            headers = {
                #"Authorization": f"Bearer {self.config.key}",
                "Content-Type": "application/json",
                'HTTP-Referer': 'https://github.com/gagin/batch_doc_analyzer/',
                'X-Title': 'GAR: batch-doc-analyzer'
            }
            if not self.config.skip_key_check:
                headers["Authorization"] = f"Bearer {self.config.key}"
                
            data = {
                "model": self.config.inconfig_values.model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": content}
                ],
                "temperature": self.config.inconfig_values.temperature
            }

            response = requests.post(
                f"{self.config.inconfig_values.provider}/chat/completions",
                headers=headers,
                json=data,
                timeout=self.config.inconfig_values.timeout
            )

            response.raise_for_status()

            if signal_received:
                return None, "Request interrupted after response, during processing"

            logger.debug(f"Status code: {response.status_code}")
            logger.debug(f"Raw response: {response.text.strip()}")

            if not response.text.strip():
                return None, ""

            response_data = response.json()

            if 'choices' not in response_data or not response_data['choices']:
                return None, json.dumps(response_data)

            choice = response_data['choices'][0]
            if 'message' not in choice or 'content' not in choice['message']:
                return None, json.dumps(response_data)

            return choice['message']['content'], json.dumps(response_data)

        except requests.exceptions.HTTPError as e:
            error_message = None
            try:
                error_message = f". Error message: {e.response.json().get('error', {}).get('message')}"
            except:
                pass #Ignore any error during json parsing.
            logger.error(f"HTTP error making request to {self.config.inconfig_values.provider}: {e}{error_message or ''}")
            return None, f"Request error: {e}{error_message or ''}"
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making request to {self.config.inconfig_values.provider}: {e}")
            return None, f"Request error: {e}"
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON response: {e}")
            return None, f"JSON decode error: {e}"
        except KeyError as e:
            logger.error(f"KeyError in JSON response: {e}")
            return None, f"Key error: {e}"
        except requests.exceptions.HTTPError as e:
            logger.exception(f"HTTP Error: {e}")
            return None, f"HTTP Error: {e}"
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            return None, f"Unexpected error: {e}"
        

    def _aggressive_json_cleaning(self, response: str) -> str:
        """Attempts aggressive ```json extraction."""
        match = re.search(r"```json\s*([\s\S]*?)\s*```", response)
        if match:
            try:
                json_string = match.group(1).strip()
                json.loads(json_string)  # Just check if it's valid JSON
                logger.debug("Aggressive JSON extraction from ```json block successful.")
                return json_string
            except json.JSONDecodeError as e:
                logger.debug(f"Aggressive JSON decode error: {e}. Raw response: {response}")
                return response  # Return original response if aggressive cleaning fails
            except Exception as e:
                logger.error(f"Unexpected error during aggressive ```json extraction: {e}")
                return response  # Return original response on any other exception
        else:
            return response  # Return original response if no ```json block is found

    def _super_aggressive_json_cleaning(self, response: str) -> str:
        """Attempts super-aggressive curly braces cleaning."""
        try:
            start = response.find('{')
            end = response.rfind('}')
            if start != -1 and end != -1:
                super_aggressive_cleaned_response = response[start:end + 1]
                try:
                    json.loads(super_aggressive_cleaned_response)
                    logger.debug("Super-aggressive JSON cleaning helped.")
                    logger.debug(f"Super-aggressively cleaned response: {super_aggressive_cleaned_response}")
                    return super_aggressive_cleaned_response
                except json.JSONDecodeError as e:
                    logger.error(f"Super-aggressive JSON cleaning failed: {e}. Raw response: {response}")
                    return response
            else:
                logger.warning("Could not find JSON braces in the response.")
                return response
        except Exception as e:
            logger.error(f"Unexpected error during super-aggressive cleaning: {e}")
            return response


    def clean_json_response(self, response: str) -> Optional[dict]: # -> str:
        """Cleans the LLM response to extract JSON, using aggressive and super-aggressive cleaning as fallbacks."""

        if not response:
            return response

        try:
            cleaned_response = re.sub(r'^```json\s*', '', response.strip(), flags=re.MULTILINE)
            cleaned_response = re.sub(r'^```\s*', '', cleaned_response, flags=re.MULTILINE)
            cleaned_response = re.sub(r'\s*```$', '', cleaned_response, flags=re.MULTILINE)
            cleaned_response = cleaned_response.strip()
            return json.loads(cleaned_response)
            # return cleaned_response
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug(f"Initial JSON decode error: {e}. Response: {response}")

            # Attempt aggressive cleaning
            aggressive_cleaned = self._aggressive_json_cleaning(response)  # Call aggressive cleaning
            try:
                json_response = json.loads(aggressive_cleaned)
                logger.debug("Aggressive cleaning succeeded.")
                return json_response
            except json.JSONDecodeError as e:
                logger.debug(f"Aggressive cleaning failed: {e}. Aggressively cleaned response: {aggressive_cleaned}")

                # Attempt super-aggressive cleaning
                super_aggressive_cleaned = self._super_aggressive_json_cleaning(response) # Call super-aggressive cleaning
                try:
                    json_response = json.loads(super_aggressive_cleaned)
                    logger.debug("Super-aggressive cleaning succeeded.")
                    return json_response
                except json.JSONDecodeError as e:
                    logger.warning(f"All cleaning attempts failed, even super-aggressive: {e}. Super-aggressively cleaned response: {super_aggressive_cleaned}")
                    return None  # Return None only after all attempts fail

        except Exception as e:
            logger.error(f"Unexpected error during JSON cleaning: {e}. Response: {response}")
            return None  # Return None on any other exception

    def process_chunk(self, db: Database, filename: str, chunk_number: int, chunk_content: str) -> bool:
        """Invokes LLM call function, processes response, and attempts to log/store results."""
        # Initialize result assuming failure until success is proven
        result = ProcessingResult(success=False, raw_response="", error_message="Processing not completed")
        request_id = -1 # Default request_id indicating logging hasn't happened or failed

        # --- Stage 1: Handle Empty Content ---
        if not chunk_content:
            logger.warning(f"Chunk {chunk_number} for file {filename} has empty content. Skipping LLM call.")
            result.error_message = "Chunk content was empty, skipped LLM call."
            # Attempt to log this specific failure state
            try:
                # We still call log_request to record the attempt and the reason for skipping
                db.log_request(filename, chunk_number, result)
            except Exception as log_err:
                # Log error if logging the empty state fails, but don't stop the whole script
                logger.error(f"Failed to log empty chunk state for chunk {chunk_number} of {filename}: {log_err}")
            return False # Indicate failure/skip for this chunk

        # --- Stage 2: LLM Interaction and Response Processing ---
        try:
            response, full_response = self.get_llm_response(
                content=chunk_content,
                prompt=self.config.prompt
            )
            result.raw_response = full_response # Store raw response early

            if response is None:
                # LLM call failed or returned nothing, error message might be in full_response
                result.error_message = f"LLM request failed or returned empty response. Raw details: {full_response}"
                # Proceed to Stage 3 to log this failure
            else:
                # Attempt to clean and validate JSON
                json_response = self.clean_json_response(response)

                if json_response is None:
                    result.error_message = "Failed to extract valid JSON from LLM response."
                    # Proceed to Stage 3 to log this failure
                else:
                    # Validate required nodes
                    missing_required_nodes = [
                        node for node_name, node_config in self.config.node_configs.items()
                        if node_config.get('required', False) and node_name not in json_response
                    ]

                    if missing_required_nodes:
                        result.error_message = f"Missing required JSON nodes: {', '.join(missing_required_nodes)}"
                        result.extracted_data = json_response # Keep partial data for logging
                        # Proceed to Stage 3 to log this failure
                    else:
                        # --- Success Point for LLM/JSON Processing ---
                        result.success = True
                        result.extracted_data = json_response
                        result.error_message = None # Clear error message on success
                        # Proceed to Stage 3 to log success and store data

        except Exception as processing_error:
            # Catch unexpected errors during LLM call or JSON handling
            logger.error(f"Unexpected error during LLM/JSON processing for chunk {chunk_number} of {filename}: {processing_error}", exc_info=True)
            result.success = False
            # Try to capture the error, raw_response might not be set if get_llm_response failed early
            if not result.raw_response:
                result.raw_response = f"Processing error before full response: {processing_error}"
            result.error_message = f"Unexpected processing error: {processing_error}"
            # Proceed to Stage 3 to log this failure

        # --- Stage 3: Database Operations (Logging and Storing) ---
        db_success = False # Track success of database operations separately
        try:
            # Always attempt to log the outcome (success or failure) from Stage 2
            request_id = db.log_request(filename, chunk_number, result)

            if request_id == -1:
                # Logging failed, db.log_request should have logged the specific error
                logger.error(f"Database logging failed for chunk {chunk_number} of {filename}. Cannot store results.")
                # Keep db_success as False
            elif result.success and result.extracted_data:
                # If LLM/JSON was successful AND logging worked, attempt to store results
                db.store_results(
                    request_id=request_id,
                    file=filename,
                    chunk_number=chunk_number,
                    data=result.extracted_data
                )
                # Assume store_results handles its own errors/logging internally
                # If store_results were to return a status, we'd check it here.
                # For now, if it doesn't raise an exception caught below, assume success.
                db_success = True # DB operations completed if no exception below
            elif not result.success:
                # LLM/JSON failed, logging happened (request_id != -1), no storing needed.
                db_success = True # DB logging part was successful
            else:
                # Should not happen (result.success=True but no data)
                logger.error("Internal inconsistency: Processing marked success but no extracted data.")
                db_success = True # Logged, but nothing to store


        except Exception as db_error:
            # Catch ANY exception during db.log_request or db.store_results
            logger.error(f"Database error during log/store for chunk {chunk_number} of {filename}: {db_error}", exc_info=True)
            # Update the result object if it wasn't already marked as failed
            if result.success:
                result.success = False
                result.error_message = f"Processing succeeded but database operation failed: {db_error}"
            # Keep db_success as False

        # --- Final Return Value ---
        # Return True only if both LLM/JSON processing AND subsequent DB operations were successful
        final_success = result.success and db_success
        if not final_success:
            logger.warning(f"Overall processing failed for chunk {chunk_number} of {filename}. LLM/JSON Success: {result.success}, DB Success: {db_success}, Error: {result.error_message}")

        return final_success