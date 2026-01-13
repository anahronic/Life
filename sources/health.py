"""
Health check endpoint for monitoring and diagnostics.
Checks TomTom API availability, cache status, and data freshness.
"""

import time
import os
from typing import Dict, Any
from datetime import datetime
from .cache import cache_read


class HealthChecker:
    """Health checking for the application."""
    
    @staticmethod
    def check_tomtom_api() -> Dict[str, Any]:
        """
        Check if TomTom API is accessible.
        Returns status without making actual API calls when possible.
        """
        import requests
        
        # Quick connectivity check (doesn't consume quota)
        try:
            response = requests.head(
                'https://api.tomtom.com/',
                timeout=5
            )
            return {
                'status': 'ok' if response.status_code < 500 else 'degraded',
                'endpoint': 'https://api.tomtom.com/',
                'response_time_ms': int(response.elapsed.total_seconds() * 1000),
                'check_time': datetime.utcnow().isoformat() + 'Z'
            }
        except Exception as e:
            return {
                'status': 'down',
                'error': str(e)[:100],  # Truncate error message
                'check_time': datetime.utcnow().isoformat() + 'Z'
            }
    
    @staticmethod
    def check_cache_status() -> Dict[str, Any]:
        """Check cache directory and recent cache files."""
        cache_dir = os.path.join(os.path.dirname(__file__), '_cache')
        
        cache_ok = os.path.exists(cache_dir) and os.path.isdir(cache_dir)
        
        file_count = 0
        if cache_ok:
            try:
                file_count = len(os.listdir(cache_dir))
            except:
                pass
        
        return {
            'status': 'ok' if cache_ok else 'missing',
            'cache_dir': cache_dir,
            'file_count': file_count,
            'writable': cache_ok and os.access(cache_dir, os.W_OK)
        }
    
    @staticmethod
    def check_data_freshness() -> Dict[str, Any]:
        """Check how fresh the latest TomTom data is."""
        try:
            # Try to read the most recent aggregate cache
            data = cache_read('tomtom_ayalon_v4_abs10_flow', max_age_s=3600)
            
            if not data:
                return {
                    'status': 'stale',
                    'last_fetch': None,
                    'age_seconds': None,
                    'message': 'No recent data in cache'
                }
            
            fetched_at = data.get('fetched_at')
            if not fetched_at:
                return {
                    'status': 'unknown',
                    'message': 'fetched_at not found in cache'
                }
            
            # Parse ISO timestamp
            try:
                fetch_time = datetime.fromisoformat(
                    fetched_at.replace('Z', '+00:00')
                ).timestamp()
            except:
                return {
                    'status': 'unknown',
                    'message': f'Cannot parse timestamp: {fetched_at}'
                }
            
            age_seconds = time.time() - fetch_time
            
            # Status: ok if < 5 min, stale if > 10 min
            if age_seconds < 300:
                status = 'ok'
            elif age_seconds < 600:
                status = 'warning'
            else:
                status = 'stale'
            
            return {
                'status': status,
                'last_fetch': fetched_at,
                'age_seconds': int(age_seconds),
                'message': f'Data is {int(age_seconds)}s old'
            }
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e)[:100]
            }
    
    @staticmethod
    def full_health_check() -> Dict[str, Any]:
        """Run full health check and return aggregated status."""
        api_status = HealthChecker.check_tomtom_api()
        cache_status = HealthChecker.check_cache_status()
        data_status = HealthChecker.check_data_freshness()
        
        # Aggregate status
        statuses = [api_status.get('status'), cache_status.get('status'), data_status.get('status')]
        
        if 'down' in statuses:
            overall = 'down'
        elif 'error' in statuses:
            overall = 'error'
        elif 'stale' in statuses:
            overall = 'degraded'
        elif 'warning' in statuses:
            overall = 'warning'
        else:
            overall = 'ok'
        
        return {
            'status': overall,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'checks': {
                'tomtom_api': api_status,
                'cache': cache_status,
                'data_freshness': data_status
            }
        }


# Global health checker instance
_health_checker = HealthChecker()


def get_health_status() -> Dict[str, Any]:
    """Get current health status."""
    return _health_checker.full_health_check()


def get_quick_status() -> str:
    """Get one-word status: ok, warning, degraded, down."""
    status = get_health_status()
    return status.get('status', 'unknown')
