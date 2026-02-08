"""Tests for the profile builder module."""

import pytest
from datetime import datetime

from mscan.enricher.profile_builder import ProfileBuilder, ProfileBuilderError
from mscan.models.enriched_brand import (
    EnrichedBrand,
    SECProfile,
    FinancialMetrics,
    SECEntityMetadata,
    SECFilingsMetadata,
    EnrichmentResult,
)


class TestProfileBuilder:
    """Test cases for ProfileBuilder."""
    
    def test_init_default_values(self):
        """Test initialization with default values."""
        builder = ProfileBuilder()
        assert builder.min_revenue_threshold == 0
        assert builder.min_employee_threshold == 0
    
    def test_init_custom_values(self):
        """Test initialization with custom values."""
        builder = ProfileBuilder(
            min_revenue_threshold=1_000_000,
            min_employee_threshold=50
        )
        assert builder.min_revenue_threshold == 1_000_000
        assert builder.min_employee_threshold == 50
    
    def test_build_profile_minimal(self):
        """Test building profile with minimal data."""
        builder = ProfileBuilder()
        
        brand = builder.build_profile(domain="example.com")
        
        assert brand.domain == "example.com"
        assert brand.is_publicly_traded is False
        assert brand.qualification_score >= 0
        assert brand.confidence_level in ["low", "medium", "high"]
        assert isinstance(brand.insights, list)
        assert isinstance(brand.recommendations, list)
    
    def test_build_profile_with_scan_data(self):
        """Test building profile with scan data."""
        builder = ProfileBuilder()
        
        scan_data = {
            "detected_technologies": [
                {"vendor": "Google Analytics", "category": "Analytics"},
                {"vendor": "Meta Pixel", "category": "Social Media"}
            ],
            "requests": ["https://example.com"],
            "scanned_at": datetime.now()
        }
        
        brand = builder.build_profile(
            domain="example.com",
            scan_data=scan_data
        )
        
        assert brand.domain == "example.com"
        assert len(brand.detected_technologies) == 2
        assert brand.is_publicly_traded is False
    
    def test_build_profile_with_sec_data(self):
        """Test building profile with SEC data."""
        builder = ProfileBuilder()
        
        financials = FinancialMetrics(
            revenue_usd=10_000_000_000,  # $10B
            net_income_usd=1_000_000_000,
            employee_count=50_000,
            fiscal_year="2024"
        )
        
        sec_profile = SECProfile(
            cik="0000320193",
            ticker="AAPL",
            company_name="Test Company Inc",
            sic_code="3571",
            sic_description="Electronic Computers",
            exchange="Nasdaq",
            latest_financials=financials,
            enriched_at=datetime.now()
        )
        
        brand = builder.build_profile(
            domain="test.com",
            sec_profile=sec_profile
        )
        
        assert brand.is_publicly_traded is True
        assert brand.sec_profile == sec_profile
        assert brand.qualification_score > 0
        assert len(brand.insights) > 0
        assert len(brand.recommendations) > 0
    
    def test_calculate_qualification_score_revenue_tiers(self):
        """Test qualification scoring based on revenue tiers."""
        builder = ProfileBuilder()
        
        # Test different revenue levels
        test_cases = [
            (1_000_000_000_000, 100),  # $1T
            (100_000_000_000, 90),     # $100B
            (10_000_000_000, 80),      # $10B
            (1_000_000_000, 70),       # $1B
            (500_000_000, 60),         # $500M
            (100_000_000, 50),         # $100M
            (10_000_000, 40),          # $10M
            (1_000_000, 30),           # $1M
        ]
        
        for revenue, min_expected_score in test_cases:
            financials = FinancialMetrics(revenue_usd=revenue)
            sec_profile = SECProfile(
                cik="0000000000",
                company_name="Test",
                latest_financials=financials,
                enriched_at=datetime.now()
            )
            
            score = builder._calculate_qualification_score(sec_profile, [])
            assert score >= min_expected_score, f"Revenue ${revenue} should score at least {min_expected_score}"
    
    def test_calculate_qualification_score_employee_tiers(self):
        """Test qualification scoring based on employee tiers."""
        builder = ProfileBuilder()
        
        test_cases = [
            (100_000, 25),  # 100K employees
            (10_000, 20),   # 10K employees
            (1_000, 15),    # 1K employees
            (100, 10),      # 100 employees
        ]
        
        for employees, expected_points in test_cases:
            financials = FinancialMetrics(
                revenue_usd=10_000_000,  # Base revenue
                employee_count=employees
            )
            sec_profile = SECProfile(
                cik="0000000000",
                company_name="Test",
                latest_financials=financials,
                enriched_at=datetime.now()
            )
            
            score = builder._calculate_qualification_score(sec_profile, [])
            # Should have revenue points + employee points
            assert score >= expected_points
    
    def test_calculate_qualification_score_marketing_spend(self):
        """Test qualification scoring with marketing spend."""
        builder = ProfileBuilder()
        
        # 15% of revenue spent on marketing
        financials = FinancialMetrics(
            revenue_usd=1_000_000_000,
            marketing_spend_usd=150_000_000
        )
        sec_profile = SECProfile(
            cik="0000000000",
            company_name="Test",
            latest_financials=financials,
            enriched_at=datetime.now()
        )
        
        score = builder._calculate_qualification_score(sec_profile, [])
        # Revenue (70) + marketing spend (15) = 85
        assert score >= 85
    
    def test_calculate_qualification_score_rd_spend(self):
        """Test qualification scoring with R&D spend."""
        builder = ProfileBuilder()
        
        # 12% of revenue spent on R&D
        financials = FinancialMetrics(
            revenue_usd=1_000_000_000,
            rd_spend_usd=120_000_000
        )
        sec_profile = SECProfile(
            cik="0000000000",
            company_name="Test",
            latest_financials=financials,
            enriched_at=datetime.now()
        )
        
        score = builder._calculate_qualification_score(sec_profile, [])
        # Revenue (70) + R&D (10) = 80
        assert score >= 80
    
    def test_calculate_qualification_score_no_sec_data(self):
        """Test scoring without SEC data."""
        builder = ProfileBuilder()
        
        technologies = [
            {"vendor": "Google Analytics"},
            {"vendor": "Meta Pixel"},
            {"vendor": "HubSpot"}
        ]
        
        score = builder._calculate_qualification_score(None, technologies)
        # Base score based on tech count (5 points each, max 40)
        assert score == min(len(technologies) * 5, 40)
    
    def test_generate_insights_revenue(self):
        """Test insight generation for revenue tiers."""
        builder = ProfileBuilder()
        
        test_cases = [
            (150_000_000_000, "Fortune 100"),
            (50_000_000_000, "Large enterprise"),
            (5_000_000_000, "Mid-market"),
            (500_000_000, "Growth company"),
        ]
        
        for revenue, expected_term in test_cases:
            financials = FinancialMetrics(revenue_usd=revenue)
            sec_profile = SECProfile(
                cik="0000000000",
                company_name="Test",
                latest_financials=financials,
                enriched_at=datetime.now()
            )
            brand = builder.build_profile("test.com", sec_profile=sec_profile)
            
            insight_text = " ".join(brand.insights)
            assert expected_term in insight_text
    
    def test_generate_insights_growth(self):
        """Test insight generation for growth rates."""
        builder = ProfileBuilder()
        
        # High growth
        financials = FinancialMetrics(
            revenue_usd=1_000_000_000,
            revenue_growth_yoy=25.0
        )
        sec_profile = SECProfile(
            cik="0000000000",
            company_name="Test",
            latest_financials=financials,
            enriched_at=datetime.now()
        )
        brand = builder.build_profile("test.com", sec_profile=sec_profile)
        
        insight_text = " ".join(brand.insights)
        assert "growth" in insight_text.lower()
    
    def test_generate_insights_employees(self):
        """Test insight generation for employee counts."""
        builder = ProfileBuilder()
        
        financials = FinancialMetrics(
            revenue_usd=1_000_000_000,
            employee_count=150_000
        )
        sec_profile = SECProfile(
            cik="0000000000",
            company_name="Test",
            latest_financials=financials,
            enriched_at=datetime.now()
        )
        brand = builder.build_profile("test.com", sec_profile=sec_profile)
        
        insight_text = " ".join(brand.insights)
        assert "150,000" in insight_text or "employee" in insight_text.lower()
    
    def test_generate_insights_marketing_spend(self):
        """Test insight generation for marketing spend."""
        builder = ProfileBuilder()
        
        financials = FinancialMetrics(
            revenue_usd=1_000_000_000,
            marketing_spend_usd=100_000_000
        )
        sec_profile = SECProfile(
            cik="0000000000",
            company_name="Test",
            latest_financials=financials,
            enriched_at=datetime.now()
        )
        brand = builder.build_profile("test.com", sec_profile=sec_profile)
        
        insight_text = " ".join(brand.insights)
        assert "100M" in insight_text or "marketing" in insight_text.lower()
    
    def test_generate_insights_rd_spend(self):
        """Test insight generation for R&D spend."""
        builder = ProfileBuilder()
        
        financials = FinancialMetrics(
            revenue_usd=1_000_000_000,
            rd_spend_usd=150_000_000
        )
        sec_profile = SECProfile(
            cik="0000000000",
            company_name="Test",
            latest_financials=financials,
            enriched_at=datetime.now()
        )
        brand = builder.build_profile("test.com", sec_profile=sec_profile)
        
        insight_text = " ".join(brand.insights)
        assert "R&D" in insight_text or "Research" in insight_text
    
    def test_generate_recommendations_enterprise(self):
        """Test recommendations for enterprise companies."""
        builder = ProfileBuilder()
        
        financials = FinancialMetrics(revenue_usd=50_000_000_000)
        sec_profile = SECProfile(
            cik="0000000000",
            company_name="Test",
            latest_financials=financials,
            enriched_at=datetime.now()
        )
        brand = builder.build_profile("test.com", sec_profile=sec_profile)
        
        rec_text = " ".join(brand.recommendations)
        assert "Enterprise" in rec_text or "multi-stakeholder" in rec_text.lower()
    
    def test_generate_recommendations_midmarket(self):
        """Test recommendations for mid-market companies."""
        builder = ProfileBuilder()
        
        financials = FinancialMetrics(revenue_usd=5_000_000_000)
        sec_profile = SECProfile(
            cik="0000000000",
            company_name="Test",
            latest_financials=financials,
            enriched_at=datetime.now()
        )
        brand = builder.build_profile("test.com", sec_profile=sec_profile)
        
        rec_text = " ".join(brand.recommendations)
        assert "mid-market" in rec_text.lower() or "scalability" in rec_text.lower()
    
    def test_generate_recommendations_growth(self):
        """Test recommendations for growth companies."""
        builder = ProfileBuilder()
        
        financials = FinancialMetrics(revenue_usd=100_000_000)
        sec_profile = SECProfile(
            cik="0000000000",
            company_name="Test",
            latest_financials=financials,
            enriched_at=datetime.now()
        )
        brand = builder.build_profile("test.com", sec_profile=sec_profile)
        
        rec_text = " ".join(brand.recommendations)
        assert "Growth" in rec_text or "quick time-to-value" in rec_text.lower()
    
    def test_generate_recommendations_under_invested_marketing(self):
        """Test recommendations for low marketing spend."""
        builder = ProfileBuilder()
        
        financials = FinancialMetrics(
            revenue_usd=1_000_000_000,
            marketing_spend_usd=20_000_000  # 2% of revenue
        )
        sec_profile = SECProfile(
            cik="0000000000",
            company_name="Test",
            latest_financials=financials,
            enriched_at=datetime.now()
        )
        brand = builder.build_profile("test.com", sec_profile=sec_profile)
        
        rec_text = " ".join(brand.recommendations)
        assert "Under-invested" in rec_text or "budget expansion" in rec_text.lower()
    
    def test_generate_recommendations_high_rd(self):
        """Test recommendations for high R&D spend."""
        builder = ProfileBuilder()
        
        financials = FinancialMetrics(
            revenue_usd=1_000_000_000,
            rd_spend_usd=200_000_000  # 20% of revenue
        )
        sec_profile = SECProfile(
            cik="0000000000",
            company_name="Test",
            latest_financials=financials,
            enriched_at=datetime.now()
        )
        brand = builder.build_profile("test.com", sec_profile=sec_profile)
        
        rec_text = " ".join(brand.recommendations)
        assert "Innovation-focused" in rec_text or "cutting-edge" in rec_text.lower()
    
    def test_generate_recommendations_missing_tech(self):
        """Test recommendations for missing martech categories."""
        builder = ProfileBuilder()
        
        financials = FinancialMetrics(revenue_usd=5_000_000_000)
        sec_profile = SECProfile(
            cik="0000000000",
            company_name="Test",
            latest_financials=financials,
            enriched_at=datetime.now()
        )
        
        # No technologies detected
        scan_data = {"detected_technologies": []}
        brand = builder.build_profile("test.com", scan_data=scan_data, sec_profile=sec_profile)
        
        rec_text = " ".join(brand.recommendations)
        assert "analytics" in rec_text.lower() or "CDP" in rec_text or "social" in rec_text.lower()
    
    def test_calculate_data_completeness(self):
        """Test data completeness calculation."""
        builder = ProfileBuilder()
        
        # Empty data
        completeness = builder._calculate_data_completeness({}, None)
        assert completeness == 0.0
        
        # With scan data only
        completeness = builder._calculate_data_completeness(
            {"detected_technologies": [1, 2], "requests": [], "scanned_at": datetime.now()},
            None
        )
        assert completeness > 0.0
        
        # With full data
        sec_profile = SECProfile(
            cik="0000000000",
            company_name="Test",
            sic_code="1234",
            exchange="Nasdaq",
            latest_financials=FinancialMetrics(),
            filings_metadata=SECFilingsMetadata(),
            entity_metadata=SECEntityMetadata(cik="0000000000", entity_name="Test"),
            enriched_at=datetime.now()
        )
        completeness = builder._calculate_data_completeness(
            {"detected_technologies": [1, 2], "requests": [], "scanned_at": datetime.now()},
            sec_profile
        )
        assert completeness >= 0.8
    
    def test_determine_confidence_level(self):
        """Test confidence level determination."""
        builder = ProfileBuilder()
        
        brand = EnrichedBrand(domain="test.com", data_completeness=0.95)
        assert builder._determine_confidence_level(brand) == "high"
        
        brand = EnrichedBrand(domain="test.com", data_completeness=0.75)
        assert builder._determine_confidence_level(brand) == "medium"
        
        brand = EnrichedBrand(domain="test.com", data_completeness=0.3)
        assert builder._determine_confidence_level(brand) == "low"
    
    def test_build_profile_from_enrichment_success(self):
        """Test building profile from successful enrichment result."""
        builder = ProfileBuilder()
        
        sec_profile = SECProfile(
            cik="0000320193",
            ticker="AAPL",
            company_name="Apple Inc",
            latest_financials=FinancialMetrics(revenue_usd=391_000_000_000),
            enriched_at=datetime.now()
        )
        
        enrichment_result = EnrichmentResult(
            success=True,
            brand=EnrichedBrand(
                domain="",
                sec_profile=sec_profile,
                is_publicly_traded=True,
                qualification_score=0
            ),
            api_calls_made=2,
            cache_hits=1,
            duration_seconds=1.5
        )
        
        brand = builder.build_profile_from_enrichment(
            domain="apple.com",
            enrichment_result=enrichment_result
        )
        
        assert brand.domain == "apple.com"
        assert brand.is_publicly_traded is True
        assert brand.sec_profile.company_name == "Apple Inc"
        assert brand.qualification_score > 0
    
    def test_build_profile_from_enrichment_failure(self):
        """Test building profile from failed enrichment result."""
        builder = ProfileBuilder()
        
        enrichment_result = EnrichmentResult(
            success=False,
            error=None,  # Would normally have error details
            api_calls_made=1,
            cache_hits=0,
            duration_seconds=0.5
        )
        
        scan_data = {
            "detected_technologies": [
                {"vendor": "Google Analytics", "category": "Analytics"}
            ]
        }
        
        brand = builder.build_profile_from_enrichment(
            domain="private.com",
            enrichment_result=enrichment_result,
            scan_data=scan_data
        )
        
        assert brand.domain == "private.com"
        assert brand.is_publicly_traded is False
        assert brand.sec_profile is None
        assert len(brand.detected_technologies) == 1
    
    def test_scan_data_vendor_conversion(self):
        """Test conversion of scan data vendors to detected technologies."""
        builder = ProfileBuilder()
        
        scan_data = {
            "vendors": [
                {"vendor_name": "Google Analytics", "category": "Analytics"},
                {"vendor_name": "Meta Pixel", "category": "Social Media"}
            ]
        }
        
        brand = builder.build_profile("test.com", scan_data=scan_data)
        
        assert len(brand.detected_technologies) == 2
        assert brand.detected_technologies[0]["vendor"] == "Google Analytics"
        assert brand.detected_technologies[0]["category"] == "Analytics"
