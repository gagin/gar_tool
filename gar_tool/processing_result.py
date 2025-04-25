# gar_tool/processing_result.py

from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass
class ProcessingResult:
    """Stores both raw response and extracted data"""
    success: bool
    raw_response: str
    extracted_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None