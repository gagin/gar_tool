import logging
import sys
from typing import Callable, Optional

MAX_EXCERPT_LENGTH = 10000  # Generous default limit


class LoggingWrapper:
    def __init__(
        self,
        log_level: str = "INFO",
        excerpt_length: Optional[int] = 200,
    ):
        self.error_count = 0
        self.warning_count = 0
        self.root_logger = logging.getLogger()
        # Clear existing handlers if any (useful for re-runs in notebooks)
        if self.root_logger.hasHandlers():
            self.root_logger.handlers.clear()

        self.max_passable_errors = 5
        self.max_passable_warnings = 10
        self.error_exceed_message = (
            "Exceeded maximum passable errors ({max_errors}). Exiting."
        )
        self.warning_exceed_message = (
            "Exceeded maximum passable warnings ({max_warnings}). Exiting."
        )
        self.set_excerpt_length(excerpt_length)
        self.setup_logger(log_level)

    def setup_logger(self, log_level: str):
        self.root_logger.setLevel(log_level.upper())

        class InfoFormatter(logging.Formatter):
            def format(self, record):
                if record.levelname == "INFO":
                    # Basic format for INFO messages
                    return record.getMessage()
                elif record.levelname in ("WARNING", "ERROR", "CRITICAL"):
                    # More detailed format for errors/warnings
                    return super().format(record)
                else: # DEBUG
                    # Most detailed format for DEBUG
                    return super().format(record)

        log_format_debug = (
            "%(asctime)s - %(levelname)s - "
            "%(filename)s:%(lineno)d - %(message)s"
        )
        log_format_warn_err = (
             "%(asctime)s - %(levelname)s - %(message)s"
        )

        # Use a single handler and adjust formatting within the formatter
        handler = logging.StreamHandler(sys.stdout)

        # Create a custom formatter that chooses based on level
        formatter = logging.Formatter(log_format_debug) # Default to debug
        # Override format based on level within the custom formatter if needed
        # Or simpler: Set formatter based on handler level (but INFO is lowest)

        # Let's try setting different formats based on level in the formatter
        class LevelBasedFormatter(logging.Formatter):
            def format(self, record):
                if record.levelno == logging.DEBUG:
                    self._style._fmt = log_format_debug
                elif record.levelno >= logging.WARNING:
                     self._style._fmt = log_format_warn_err
                else: # INFO and others
                    # Use just the message for INFO
                    return record.getMessage() # Special handling for INFO
                # Call the original format method with the updated format string
                return super().format(record)

        # handler.setFormatter(InfoFormatter('%(asctime)s - %(levelname)s - %(lineno)d: %(message)s'))
        handler.setFormatter(LevelBasedFormatter(log_format_debug))
        self.root_logger.addHandler(handler)

    def set_log_level(self, log_level: str):
        self.root_logger.setLevel(log_level.upper())

    def get_log_level_name(self) -> str:
        return logging.getLevelName(self.root_logger.getEffectiveLevel())

    def set_max_passable(
        self,
        max_errors: int,
        max_warnings: int,
        error_message: str = None,
        warning_message: str = None,
    ):
        self.max_passable_errors = max_errors
        self.max_passable_warnings = max_warnings
        if error_message:
            self.error_exceed_message = error_message
        if warning_message:
            self.warning_exceed_message = warning_message

    def _log(self, log_func: Callable, message: str, exc_info=False):
        if self.excerpt_length is not None and len(message) > self.excerpt_length:
            message = (
                f"{message[:self.excerpt_length]}\n...\n"
                f"(message truncated to {self.excerpt_length} chars)"
            )

        if log_func.__name__ in ("error", "exception", "critical"):
            self.error_count += 1
            if self.error_count > self.max_passable_errors:
                final_message = self.error_exceed_message.format(
                    max_errors=self.max_passable_errors
                )
                # Log the original message before exiting
                log_func(message, exc_info=exc_info)
                logging.critical(final_message) # Use std logging for final exit msg
                sys.exit(1)
        elif log_func.__name__ == "warning":
            self.warning_count += 1
            if self.warning_count > self.max_passable_warnings:
                final_message = self.warning_exceed_message.format(
                    max_warnings=self.max_passable_warnings
                )
                # Log the original message before exiting
                log_func(message, exc_info=exc_info)
                logging.critical(final_message)
                sys.exit(1)

        # Use the logger instance's methods directly
        if exc_info:
             log_func(message, exc_info=True)
        else:
             log_func(message)


    def set_excerpt_length(self, length: Optional[int]):
        if length is None:
            self.excerpt_length = None
        elif length > 0:
            self.excerpt_length = min(length, MAX_EXCERPT_LENGTH)
        else:
             self.excerpt_length = None # Disable if zero or negative

    def debug(self, message: str):
        self._log(self.root_logger.debug, message)

    def info(self, message: str):
        self._log(self.root_logger.info, message)

    def warning(self, message: str, exc_info=False):
        self._log(self.root_logger.warning, message, exc_info=exc_info)

    def error(self, message: str, exc_info=False):
        self._log(self.root_logger.error, message, exc_info=exc_info)

    def exception(self, message: str):
        # exception method inherently includes exc_info=True
        self._log(self.root_logger.exception, message, exc_info=True)

    def critical(self, message: str, exc_info=False):
        self._log(self.root_logger.critical, message, exc_info=exc_info)

    def critical_exit(self, message: str):
        # Log using the wrapper's critical to check limits potentially
        # Although critical usually implies immediate exit anyway
        self._log(self.root_logger.critical, message)
        sys.exit(1)


logger = LoggingWrapper()
