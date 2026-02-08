"""Pydantic data models for SEC EDGAR enriched brand data.

Defines structured models for company metadata, financials, and enriched profiles.
Compatible with Pydantic v2.
"""

from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict


class EntityType(str, Enum):
    """SEC entity types."""
    OPERATING = "operating"
    SHELL = "shell company"
    OTHER = "other"


class FilingType(str, Enum):
    """Common SEC filing form types."""
    FORM_10_K = "10-K"
    FORM_10_Q = "10-Q"
    FORM_8_K = "8-K"
    FORM_4 = "4"
    FORM_DEF_14A = "DEF 14A"
    FORM_S_1 = "S-1"
    FORM_13F = "13F-HR"
    FORM_20_F = "20-F"
    FORM_6_K = "6-K"


class FinancialMetrics(BaseModel):
    """Key financial metrics extracted from SEC filings.
    
    Attributes:
        revenue_usd: Annual revenue in USD.
        revenue_growth_yoy: Year-over-year revenue growth percentage.
        net_income_usd: Net income (profit/loss) in USD.
        total_assets_usd: Total assets in USD.
        marketing_spend_usd: Marketing/SG&A expenses in USD.
        rd_spend_usd: Research and development expenses in USD.
        employee_count: Number of employees.
        fiscal_year: Fiscal year identifier (e.g., "2024").
        period_end: End date of the reporting period (ISO format).
    """
    model_config = ConfigDict(populate_by_name=True)
    
    revenue_usd: Optional[int] = Field(None, description="Annual revenue in USD")
    revenue_growth_yoy: Optional[float] = Field(None, description="YoY revenue growth %")
    net_income_usd: Optional[int] = Field(None, description="Net income in USD")
    total_assets_usd: Optional[int] = Field(None, description="Total assets in USD")
    marketing_spend_usd: Optional[int] = Field(None, description="Marketing/SG&A spend in USD")
    rd_spend_usd: Optional[int] = Field(None, description="R&D spend in USD")
    employee_count: Optional[int] = Field(None, description="Employee count")
    fiscal_year: Optional[str] = Field(None, description="Fiscal year")
    period_end: Optional[str] = Field(None, description="Period end date (ISO)")


class Filing(BaseModel):
    """Represents a single SEC filing.
    
    Attributes:
        accession_number: Unique filing identifier.
        filing_date: Date filed (ISO format).
        form_type: Form type (e.g., "10-K").
        primary_document: Primary document filename.
        description: Brief description of filing content.
        url: URL to filing document.
    """
    model_config = ConfigDict(populate_by_name=True)
    
    accession_number: str = Field(..., description="Unique filing identifier")
    filing_date: str = Field(..., description="Filing date (ISO)")
    form_type: str = Field(..., description="Form type (e.g., 10-K)")
    primary_document: Optional[str] = Field(None, description="Primary document filename")
    description: Optional[str] = Field(None, description="Filing description")
    url: Optional[str] = Field(None, description="Document URL")
    size_bytes: Optional[int] = Field(None, description="Document size in bytes")


class Executive(BaseModel):
    """Company executive information.
    
    Attributes:
        name: Executive's full name.
        title: Job title.
        compensation_usd: Annual compensation in USD.
        tenure_years: Years in current role.
        is_ceo: Whether this is the CEO.
        is_cfo: Whether this is the CFO.
    """
    model_config = ConfigDict(populate_by_name=True)
    
    name: str = Field(..., description="Executive name")
    title: str = Field(..., description="Job title")
    compensation_usd: Optional[int] = Field(None, description="Annual compensation")
    tenure_years: Optional[float] = Field(None, description="Years in role")
    is_ceo: bool = Field(False, description="Is CEO")
    is_cfo: bool = Field(False, description="Is CFO")


class RiskFactor(BaseModel):
    """Risk factor disclosure from 10-K.
    
    Attributes:
        category: Risk category (e.g., "Competition").
        summary: Brief summary of the risk.
        severity: Risk severity level.
        raw_text: Original disclosure text.
    """
    model_config = ConfigDict(populate_by_name=True)
    
    category: str = Field(..., description="Risk category")
    summary: str = Field(..., description="Risk summary")
    severity: str = Field("medium", description="Severity: high/medium/low")
    raw_text: Optional[str] = Field(None, description="Original disclosure text")


