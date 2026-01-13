"""
Analytics and monitoring for production health.
Tracks API calls, errors, and cache statistics without exposing sensitive data.
"""

import time
import os
from typing import Dict, Any
from threading import Lock
from datetime import datetime, timedelta


class Analytics:
    """Track application metrics."""
    
    def __init__(self):
        self.lock = Lock()
        
        # Counters
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.rate_limited_requests = 0
        self.stale_data_served = 0
        
        # Error tracking
        self.errors_by_type: Dict[str, int] = {}
        
        # Cache metrics
        self.cache_hits = 0
        self.cache_misses = 0
        
        # Start time for uptime calculation
        self.start_time = time.time()
        
        # Windows for rate calculation
        self.requests_per_minute: list = []  # tuples of (time, count)
    
    def record_request(self, success: bool, error_code: str = None):
        """Record a request attempt."""
        with self.lock:
            self.total_requests += 1
            if success:
                self.successful_requests += 1
            else:
                self.failed_requests += 1
                if error_code:
                    self.errors_by_type[error_code] = self.errors_by_type.get(error_code, 0) + 1
    
    def record_rate_limited(self):
        """Record a rate-limited request."""
        with self.lock:
            self.rate_limited_requests += 1
    
    def record_stale_data(self):
        """Record when stale data is served."""
        with self.lock:
            self.stale_data_served += 1
    
    def record_cache_hit(self):
        """Record cache hit."""
        with self.lock:
            self.cache_hits += 1
    
    def record_cache_miss(self):
        """Record cache miss."""
        with self.lock:
            self.cache_misses += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        with self.lock:
            uptime_seconds = time.time() - self.start_time
            total_cache = self.cache_hits + self.cache_misses
            cache_hit_ratio = (
                self.cache_hits / total_cache * 100 if total_cache > 0 else 0
            )
            
            return {
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'uptime_seconds': int(uptime_seconds),
                'uptime_minutes': int(uptime_seconds / 60),
                'requests': {
                    'total': self.total_requests,
                    'successful': self.successful_requests,
                    'failed': self.failed_requests,
                    'rate_limited': self.rate_limited_requests,
                    'success_rate': (
                        self.successful_requests / self.total_requests * 100
                        if self.total_requests > 0 else 0
                    )
                },
                'cache': {
                    'hits': self.cache_hits,
                    'misses': self.cache_misses,
                    'hit_ratio': cache_hit_ratio
                },
                'data_quality': {
                    'stale_data_served': self.stale_data_served,
                },
                'errors': self.errors_by_type.copy(),
                'requests_per_minute': len([x for x in self.requests_per_minute 
                                          if time.time() - x[0] < 60])
            }


# Global analytics instance
_analytics = Analytics()


def record_request(success: bool = True, error_code: str = None):
    """Record a request."""
    _analytics.record_request(success, error_code)


def record_rate_limited():
    """Record rate limited."""
    _analytics.record_rate_limited()


def record_stale_data():
    """Record stale data served."""
    _analytics.record_stale_data()


def record_cache_hit():
    """Record cache hit."""
    _analytics.record_cache_hit()


def record_cache_miss():
    """Record cache miss."""
    _analytics.record_cache_miss()


def get_analytics() -> Dict[str, Any]:
    """Get analytics stats."""
    return _analytics.get_stats()


def get_dashboard_summary() -> Dict[str, Any]:
    """Get summary for UI dashboard."""
    stats = get_analytics()
    
    return {
        'status': 'operational' if stats['requests']['success_rate'] > 95 else 'degraded',
        'uptime': f"{stats['uptime_minutes']} minutes",
        'requests_total': stats['requests']['total'],
        'success_rate': f"{stats['requests']['success_rate']:.1f}%",
        'cache_hit_ratio': f"{stats['cache']['hit_ratio']:.1f}%",
        'errors_this_session': sum(stats['errors'].values())
    }
