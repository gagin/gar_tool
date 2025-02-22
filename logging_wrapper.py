import logging
import sys
from typing import Callable

class LoggingWrapper:
    def __init__(self, log_level: str = "INFO"):
        self.error_count = 0
        self.warning_count = 0
        self.root_logger = logging.getLogger()
        self.max_passable_errors = 5  # Default value
        self.max_passable_warnings = 5 # Default Value
        self.error_exceed_message = "Exceeded maximum passable errors ({max_errors}). Exiting."
        self.warning_exceed_message = "Exceeded maximum passable warnings ({max_warnings}). Exiting."
        self.setup_logger(log_level)

    def setup_logger(self, log_level: str):
        self.root_logger.setLevel(log_level.upper())

        class InfoFormatter(logging.Formatter):
            def format(self, record):
                if record.levelname == 'INFO':
                    return record.getMessage()
                return super().format(record)

        handler = logging.StreamHandler()
        handler.setFormatter(InfoFormatter('%(asctime)s - %(levelname)s - %(lineno)d: %(message)s'))
        self.root_logger.addHandler(handler)

    def set_log_level(self, log_level: str):
        self.root_logger.setLevel(log_level.upper())

    def get_log_level_name(self) -> str:
        return logging.getLevelName(self.root_logger.getEffectiveLevel())

    def get_log_level_value(self) -> int: # Is not used anymore in the main script, but let's keep it just in case
        return self.root_logger.getEffectiveLevel()

    def set_max_passable(self, max_errors: int, max_warnings: int, error_message: str = None, warning_message: str = None):
        self.max_passable_errors = max_errors
        self.max_passable_warnings = max_warnings
        if error_message:
            self.error_exceed_message = error_message
        if warning_message:
            self.warning_exceed_message = warning_message

    def _log(self, log_func: Callable[[str], None], message: str):
        if log_func in (logging.error, logging.exception, logging.critical):
            self.error_count += 1
            if self.error_count > self.max_passable_errors:
                logging.critical(self.error_exceed_message.format(max_errors=self.max_passable_errors))
                sys.exit(1)
        elif log_func == logging.warning:
            self.warning_count += 1
            if self.warning_count > self.max_passable_warnings:
                logging.critical(self.warning_exceed_message.format(max_warnings=self.max_passable_warnings))
                sys.exit(1)
        log_func(message)

    def debug(self, message: str):
        self._log(logging.debug, message)

    def info(self, message: str):
        self._log(logging.info, message)

    def warning(self, message: str):
        self._log(logging.warning, message)

    def error(self, message: str):
        self._log(logging.error, message)

    def exception(self, message: str):
        self._log(logging.exception, message)

    def critical(self, message: str):
        self._log(logging.critical, message)

logger = LoggingWrapper()  # Initialize the logger instance