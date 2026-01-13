"""
Global rate limiter to protect external API quotas.
Implements a simple token-bucket style rate limiting at application level.
"""

import time
from threading import Lock
from typing import Dict, Tuple


class RateLimiter:
    """Thread-safe rate limiter for external API calls."""
    
    def __init__(self, min_interval_seconds: int = 60):
        """
        Initialize rate limiter.
        
        Args:
            min_interval_seconds: Minimum seconds between any external API calls
        """
        self.min_interval_seconds = min_interval_seconds
        self.last_call_time: Dict[str, float] = {}
        self.call_count_per_hour: Dict[str, int] = {}
        self.hour_window_start: Dict[str, float] = {}
        self.lock = Lock()
    
    def can_call(self, service: str = 'tomtom') -> Tuple[bool, float]:
        """
        Check if we can make an API call to the given service.
        
        Args:
            service: Service name (e.g., 'tomtom')
            
        Returns:
            Tuple of (allowed: bool, seconds_to_wait: float)
        """
        with self.lock:
            now = time.time()
            last_call = self.last_call_time.get(service, 0)
            elapsed = now - last_call
            
            if elapsed < self.min_interval_seconds:
                wait_time = self.min_interval_seconds - elapsed
                return False, wait_time
            
            # Track hourly quota
            hour_start = self.hour_window_start.get(service, now)
            if now - hour_start > 3600:
                # Reset hourly counter
                self.call_count_per_hour[service] = 0
                self.hour_window_start[service] = now
            
            return True, 0.0
    
    def record_call(self, service: str = 'tomtom', quota_per_hour: int = 2500):
        """
        Record that an API call was made.
        
        Args:
            service: Service name
            quota_per_hour: Maximum calls allowed per hour
        """
        with self.lock:
            now = time.time()
            self.last_call_time[service] = now
            
            # Initialize hourly tracking if needed
            if service not in self.hour_window_start:
                self.hour_window_start[service] = now
            
            # Increment counter
            self.call_count_per_hour[service] = self.call_count_per_hour.get(service, 0) + 1
    
    def get_quota_status(self, service: str = 'tomtom', quota_per_hour: int = 2500) -> Dict:
        """Get current quota status."""
        with self.lock:
            count = self.call_count_per_hour.get(service, 0)
            return {
                'calls_this_hour': count,
                'quota_per_hour': quota_per_hour,
                'remaining': max(0, quota_per_hour - count),
                'percent_used': min(100, (count / quota_per_hour) * 100) if quota_per_hour > 0 else 0
            }
    
    def get_last_call_age(self, service: str = 'tomtom') -> float:
        """Get seconds since last call to service."""
        with self.lock:
            last_call = self.last_call_time.get(service, 0)
            return time.time() - last_call if last_call > 0 else float('inf')


# Global instance
_global_limiter = RateLimiter(min_interval_seconds=60)


def can_call_api(service: str = 'tomtom') -> Tuple[bool, float]:
    """Check if API call is allowed."""
    return _global_limiter.can_call(service)


def record_api_call(service: str = 'tomtom', quota_per_hour: int = 2500):
    """Record that an API call was made."""
    _global_limiter.record_call(service, quota_per_hour)


def get_quota_status(service: str = 'tomtom', quota_per_hour: int = 2500) -> Dict:
    """Get quota status."""
    return _global_limiter.get_quota_status(service, quota_per_hour)


def get_last_call_age(service: str = 'tomtom') -> float:
    """Get age of last call."""
    return _global_limiter.get_last_call_age(service)
