"""Tests for the enriched brand models."""

import pytest
from datetime import datetime

from mscan.models.enriched_brand import (
    FinancialMetrics,
    Filing,
    Executive,
    RiskFactor,
    RecentEvent,
    SECEntityMetadata,
    SECFilingsMetadata,
    SECProfile,
    EnrichedBrand,
    EnrichmentResult,
    EdgarAPIError,
)


class TestFinancialMetrics:
    """Test cases for FinancialMetrics model."""
    
    def test_create_minimal(self):
        """Test creating with minimal fields."""
        metrics = FinancialMetrics()
        assert metrics.revenue_usd is None
        
    def test_create_full(self):
        """Test creating with all fields."""
        metrics = FinancialMetrics(
            revenue_usd=1000000000,
            revenue_growth_yoy=15.5,
            net_income_usd=100000000,
            total_assets_usd=5000000000,
            marketing_spend_usd=50000000,
            rd_spend_usd=75000000,
            employee_count=5000,
            fiscal_year="2024",
            period_end="2024-09-30"
        )
        
        assert metrics.revenue_usd == 1000000000
        assert metrics.revenue_growth_yoy == 15.5
        assert metrics.fiscal_year == "2024"
        
    def test_serialization(self):
        """Test serialization to dict."""
        metrics = FinancialMetrics(revenue_usd=1000000, fiscal_year="2024")
        data = metrics.model_dump()
        
        assert data['revenue_usd'] == 1000000
        assert data['fiscal_year'] == "2024"
        
    def test_deserialization(self):
        """Test deserialization from dict."""
        data = {
            "revenue_usd": 1000000,
            "fiscal_year": "2024",
            "revenue_growth_yoy": None
        }
        
        metrics = FinancialMetrics.model_validate(data)
        assert metrics.revenue_usd == 1000000


class TestFiling:
    """Test cases for Filing model."""
    
    def test_create(self):
        """Test creating a filing."""
        filing = Filing(
            accession_number="0000320193-24-000123",
            filing_date="2024-02-02",
            form_type="10-K",
            primary_document="aapl-20231230.htm"
        )
        
        assert filing.accession_number == "0000320193-24-000123"
        assert filing.form_type == "10-K"


class TestExecutive:
    """Test cases for Executive model."""
    
    def test_create(self):
        """Test creating an executive."""
        exec_data = Executive(
            name="Tim Cook",
            title="Chief Executive Officer",
            is_ceo=True,
            is_cfo=False
        )
        
        assert exec_data.name == "Tim Cook"
        assert exec_data.is_ceo is True
        assert exec_data.compensation_usd is None


class TestSECEntityMetadata:
    """Test cases for SECEntityMetadata model."""
    
    def test_create_minimal(self):
        """Test minimal creation."""
        meta = SECEntityMetadata(
            cik="0000320193",
            entity_name="Apple Inc."
        )
        
        assert meta.cik == "0000320193"
        assert meta.entity_name == "Apple Inc."
        assert meta.tickers == []
        
    def test_create_full(self):
        """Test full creation."""
        meta = SECEntityMetadata(
            cik="0000320193",
            entity_name="Apple Inc.",
            entity_type="operating",
            sic_code="3571",
            sic_description="Electronic Computers",
            tickers=["AAPL"],
            exchanges=["Nasdaq"],
            ein="94-2404110",
            fiscal_year_end="0928",
            state_of_incorporation="CA",
            phone="(408) 996-1010"
        )
        
        assert meta.sic_code == "3571"
        assert meta.exchanges == ["Nasdaq"]


class TestSECProfile:
    """Test cases for SECProfile model."""
    
    def test_create_minimal(self):
        """Test minimal profile creation."""
        profile = SECProfile(
            cik="0000320193",
            company_name="Apple Inc."
        )
        
        assert profile.cik == "0000320193"
        assert profile.company_name == "Apple Inc."
        assert profile.data_source == "SEC EDGAR"
        
    def test_create_with_financials(self):
        """Test profile with financial data."""
        financials = FinancialMetrics(
            revenue_usd=391035000000,
            fiscal_year="2024"
        )
        
        profile = SECProfile(
            cik="0000320193",
            ticker="AAPL",
            company_name="Apple Inc.",
            latest_financials=financials,
            sic_description="Electronic Computers"
        )
        
        assert profile.latest_financials.revenue_usd == 391035000000
        assert profile.sic_description == "Electronic Computers"
        
    def test_serialization_roundtrip(self):
        """Test full serialization roundtrip."""
        profile = SECProfile(
            cik="0000320193",
            ticker="AAPL",
            company_name="Apple Inc.",
            latest_financials=FinancialMetrics(revenue_usd=1000000)
        )
        
        # Serialize
        data = profile.model_dump()
        
        # Deserialize
        profile2 = SECProfile.model_validate(data)
        
        assert profile2.cik == profile.cik
        assert profile2.latest_financials.revenue_usd == 1000000


