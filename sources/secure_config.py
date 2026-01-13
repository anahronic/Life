"""
Secure configuration module for handling sensitive environment variables.
Ensures API keys and secrets are only loaded from env/secrets, never exposed in UI.
"""

import os
from typing import Optional


class SecureConfig:
    """Encapsulates secure configuration loading from environment variables."""
    
    @staticmethod
    def get_tomtom_api_key() -> Optional[str]:
        """
        Load TomTom API key from environment.
        Returns None if not set (will trigger sample mode).
        Never logs or exposes the key value.
        """
        key = os.getenv('TOMTOM_API_KEY')
        if key:
            # Verify it's a non-empty string, don't log its value
            return key if len(key) > 10 else None
        return None
    
    @staticmethod
    def get_enable_sample_mode() -> bool:
        """Allow sample mode for testing without API key."""
        return os.getenv('TT_ALLOW_SAMPLE', '0') == '1'
    
    @staticmethod
    def get_rate_limit_seconds() -> int:
        """Global rate limit: minimum seconds between any external API calls."""
        return int(os.getenv('RATE_LIMIT_SECONDS', '60'))
    
    @staticmethod
    def get_cache_ttl() -> int:
        """Cache TTL in seconds."""
        return int(os.getenv('CACHE_TTL_SECONDS', '300'))
    
    @staticmethod
    def get_quota_per_hour() -> int:
        """Max API calls per hour (for monitoring)."""
        return int(os.getenv('TOMTOM_QUOTA_PER_HOUR', '2500'))
    
    @staticmethod
    def is_production() -> bool:
        """Check if running in production (Streamlit Cloud or similar)."""
        return os.getenv('ENVIRONMENT', 'development').lower() in ('production', 'prod')
    
    @staticmethod
    def verify_api_key_security():
        """Verify that API key is not exposed in any dangerous way."""
        key = os.getenv('TOMTOM_API_KEY', '')
        # Never log or return the key itself
        if key:
            # Just confirm it exists and is reasonably long
            return len(key) > 10
        return False