class RecentEvent(BaseModel):
    """Recent material event from 8-K filings.
    
    Attributes:
        date: Event date (ISO format).
        form_type: Filing form type.
        summary: Event summary.
        url: Filing URL.
        items: Specific 8-K item numbers triggered.
    """
    model_config = ConfigDict(populate_by_name=True)
    
    date: str = Field(..., description="Event date (ISO)")
    form_type: str = Field(default="8-K", description="Form type")
    summary: Optional[str] = Field(None, description="Event summary")
    url: Optional[str] = Field(None, description="Filing URL")
    items: List[str] = Field(default_factory=list, description="8-K item numbers")


class SECFilingsMetadata(BaseModel):
    """Metadata about available SEC filings.
    
    Attributes:
        recent_filings: List of recent filings.
        filing_count_10k: Number of 10-K filings available.
        filing_count_10q: Number of 10-Q filings available.
        filing_count_8k: Number of 8-K filings available.
        last_filing_date: Date of most recent filing.
    """
    model_config = ConfigDict(populate_by_name=True)
    
    recent_filings: List[Filing] = Field(default_factory=list)
    filing_count_10k: int = Field(0, description="10-K count")
    filing_count_10q: int = Field(0, description="10-Q count")
    filing_count_8k: int = Field(0, description="8-K count")
    last_filing_date: Optional[str] = Field(None, description="Last filing date")


class SECEntityMetadata(BaseModel):
    """SEC entity metadata from submissions endpoint.
    
    Attributes:
        cik: Central Index Key (10-digit padded).
        entity_name: Legal entity name.
        entity_type: Type of entity.
        sic_code: Standard Industrial Classification code.
        sic_description: SIC code description.
        industry: Industry classification.
        sector: Business sector.
        tickers: List of ticker symbols.
        exchanges: List of stock exchanges.
        ein: Employer Identification Number.
        fiscal_year_end: Fiscal year end (MMDD format).
        state_of_incorporation: State of incorporation.
        phone: Contact phone number.
    """
    model_config = ConfigDict(populate_by_name=True)
    
    cik: str = Field(..., description="CIK (10-digit)")
    entity_name: str = Field(..., description="Legal entity name")
    entity_type: Optional[str] = Field(None, description="Entity type")
    sic_code: Optional[str] = Field(None, description="SIC code")
    sic_description: Optional[str] = Field(None, description="SIC description")
    industry: Optional[str] = Field(None, description="Industry")
    sector: Optional[str] = Field(None, description="Sector")
    tickers: List[str] = Field(default_factory=list, description="Ticker symbols")
    exchanges: List[str] = Field(default_factory=list, description="Stock exchanges")
    ein: Optional[str] = Field(None, description="EIN")
    fiscal_year_end: Optional[str] = Field(None, description="Fiscal year end (MMDD)")
    state_of_incorporation: Optional[str] = Field(None, description="State of incorporation")
    phone: Optional[str] = Field(None, description="Contact phone")


class SECProfile(BaseModel):
    """Complete SEC profile for a public company.
    
    Combines entity metadata, financial metrics, filings, and derived insights.
    
    Attributes:
        cik: Central Index Key.
        ticker: Primary ticker symbol.
        company_name: Company name.
        legal_name: Full legal name if different.
        entity_metadata: Raw entity metadata.
        sic_code: SIC classification code.
        sic_description: SIC code description.
        industry: Industry classification.
        sector: Business sector.
        exchange: Primary stock exchange.
        fiscal_year_end: Fiscal year end date.
        latest_financials: Most recent financial metrics.
        financial_history: Historical financial data.
        key_executives: List of key executives.
        ceo_name: CEO name.
        cfo_name: CFO name.
        business_description: Business description from filings.
        key_products: List of key products/services.
        risk_factors: List of disclosed risk factors.
        recent_events: Recent material events.
        insider_activity: Insider trading sentiment.
        filings_metadata: Filing availability metadata.
        last_filing_date: Date of most recent filing.
        data_source: Source of data (always "SEC EDGAR").
        enriched_at: When data was enriched.
        cache_expires_at: When cached data expires.
    """
    model_config = ConfigDict(populate_by_name=True)
    
    # Identity
    cik: str = Field(..., description="CIK")
    ticker: Optional[str] = Field(None, description="Primary ticker")
    company_name: str = Field(..., description="Company name")
    legal_name: Optional[str] = Field(None, description="Legal name")
    
    # Classification
    entity_metadata: Optional[SECEntityMetadata] = Field(None, description="Raw entity metadata")
    sic_code: Optional[str] = Field(None, description="SIC code")
    sic_description: Optional[str] = Field(None, description="SIC description")
    industry: Optional[str] = Field(None, description="Industry")
    sector: Optional[str] = Field(None, description="Sector")
    
    # Market Data
    exchange: Optional[str] = Field(None, description="Primary exchange")
    fiscal_year_end: Optional[str] = Field(None, description="Fiscal year end")
    
    # Financials
    latest_financials: Optional[FinancialMetrics] = Field(None, description="Latest financials")
    financial_history: List[FinancialMetrics] = Field(default_factory=list, description="Financial history")
    
    # Leadership
    key_executives: List[Executive] = Field(default_factory=list, description="Key executives")
    ceo_name: Optional[str] = Field(None, description="CEO name")
    cfo_name: Optional[str] = Field(None, description="CFO name")
    
    # Strategy & Risk
    business_description: Optional[str] = Field(None, description="Business description")
    key_products: List[str] = Field(default_factory=list, description="Key products")
    risk_factors: List[RiskFactor] = Field(default_factory=list, description="Risk factors")
    
    # Recent Activity
    recent_events: List[RecentEvent] = Field(default_factory=list, description="Recent events")
    insider_activity: str = Field("neutral", description="Insider sentiment")
    
    # Filings
    filings_metadata: Optional[SECFilingsMetadata] = Field(None, description="Filings metadata")
    last_filing_date: Optional[str] = Field(None, description="Last filing date")
    
    # Metadata
    data_source: str = Field(default="SEC EDGAR", description="Data source")
    enriched_at: Optional[datetime] = Field(None, description="Enrichment timestamp")
    cache_expires_at: Optional[datetime] = Field(None, description="Cache expiry")


