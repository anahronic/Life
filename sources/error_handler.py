"""
Fail-closed error handling with user-friendly status codes and messages.
No stack traces in browser; structured logging for diagnostics.
"""

from typing import Dict, Any, Optional
from enum import Enum


class ErrorCode(str, Enum):
    """Standard error codes for API failures."""
    SOURCE_UNAVAILABLE = "source_unavailable"  # Service unreachable
    STALE_DATA = "stale_data"                  # Data older than expected
    QUOTA_EXCEEDED = "quota_exceeded"          # Rate limit or quota hit
    INVALID_INPUT = "invalid_input"            # Bad parameters
    INTERNAL_ERROR = "internal_error"          # Unexpected server error
    NETWORK_ERROR = "network_error"            # Connection issues


class APIError:
    """Structured error with user-friendly message and code."""
    
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        internal_details: Optional[str] = None,
        retry_after_seconds: Optional[float] = None
    ):
        self.code = code
        self.message = message  # User-facing
        self.internal_details = internal_details  # For logs only
        self.retry_after_seconds = retry_after_seconds
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON responses."""
        result = {
            'error': self.code.value,
            'message': self.message,
        }
        if self.retry_after_seconds:
            result['retry_after_seconds'] = self.retry_after_seconds
        return result
    
    def __str__(self) -> str:
        return f"[{self.code.value}] {self.message}"


class ErrorHandler:
    """Handle errors in a structured, user-friendly way."""
    
    @staticmethod
    def handle_api_call_error(exception: Exception, service: str = 'tomtom') -> APIError:
        """
        Convert an exception from an API call to a user-friendly APIError.
        Never expose raw exception message or stack trace.
        """
        error_str = str(exception).lower()
        
        # Recognize specific error patterns
        if 'timeout' in error_str or 'connection' in error_str:
            return APIError(
                code=ErrorCode.NETWORK_ERROR,
                message=f"{service.title()} service is temporarily unavailable. Please try again in a moment.",
                internal_details=str(exception),
                retry_after_seconds=30
            )
        
        if '403' in error_str or 'forbidden' in error_str:
            return APIError(
                code=ErrorCode.QUOTA_EXCEEDED,
                message="API quota exceeded. Service will resume later.",
                internal_details=str(exception),
                retry_after_seconds=60
            )
        
        if '429' in error_str or 'too many' in error_str:
            return APIError(
                code=ErrorCode.QUOTA_EXCEEDED,
                message="Too many requests. Please wait before trying again.",
                internal_details=str(exception),
                retry_after_seconds=60
            )
        
        if '404' in error_str or 'not found' in error_str:
            return APIError(
                code=ErrorCode.INVALID_INPUT,
                message=f"{service.title()} endpoint not found.",
                internal_details=str(exception)
            )
        
        if '5' in error_str and ('00' in error_str or 'server' in error_str):
            return APIError(
                code=ErrorCode.SOURCE_UNAVAILABLE,
                message=f"{service.title()} service error. Please try again later.",
                internal_details=str(exception),
                retry_after_seconds=60
            )
        
        # Generic fallback
        return APIError(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Error fetching from {service.title()}. Please try again.",
            internal_details=str(exception),
            retry_after_seconds=30
        )
    
    @staticmethod
    def handle_stale_data_error(age_seconds: float, max_age_seconds: float = 600) -> APIError:
        """Create error for stale data."""
        return APIError(
            code=ErrorCode.STALE_DATA,
            message=f"Traffic data is outdated (last updated {int(age_seconds)}s ago). "
                    "Data quality may be reduced.",
            internal_details=f"Data age {age_seconds}s exceeds max {max_age_seconds}s"
        )
    
    @staticmethod
    def handle_missing_key_error() -> APIError:
        """Create error for missing API key."""
        return APIError(
            code=ErrorCode.SOURCE_UNAVAILABLE,
            message="Traffic service is not configured. Please contact administrator.",
            internal_details="TOMTOM_API_KEY not set and sample mode not enabled"
        )
    
    @staticmethod
    def make_error_response(error: APIError) -> Dict[str, Any]:
        """
        Create a standard error response dict.
        Safe to display in UI.
        """
        return {
            'error': error.code.value,
            'message': error.message,
            'status': 'error',
            'retry_after_seconds': error.retry_after_seconds
        }


def create_safe_error_dict(code: ErrorCode, message: str) -> Dict[str, Any]:
    """Quick helper to create a safe error dict."""
    return {
        'error': code.value,
        'message': message,
        'status': 'error'
    }
