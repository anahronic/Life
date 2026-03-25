"""
Tests for sources/official_stats.py — env-first congestion benchmark.

Covers:
  - Auto mode: URL adapter → static env → unconfigured stub
  - URL adapter parses JSON correctly
  - Static env adapter reads OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR
  - Disabled mode always returns stub
  - No st.secrets import anywhere in module
  - Unconfigured stub has correct schema
  - Cache behaviour
"""

import pytest
from unittest.mock import patch, MagicMock
from sources import official_stats


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_cache(monkeypatch):
    """Disable on-disk cache for deterministic tests."""
    monkeypatch.setattr("sources.official_stats.cache_read", lambda *a, **k: None)
    monkeypatch.setattr("sources.official_stats.cache_write", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Ensure relevant env vars are unset by default."""
    for key in [
        "OFFICIAL_STATS_SOURCE_MODE",
        "OFFICIAL_STATS_JSON_URL",
        "OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR",
        "OFFICIAL_SOURCE_LABEL",
    ]:
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Unconfigured stub
# ---------------------------------------------------------------------------

class TestUnconfiguredStub:
    def test_returns_none_hours(self):
        """When nothing configured, returns stub with hours=None."""
        out = official_stats.fetch_official_congestion_benchmark(cache_ttl_s=0)
        assert out["hours_lost_per_person_per_year"] is None
        assert out["source_id"] == "official:benchmark:unconfigured"
        assert "error" in out

    def test_stub_schema(self):
        """Stub has all expected keys."""
        out = official_stats._unconfigured_stub()
        expected_keys = {
            "source_id", "fetched_at", "hours_lost_per_person_per_year",
            "source_label", "source_url", "raw", "error",
        }
        assert set(out.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Static env adapter
# ---------------------------------------------------------------------------

class TestStaticEnv:
    def test_reads_hours_from_env(self, monkeypatch):
        monkeypatch.setenv("OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR", "82")
        out = official_stats.fetch_official_congestion_benchmark(cache_ttl_s=0)

        assert out["hours_lost_per_person_per_year"] == 82.0
        assert out["source_id"] == "official:benchmark:env"

    def test_custom_label(self, monkeypatch):
        monkeypatch.setenv("OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR", "82")
        monkeypatch.setenv("OFFICIAL_SOURCE_LABEL", "CBS 2024")
        out = official_stats.fetch_official_congestion_benchmark(cache_ttl_s=0)

        assert out["source_label"] == "CBS 2024"

    def test_static_mode_explicit(self, monkeypatch):
        """OFFICIAL_STATS_SOURCE_MODE=static only tries env, not URL."""
        monkeypatch.setenv("OFFICIAL_STATS_SOURCE_MODE", "static")
        monkeypatch.setenv("OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR", "75")
        out = official_stats.fetch_official_congestion_benchmark(cache_ttl_s=0)

        assert out["hours_lost_per_person_per_year"] == 75.0

    def test_static_mode_not_set(self, monkeypatch):
        """Static mode with no env var returns unconfigured stub."""
        monkeypatch.setenv("OFFICIAL_STATS_SOURCE_MODE", "static")
        out = official_stats.fetch_official_congestion_benchmark(cache_ttl_s=0)

        assert out["hours_lost_per_person_per_year"] is None


# ---------------------------------------------------------------------------
# URL adapter
# ---------------------------------------------------------------------------

class TestUrlAdapter:
    def test_url_parses_json(self, monkeypatch):
        """URL adapter fetches JSON and extracts hours."""
        monkeypatch.setenv("OFFICIAL_STATS_JSON_URL", "https://example.com/stats.json")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "hours_lost_per_person_per_year": 90,
            "source": "Ministry of Transport 2025",
        }

        with patch("sources.official_stats.requests.get", return_value=mock_resp):
            out = official_stats.fetch_official_congestion_benchmark(cache_ttl_s=0)

        assert out["hours_lost_per_person_per_year"] == 90.0
        assert out["source_id"] == "official:benchmark:url"
        assert "Ministry" in out["source_label"]

    def test_url_fallback_to_static(self, monkeypatch):
        """In auto mode, falls back to static env when URL fails."""
        monkeypatch.setenv("OFFICIAL_STATS_JSON_URL", "https://example.com/broken")
        monkeypatch.setenv("OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR", "85")

        with patch("sources.official_stats.requests.get",
                    side_effect=ConnectionError("down")):
            out = official_stats.fetch_official_congestion_benchmark(cache_ttl_s=0)

        assert out["hours_lost_per_person_per_year"] == 85.0
        assert out["source_id"] == "official:benchmark:env"

    def test_url_mode_fails_returns_error(self, monkeypatch):
        """In url-only mode, failure returns error dict (not exception)."""
        monkeypatch.setenv("OFFICIAL_STATS_SOURCE_MODE", "url")
        monkeypatch.setenv("OFFICIAL_STATS_JSON_URL", "https://example.com/broken")

        with patch("sources.official_stats.requests.get",
                    side_effect=ConnectionError("down")):
            out = official_stats.fetch_official_congestion_benchmark(cache_ttl_s=0)

        assert out["hours_lost_per_person_per_year"] is None
        assert "error" in out
        assert out["source_id"] == "official:benchmark:error"

    def test_url_field_variants(self, monkeypatch):
        """URL adapter accepts multiple field name variants."""
        monkeypatch.setenv("OFFICIAL_STATS_JSON_URL", "https://example.com/v2")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hours_per_person_per_year": 77,  # alternative field name
        }

        with patch("sources.official_stats.requests.get", return_value=mock_resp):
            out = official_stats.fetch_official_congestion_benchmark(cache_ttl_s=0)

        assert out["hours_lost_per_person_per_year"] == 77.0


# ---------------------------------------------------------------------------
# Disabled mode
# ---------------------------------------------------------------------------

class TestDisabledMode:
    def test_disabled_returns_stub(self, monkeypatch):
        monkeypatch.setenv("OFFICIAL_STATS_SOURCE_MODE", "disabled")
        monkeypatch.setenv("OFFICIAL_HOURS_LOST_PER_PERSON_PER_YEAR", "99")

        out = official_stats.fetch_official_congestion_benchmark(cache_ttl_s=0)
        assert out["hours_lost_per_person_per_year"] is None
        assert out["source_id"] == "official:benchmark:unconfigured"


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------

class TestCacheBehaviour:
    def test_cache_hit_skips_adapters(self, monkeypatch):
        cached_data = {
            "source_id": "official:benchmark:env",
            "hours_lost_per_person_per_year": 80.0,
        }
        monkeypatch.setattr("sources.official_stats.cache_read",
                            lambda *a, **k: cached_data)

        out = official_stats.fetch_official_congestion_benchmark(cache_ttl_s=300)
        assert out == cached_data


# ---------------------------------------------------------------------------
# No st.secrets dependency
# ---------------------------------------------------------------------------

class TestNoSecretsDependency:
    def test_no_streamlit_import(self):
        """Module must not import streamlit or st.secrets."""
        import inspect
        source = inspect.getsource(official_stats)
        assert "st.secrets" not in source
        assert "import streamlit" not in source
        assert "SecureConfig" not in source