class EnrichedBrand(BaseModel):
    """Complete enriched brand profile combining mscan + SEC data.
    
    This is the top-level model that combines website scan data with
    SEC enrichment for a comprehensive brand profile.
    
    Attributes:
        domain: Website domain.
        scanned_at: When website was scanned.
        detected_technologies: List of detected martech vendors.
        sec_profile: SEC profile if publicly traded.
        is_publicly_traded: Whether company is publicly traded.
        qualification_score: Marketing qualification score (0-100).
        insights: Generated marketing insights.
        recommendations: Actionable recommendations.
        confidence_level: Data confidence level.
        data_completeness: Completeness ratio (0.0-1.0).
    """
    model_config = ConfigDict(populate_by_name=True)
    
    # Original mscan data
    domain: str = Field(..., description="Website domain")
    scanned_at: Optional[datetime] = Field(None, description="Scan timestamp")
    detected_technologies: List[Dict[str, Any]] = Field(default_factory=list)
    
    # SEC enrichment
    sec_profile: Optional[SECProfile] = Field(None, description="SEC profile")
    is_publicly_traded: bool = Field(False, description="Is publicly traded")
    
    # Qualification
    qualification_score: int = Field(0, ge=0, le=100, description="Qualification score")
    insights: List[str] = Field(default_factory=list, description="Marketing insights")
    recommendations: List[str] = Field(default_factory=list, description="Recommendations")
    
    # Confidence
    confidence_level: str = Field("low", description="Confidence: high/medium/low")
    data_completeness: float = Field(0.0, ge=0.0, le=1.0, description="Data completeness")


class EdgarAPIError(BaseModel):
    """Error information from EDGAR API calls.
    
    Attributes:
        error_type: Type of error.
        message: Human-readable error message.
        status_code: HTTP status code if applicable.
        url: API URL that caused the error.
        retryable: Whether the request can be retried.
    """
    model_config = ConfigDict(populate_by_name=True)
    
    error_type: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    status_code: Optional[int] = Field(None, description="HTTP status code")
    url: Optional[str] = Field(None, description="Request URL")
    retryable: bool = Field(True, description="Is retryable")


class EnrichmentResult(BaseModel):
    """Result of an enrichment operation.
    
    Contains either a successful profile or error information.
    
    Attributes:
        success: Whether enrichment succeeded.
        brand: Enriched brand profile if successful.
        error: Error information if failed.
        raw_data: Raw API response data.
        api_calls_made: Number of API calls made.
        cache_hits: Number of cache hits.
        duration_seconds: Time taken for enrichment.
    """
    model_config = ConfigDict(populate_by_name=True)
    
    success: bool = Field(..., description="Success flag")
    brand: Optional[EnrichedBrand] = Field(None, description="Enriched brand")
    error: Optional[EdgarAPIError] = Field(None, description="Error info")
    raw_data: Optional[Dict[str, Any]] = Field(None, description="Raw API data")
    api_calls_made: int = Field(0, description="API calls count")
    cache_hits: int = Field(0, description="Cache hits count")
    duration_seconds: Optional[float] = Field(None, description="Duration")
