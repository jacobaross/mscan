"""Basic integration tests for the EDGAR client."""

import pytest
import responses

from mscan.enricher.edgar_client import (
    EdgarClient,
    EdgarAPIException,
    NotFoundError,
    RateLimitError
)


class TestEdgarClient:
    """Test cases for EdgarClient."""
    
    def test_init_requires_user_agent(self):
        """Test that user agent is required."""
        with pytest.raises(ValueError, match="User-Agent is required"):
            EdgarClient(user_agent="")
            
    def test_init_requires_email_in_user_agent(self):
        """Test that user agent must include email."""
        with pytest.raises(ValueError, match="must include contact email"):
            EdgarClient(user_agent="CompanyName")
            
    def test_init_success(self):
        """Test successful initialization."""
        client = EdgarClient(user_agent="TestCo test@test.com")
        
        assert client.user_agent == "TestCo test@test.com"
        assert "@" in client.headers["User-Agent"]
        
    @responses.activate
    def test_enrich_by_ticker_not_found(self):
        """Test enrichment with non-existent ticker."""
        client = EdgarClient(user_agent="TestCo test@test.com")
        
        # Mock empty ticker mapping
        responses.add(
            responses.GET,
            "https://www.sec.gov/files/company_tickers.json",
            json={},
            status=200
        )
        
        result = client.enrich_by_ticker("FAKE")
        
        assert result.success is False
        assert result.error is not None
        assert result.error.error_type == "ticker_not_found"
        
    @responses.activate
    def test_enrich_by_cik_submissions_only(self):
        """Test enrichment with submissions data only."""
        client = EdgarClient(user_agent="TestCo test@test.com")
        
        # Mock submissions endpoint
        responses.add(
            responses.GET,
            "https://data.sec.gov/submissions/CIK0000320193.json",
            json={
                "cik": "0000320193",
                "entityName": "Apple Inc.",
                "sic": "3571",
                "sicDescription": "Electronic Computers",
                "tickers": ["AAPL"],
                "exchanges": ["Nasdaq"],
                "filings": {
                    "recent": {
                        "form": ["10-K", "10-Q"],
                        "filingDate": ["2024-02-02", "2024-01-05"],
                        "accessionNumber": ["0000320193-24-000123", "0000320193-24-000001"],
                        "primaryDocument": ["aapl-20231230.htm", "aapl-20231005.htm"]
                    }
                }
            },
            status=200
        )
        
        # Mock company facts endpoint (404 - not all companies have this)
        responses.add(
            responses.GET,
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
            status=404
        )
        
        result = client.enrich_by_cik("0000320193", ticker="AAPL")
        
        assert result.success is True
        assert result.brand is not None
        assert result.brand.sec_profile.cik == "0000320193"
        assert result.brand.sec_profile.company_name == "Apple Inc."
        assert result.brand.sec_profile.ticker == "AAPL"
        
    @responses.activate
    def test_rate_limit_error_handling(self):
        """Test handling of rate limit errors."""
        client = EdgarClient(user_agent="TestCo test@test.com")
        
        # Mock rate limit response
        responses.add(
            responses.GET,
            "https://data.sec.gov/submissions/CIK0000320193.json",
            status=429
        )
        
        with pytest.raises(RateLimitError):
            client._make_request(
                "https://data.sec.gov/submissions/CIK0000320193.json",
                use_cache=False
            )
            
    @responses.activate
    def test_not_found_error_handling(self):
        """Test handling of 404 errors."""
        client = EdgarClient(user_agent="TestCo test@test.com")
        
        responses.add(
            responses.GET,
            "https://data.sec.gov/submissions/CIK9999999999.json",
            status=404
        )
        
        with pytest.raises(NotFoundError):
            client._make_request(
                "https://data.sec.gov/submissions/CIK9999999999.json",
                use_cache=False
            )
            
    def test_context_manager(self):
        """Test context manager functionality."""
        with EdgarClient(user_agent="TestCo test@test.com") as client:
            assert client.user_agent == "TestCo test@test.com"
            
    def test_get_stats(self):
        """Test statistics retrieval."""
        client = EdgarClient(user_agent="TestCo test@test.com")
        
        stats = client.get_stats()
        
        assert 'rate_limiter' in stats
        assert 'cache' in stats
        assert 'cik_lookup' in stats
        
    def test_clear_cache(self):
        """Test cache clearing."""
        client = EdgarClient(user_agent="TestCo test@test.com")
        
        # Should not raise
        client.clear_cache()
        
    @responses.activate
    def test_extract_financial_metrics(self):
        """Test financial metrics extraction."""
        client = EdgarClient(user_agent="TestCo test@test.com")
        
        facts_data = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "val": 391035000000,
                                    "fy": 2024,
                                    "fp": "FY",
                                    "end": "2024-09-28"
                                },
                                {
                                    "val": 383285000000,
                                    "fy": 2023,
                                    "fp": "FY",
                                    "end": "2023-09-30"
                                }
                            ]
                        }
                    },
                    "NetIncomeLoss": {
                        "units": {
                            "USD": [
                                {
                                    "val": 96995000000,
                                    "fy": 2024,
                                    "fp": "FY",
                                    "end": "2024-09-28"
                                }
                            ]
                        }
                    }
                },
                "dei": {
                    "EntityNumberOfEmployees": {
                        "units": {
                            "shares": [
                                {
                                    "val": 161000,
                                    "end": "2024-09-28"
                                }
                            ]
                        }
                    }
                }
            }
        }
        
        metrics = client.extract_financial_metrics(facts_data)
        
        assert metrics.revenue_usd == 391035000000
        assert metrics.net_income_usd == 96995000000
        assert metrics.employee_count == 161000
        assert metrics.fiscal_year == "2024"
        
        # Check YoY growth calculation
        assert metrics.revenue_growth_yoy is not None
        assert metrics.revenue_growth_yoy > 0  # Should show growth
