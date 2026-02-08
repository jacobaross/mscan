"""Tests for the CIK lookup module."""

import json
import tempfile
import shutil
from pathlib import Path

import pytest
import responses

from mscan.enricher.cik_lookup import (
    CIKLookup,
    CompanyMatch,
    TickerNotFoundError,
    CompanyNotFoundError,
    CIKLookupError
)
from mscan.enricher.cache_manager import CacheManager
from mscan.utils.rate_limiter import RateLimiter


class TestCIKLookup:
    """Test cases for CIKLookup."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp_path = tempfile.mkdtemp()
        yield temp_path
        shutil.rmtree(temp_path)
        
    @pytest.fixture
    def mock_ticker_data(self):
        """Mock SEC ticker data."""
        return {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
            "2": {"cik_str": 1018724, "ticker": "AMZN", "title": "Amazon.com Inc."},
            "3": {"cik_str": 1652044, "ticker": "GOOGL", "title": "Alphabet Inc."},
            "4": {"cik_str": 1326801, "ticker": "META", "title": "Meta Platforms Inc."},
        }
    
    @pytest.fixture
    def lookup(self, temp_dir, mock_ticker_data):
        """Create a CIKLookup instance with mocked data."""
        db_path = Path(temp_dir) / "cache.db"
        cache = CacheManager(db_path=str(db_path))
        rate_limiter = RateLimiter()
        
        lookup = CIKLookup(cache, rate_limiter, "TestAgent test@test.com")
        
        # Mock the internal mapping directly
        lookup._ticker_to_cik = {
            "AAPL": "0000320193",
            "MSFT": "0000789019",
            "AMZN": "0001018724",
            "GOOGL": "0001652044",
            "META": "0001326801"
        }
        lookup._cik_to_ticker = {v: k for k, v in lookup._ticker_to_cik.items()}
        lookup._company_names = {
            "0000320193": "Apple Inc.",
            "0000789019": "Microsoft Corp",
            "0001018724": "Amazon.com Inc.",
            "0001652044": "Alphabet Inc.",
            "0001326801": "Meta Platforms Inc."
        }
        lookup._name_to_cik = {
            lookup._normalize_name(v): k 
            for k, v in lookup._company_names.items()
        }
        lookup._loaded = True
        
        return lookup
        
    def test_by_ticker_success(self, lookup):
        """Test successful ticker lookup."""
        cik = lookup.by_ticker("AAPL")
        assert cik == "0000320193"
        
        cik = lookup.by_ticker("MSFT")
        assert cik == "0000789019"
        
    def test_by_ticker_case_insensitive(self, lookup):
        """Test ticker lookup is case insensitive."""
        cik = lookup.by_ticker("aapl")
        assert cik == "0000320193"
        
        cik = lookup.by_ticker("MsFt")
        assert cik == "0000789019"
        
    def test_by_ticker_not_found(self, lookup):
        """Test ticker not found raises exception."""
        with pytest.raises(TickerNotFoundError, match="Ticker not found: FAKE"):
            lookup.by_ticker("FAKE")
            
    def test_by_ticker_empty(self, lookup):
        """Test empty ticker raises exception."""
        with pytest.raises(TickerNotFoundError, match="Empty ticker symbol"):
            lookup.by_ticker("")
            
    def test_by_name_exact_match(self, lookup):
        """Test exact company name match."""
        matches = lookup.by_name("Apple Inc.")
        
        assert len(matches) == 1
        assert matches[0].cik == "0000320193"
        assert matches[0].ticker == "AAPL"
        assert matches[0].match_score == 1.0
        assert matches[0].match_type == "exact"
        
    def test_by_name_fuzzy_match(self, lookup):
        """Test fuzzy company name matching."""
        matches = lookup.by_name("Apple")
        
        assert len(matches) >= 1
        assert any(m.cik == "0000320193" for m in matches)
        
    def test_by_name_not_found(self, lookup):
        """Test company name not found raises exception."""
        with pytest.raises(CompanyNotFoundError):
            lookup.by_name("XYZ Nonexistent Company 12345")
            
    def test_by_name_empty(self, lookup):
        """Test empty company name raises exception."""
        with pytest.raises(CompanyNotFoundError, match="Empty company name"):
            lookup.by_name("")
            
    def test_by_name_limit(self, lookup):
        """Test name search with limit."""
        matches = lookup.by_name("Inc", limit=3)
        
        assert len(matches) <= 3
        
    def test_resolve_ticker(self, lookup):
        """Test resolve with ticker."""
        result = lookup.resolve("AAPL")
        
        assert isinstance(result, CompanyMatch)
        assert result.cik == "0000320193"
        assert result.ticker == "AAPL"
        assert result.match_type == "ticker"
        
    def test_resolve_name(self, lookup):
        """Test resolve with company name."""
        result = lookup.resolve("Apple Inc.")
        
        assert isinstance(result, CompanyMatch)
        assert result.cik == "0000320193"
        
    def test_resolve_ambiguous(self, lookup):
        """Test resolve with ambiguous input."""
        # "META" is also a word, but should resolve as ticker
        result = lookup.resolve("META")
        
        assert result.cik == "0001326801"
        
    def test_get_company_name(self, lookup):
        """Test getting company name by CIK."""
        name = lookup.get_company_name("0000320193")
        assert name == "Apple Inc."
        
        name = lookup.get_company_name("0000789019")
        assert name == "Microsoft Corp"
        
    def test_get_company_name_not_found(self, lookup):
        """Test getting name for unknown CIK."""
        name = lookup.get_company_name("9999999999")
        assert name is None
        
    def test_get_ticker(self, lookup):
        """Test getting ticker by CIK."""
        ticker = lookup.get_ticker("0000320193")
        assert ticker == "AAPL"
        
    def test_get_ticker_not_found(self, lookup):
        """Test getting ticker for unknown CIK."""
        ticker = lookup.get_ticker("9999999999")
        assert ticker is None
        
    def test_search_by_prefix(self, lookup):
        """Test search by prefix."""
        results = lookup.search_by_prefix("APP")
        
        assert len(results) >= 1
        assert any(r.ticker == "AAPL" for r in results)
        
    def test_normalize_name(self, lookup):
        """Test name normalization."""
        # Remove suffixes
        assert lookup._normalize_name("Apple Inc.") == "apple"
        assert lookup._normalize_name("Microsoft Corp") == "microsoft"
        assert lookup._normalize_name("Company LLC") == "company"
        
        # Handle punctuation
        assert lookup._normalize_name("Amazon.com Inc.") == "amazon com"
        
        # Lowercase
        assert lookup._normalize_name("Alphabet Inc.") == "alphabet"
        
    def test_list_all_tickers(self, lookup):
        """Test listing all tickers."""
        tickers = lookup.list_all_tickers()
        
        assert len(tickers) == 5
        assert "AAPL" in tickers
        assert "MSFT" in tickers
        
    def test_get_stats(self, lookup):
        """Test getting lookup stats."""
        stats = lookup.get_stats()
        
        assert stats['loaded'] is True
        assert stats['total_tickers'] == 5
        assert stats['total_companies'] == 5
        
    @responses.activate
    def test_load_mapping_from_sec(self, temp_dir):
        """Test loading mapping from SEC API."""
        mock_data = {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
        }
        
        responses.add(
            responses.GET,
            "https://www.sec.gov/files/company_tickers.json",
            json=mock_data,
            status=200
        )
        
        db_path = Path(temp_dir) / "cache.db"
        cache = CacheManager(db_path=str(db_path))
        rate_limiter = RateLimiter()
        
        lookup = CIKLookup(cache, rate_limiter, "TestAgent test@test.com")
        
        # Force load from SEC
        result = lookup._load_mapping(force_refresh=True)
        
        assert result is True
        assert lookup._loaded is True
        assert "AAPL" in lookup._ticker_to_cik
        
    @responses.activate  
    def test_load_mapping_failure(self, temp_dir):
        """Test handling of mapping load failure."""
        responses.add(
            responses.GET,
            "https://www.sec.gov/files/company_tickers.json",
            status=500
        )
        
        db_path = Path(temp_dir) / "cache.db"
        cache = CacheManager(db_path=str(db_path))
        rate_limiter = RateLimiter()
        
        lookup = CIKLookup(cache, rate_limiter, "TestAgent test@test.com")
        
        # Reset to force reload
        lookup._loaded = False
        result = lookup._load_mapping()
        
        assert result is False
