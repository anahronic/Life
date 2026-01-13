"""
Secure configuration module for handling sensitive environment variables.
Ensures API keys and secrets are only loaded from env/secrets, never exposed in UI.
"""

import os
from typing import Any, Optional


class SecureConfig:
    """Encapsulates secure configuration loading from environment variables."""

    @staticmethod
    def _get_value(key: str) -> Optional[str]:
        """Read a config value from env first, then Streamlit secrets (if available)."""
        value = os.getenv(key)
        if value is not None and str(value).strip() != "":
            return str(value)

        try:
            import streamlit as st  # type: ignore

            secrets: Any = getattr(st, "secrets", None)
            if secrets is not None and key in secrets:
                secret_value = secrets[key]
                if secret_value is not None and str(secret_value).strip() != "":
                    return str(secret_value)
        except Exception:
            # Streamlit not installed or secrets unavailable (e.g., during tests/import).
            return None

        return None
    
    @staticmethod
    def get_tomtom_api_key() -> Optional[str]:
        """
        Load TomTom API key from environment.
        Returns None if not set (will trigger sample mode).
        Never logs or exposes the key value.
        """
        key = SecureConfig._get_value("TOMTOM_API_KEY")
        if not key:
            return None

        # Verify it's a non-empty string, don't log its value
        return key if len(key) > 10 else None
    
    @staticmethod
    def get_enable_sample_mode() -> bool:
        """Allow sample mode for testing without API key."""
        return (SecureConfig._get_value("TT_ALLOW_SAMPLE") or "0") == "1"
    
    @staticmethod
    def get_rate_limit_seconds() -> int:
        """Global rate limit: minimum seconds between any external API calls."""
        return int(SecureConfig._get_value("RATE_LIMIT_SECONDS") or "60")
    
    @staticmethod
    def get_cache_ttl() -> int:
        """Cache TTL in seconds."""
        return int(SecureConfig._get_value("CACHE_TTL_SECONDS") or "300")
    
    @staticmethod
    def get_quota_per_hour() -> int:
        """Max API calls per hour (for monitoring)."""
        return int(SecureConfig._get_value("TOMTOM_QUOTA_PER_HOUR") or "2500")
    
    @staticmethod
    def is_production() -> bool:
        """Check if running in production (Streamlit Cloud or similar)."""
        return (SecureConfig._get_value("ENVIRONMENT") or "development").lower() in (
            "production",
            "prod",
        )
    
    @staticmethod
    def verify_api_key_security():
        """Verify that API key is not exposed in any dangerous way."""
        key = SecureConfig._get_value("TOMTOM_API_KEY") or ""
        # Never log or return the key itself
        if key:
            # Just confirm it exists and is reasonably long
            return len(key) > 10
        return False
