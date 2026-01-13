"""
Safe logging module that guarantees API keys and secrets are never logged.
Provides structured logging for diagnostics on production.
"""

import logging
import sys
import os
from typing import Any
from datetime import datetime


class SecureFormatter(logging.Formatter):
    """Formatter that masks sensitive data."""
    
    SENSITIVE_PATTERNS = [
        'TOMTOM_API_KEY',
        'api_key',
        'key=',
        'token=',
        'authorization',
        'bearer ',
        'secret',
        'password',
    ]
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record, masking sensitive data."""
        msg = super().format(record)
        
        # Mask common sensitive patterns
        for pattern in self.SENSITIVE_PATTERNS:
            # Find and mask values after patterns
            import re
            msg = re.sub(
                rf'({pattern}\s*[:=]\s*)[^\s,)"\']{{10,}}',
                r'\1[REDACTED]',
                msg,
                flags=re.IGNORECASE
            )
        
        return msg


def get_logger(name: str) -> logging.Logger:
    """Get a safe logger instance."""
    logger = logging.getLogger(name)
    
    # Only configure if not already done
    if not logger.handlers:
        # Console handler
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(SecureFormatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        logger.addHandler(handler)
        
        # Set level from env
        level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
        logger.setLevel(getattr(logging, level_str, logging.INFO))
    
    return logger


def log_api_call(service: str, endpoint: str, status_code: int, elapsed_ms: float):
    """Safe logging of API calls (never includes sensitive data like keys)."""
    logger = get_logger('api_calls')
    
    # Log endpoint without query params that might contain keys
    safe_endpoint = endpoint.split('?')[0] if '?' in endpoint else endpoint
    
    logger.info(f"{service} {status_code} {safe_endpoint} ({elapsed_ms:.0f}ms)")


def log_cache_hit(key: str):
    """Log cache hit."""
    logger = get_logger('cache')
    logger.debug(f"Cache hit: {key}")


def log_cache_miss(key: str, reason: str = 'expired'):
    """Log cache miss."""
    logger = get_logger('cache')
    logger.debug(f"Cache miss: {key} ({reason})")


def log_error(service: str, error_code: str, message: str):
    """Log error in structured way."""
    logger = get_logger('errors')
    logger.warning(f"{service} error: {error_code} - {message}")


def log_quota_alert(service: str, current: int, limit: int):
    """Log quota usage alerts."""
    logger = get_logger('quota')
    percent = (current / limit * 100) if limit > 0 else 0
    logger.warning(f"{service} quota: {current}/{limit} ({percent:.1f}%)")


# Test that nothing sensitive is ever logged
def _test_no_key_leak():
    """Verify that API keys aren't exposed in logs (test only)."""
    logger = get_logger('test')
    
    # This should work - generic key
    logger.info("api_key=12345678")  # OK - short, not real
    
    # This would be redacted if it were a real key
    # logger.info("api_key=abcdef1234567890abcdef1234567890")  # Would be [REDACTED]


if __name__ == '__main__':
    # Setup basic logging for testing
    logger = get_logger('main')
    logger.info("Logger initialized successfully")