class TestEnrichedBrand:
    """Test cases for EnrichedBrand model."""
    
    def test_create_minimal(self):
        """Test minimal brand creation."""
        brand = EnrichedBrand(
            domain="apple.com"
        )
        
        assert brand.domain == "apple.com"
        assert brand.is_publicly_traded is False
        assert brand.qualification_score == 0
        
    def test_create_with_sec_profile(self):
        """Test brand with SEC profile."""
        sec_profile = SECProfile(
            cik="0000320193",
            ticker="AAPL",
            company_name="Apple Inc."
        )
        
        brand = EnrichedBrand(
            domain="apple.com",
            is_publicly_traded=True,
            sec_profile=sec_profile,
            qualification_score=95,
            insights=["Fortune 50 company"],
            confidence_level="high"
        )
        
        assert brand.is_publicly_traded is True
        assert brand.sec_profile.ticker == "AAPL"
        assert brand.qualification_score == 95
        
    def test_qualification_score_validation(self):
        """Test qualification score bounds."""
        # Valid scores
        EnrichedBrand(domain="test.com", qualification_score=0)
        EnrichedBrand(domain="test.com", qualification_score=50)
        EnrichedBrand(domain="test.com", qualification_score=100)
        
        # Invalid scores should raise validation error
        with pytest.raises(Exception):  # pydantic.ValidationError
            EnrichedBrand(domain="test.com", qualification_score=-1)
            
        with pytest.raises(Exception):
            EnrichedBrand(domain="test.com", qualification_score=101)
            
    def test_data_completeness_validation(self):
        """Test data completeness bounds."""
        # Valid values
        EnrichedBrand(domain="test.com", data_completeness=0.0)
        EnrichedBrand(domain="test.com", data_completeness=0.5)
        EnrichedBrand(domain="test.com", data_completeness=1.0)
        
        # Invalid values
        with pytest.raises(Exception):
            EnrichedBrand(domain="test.com", data_completeness=-0.1)
            
        with pytest.raises(Exception):
            EnrichedBrand(domain="test.com", data_completeness=1.1)


class TestEnrichmentResult:
    """Test cases for EnrichmentResult model."""
    
    def test_success_result(self):
        """Test successful result."""
        brand = EnrichedBrand(domain="apple.com", is_publicly_traded=True)
        
        result = EnrichmentResult(
            success=True,
            brand=brand,
            api_calls_made=2,
            cache_hits=1,
            duration_seconds=1.5
        )
        
        assert result.success is True
        assert result.brand.domain == "apple.com"
        assert result.api_calls_made == 2
        
    def test_error_result(self):
        """Test error result."""
        error = EdgarAPIError(
            error_type="not_found",
            message="Company not found",
            status_code=404,
            retryable=False
        )
        
        result = EnrichmentResult(
            success=False,
            error=error,
            api_calls_made=1,
            duration_seconds=0.5
        )
        
        assert result.success is False
        assert result.error.error_type == "not_found"
        assert result.error.retryable is False
        
    def test_partial_result(self):
        """Test partial success with raw data."""
        result = EnrichmentResult(
            success=True,
            brand=EnrichedBrand(domain="test.com"),
            raw_data={"raw": "api response"},
            api_calls_made=3,
            cache_hits=0
        )
        
        assert result.raw_data == {"raw": "api response"}


class TestEdgarAPIError:
    """Test cases for EdgarAPIError model."""
    
    def test_create(self):
        """Test error creation."""
        error = EdgarAPIError(
            error_type="rate_limit",
            message="Too many requests",
            status_code=429,
            url="https://data.sec.gov/test",
            retryable=True
        )
        
        assert error.error_type == "rate_limit"
        assert error.status_code == 429
        assert error.retryable is True
        
    def test_default_retryable(self):
        """Test default retryable value."""
        error = EdgarAPIError(
            error_type="unknown",
            message="Something went wrong"
        )
        
        assert error.retryable is True  # Default
        assert error.status_code is None
