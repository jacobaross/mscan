"""Core SEC EDGAR API client for brand enrichment.

This module provides a robust, rate-limited client for the SEC EDGAR API
that handles CIK lookup, company metadata retrieval, and financial data
extraction with proper caching and error handling.

Usage:
    from mscan.enricher.edgar_client import EdgarClient
    
    client = EdgarClient(user_agent="YourCompany contact@company.com")
    
    # Enrich by ticker
    result = client.enrich_by_ticker("AAPL")
    
    # Enrich by company name
    result = client.enrich_by_name("Apple Inc")
    
    # Enrich by CIK directly
    result = client.enrich_by_cik("0000320193")
"""

import json
import time
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path

import requests
import backoff

from mscan.utils.rate_limiter import RateLimiter
from mscan.enricher.cache_manager import CacheManager, CacheTier
from mscan.enricher.cik_lookup import CIKLookup, TickerNotFoundError, CompanyNotFoundError
from mscan.models.enriched_brand import (
    SECProfile,
    SECEntityMetadata,
    SECFilingsMetadata,
    FinancialMetrics,
    Filing,
    EnrichmentResult,
    EdgarAPIError,
)

logger = logging.getLogger(__name__)


class EdgarAPIException(Exception):
    """Base exception for EDGAR API errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, url: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.retryable = status_code in (429, 500, 502, 503, 504) if status_code else True


class RateLimitError(EdgarAPIException):
    """Raised when SEC rate limit is hit."""
    pass


class NotFoundError(EdgarAPIException):
    """Raised when a resource is not found."""
    
    def __init__(self, message: str, url: Optional[str] = None):
        super().__init__(message, status_code=404, url=url)
        self.retryable = False


class ServerError(EdgarAPIException):
    """Raised when SEC server returns an error."""
    pass


class EdgarClient:
    """Main client for SEC EDGAR API operations.
    
    Provides a high-level interface for enriching company data with SEC
    filings information. Handles rate limiting, caching, retries, and
    error recovery automatically.
    
    Args:
        user_agent: Required User-Agent string identifying your organization.
                   Must include contact email per SEC guidelines.
                   Format: "CompanyName ContactEmail@company.com"
        cache_dir: Directory for SQLite cache. Default: ~/.mscan/
        max_retries: Maximum number of retries for failed requests.
        
    Raises:
        ValueError: If user_agent is invalid or missing contact email.
        
    Example:
        >>> client = EdgarClient(user_agent="AcmeCorp api@acme.com")
        >>> result = client.enrich_by_ticker("AAPL")
        >>> if result.success:
        ...     print(result.brand.sec_profile.company_name)
    """
    
    BASE_URL = "https://data.sec.gov"
    SUBMISSIONS_ENDPOINT = "/submissions/CIK{cik}.json"
    COMPANY_FACTS_ENDPOINT = "/api/xbrl/companyfacts/CIK{cik}.json"
    COMPANY_CONCEPT_ENDPOINT = "/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{tag}.json"
    
    def __init__(
        self,
        user_agent: str,
        cache_dir: str = "~/.mscan",
        max_retries: int = 3
    ):
        # Validate user agent per SEC requirements
        if not user_agent:
            raise ValueError("User-Agent is required per SEC guidelines")
        if "@" not in user_agent:
            raise ValueError(
                "User-Agent must include contact email per SEC guidelines. "
                "Format: 'CompanyName contact@company.com'"
            )
        
        self.user_agent = user_agent
        self.headers = {"User-Agent": user_agent}
        self.max_retries = max_retries
        
        # Initialize components
        self.rate_limiter = RateLimiter(max_requests=10, window_seconds=1)
        self.cache = CacheManager(db_path=f"{cache_dir}/edgar_cache.db")
        self.cik_lookup = CIKLookup(self.cache, self.rate_limiter, user_agent)
        
        # Request tracking
        self._request_count = 0
        self._cache_hit_count = 0
        
        logger.info(f"EdgarClient initialized with user_agent: {user_agent[:30]}...")
    
    def _make_request(
        self,
        url: str,
        method: str = "GET",
        use_cache: bool = True,
        cache_key: Optional[str] = None,
        cache_tier: CacheTier = CacheTier.ENTITY_METADATA
    ) -> Dict[str, Any]:
        """Make a rate-limited API request with retry logic.
        
        Args:
            url: Full URL to request.
            method: HTTP method (GET, POST, etc.).
            use_cache: Whether to check cache before making request.
            cache_key: Cache key for storing response. Uses URL if None.
            cache_tier: Cache tier for TTL determination.
            
        Returns:
            Parsed JSON response as dict.
            
        Raises:
            RateLimitError: If rate limited by SEC.
            NotFoundError: If resource not found (404).
            ServerError: If SEC server error (5xx).
            EdgarAPIException: For other API errors.
        """
        cache_key = cache_key or url
        
        # Check cache
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                logger.debug(f"Cache hit for {cache_key}")
                self._cache_hit_count += 1
                return cached
        
        # Acquire rate limit token
        self.rate_limiter.acquire()
        
        # Make request with exponential backoff
        @backoff.on_exception(
            backoff.expo,
            (requests.RequestException, ServerError),
            max_tries=self.max_retries,
            giveup=lambda e: isinstance(e, (NotFoundError, RateLimitError)) or 
                           (isinstance(e, EdgarAPIException) and not e.retryable)
        )
        def _do_request():
            logger.debug(f"API request: {url}")
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    timeout=30
                )
                
                # Handle specific status codes
                if response.status_code == 403:
                    logger.warning("Rate limit exceeded (403)")
                    raise RateLimitError(
                        "Rate limit exceeded or blocked by SEC",
                        status_code=403,
                        url=url
                    )
                elif response.status_code == 404:
                    logger.debug(f"Resource not found: {url}")
                    raise NotFoundError(f"Resource not found: {url}", url=url)
                elif response.status_code == 429:
                    logger.warning("Rate limit exceeded (429)")
                    raise RateLimitError(
                        "Rate limit exceeded - too many requests",
                        status_code=429,
                        url=url
                    )
                elif response.status_code >= 500:
                    logger.warning(f"Server error {response.status_code}")
                    raise ServerError(
                        f"SEC server error: {response.status_code}",
                        status_code=response.status_code,
                        url=url
                    )
                
                response.raise_for_status()
                return response.json()
                
            except requests.Timeout:
                logger.warning(f"Request timeout: {url}")
                raise ServerError(f"Request timeout", url=url)
            except requests.RequestException as e:
                logger.error(f"Request failed: {e}")
                raise
        
        data = _do_request()
        self._request_count += 1
        
        # Cache the response
        if use_cache:
            self.cache.set(
                cache_key,
                data,
                tier=cache_tier,
                ticker=data.get('tickers', [None])[0] if isinstance(data.get('tickers'), list) else None,
                company_name=data.get('entityName')
            )
        
        return data
    
    def get_submissions(
        self,
        cik: str,
        use_cache: bool = True
    ) -> SECEntityMetadata:
        """Get company submissions (metadata + filings list).
        
        Args:
            cik: CIK number (will be zero-padded to 10 digits).
            use_cache: Whether to use cached data if available.
            
        Returns:
            SECEntityMetadata with company information and filings list.
            
        Raises:
            NotFoundError: If CIK not found.
            EdgarAPIException: For API errors.
        """
        cik = cik.zfill(10)
        url = f"{self.BASE_URL}{self.SUBMISSIONS_ENDPOINT.format(cik=cik)}"
        
        data = self._make_request(
            url,
            use_cache=use_cache,
            cache_key=f"submissions:{cik}",
            cache_tier=CacheTier.ENTITY_METADATA
        )
        
        # Build filings metadata
        filings_meta = self._parse_filings_metadata(data)
        
        # Build entity metadata
        entity_meta = SECEntityMetadata(
            cik=cik,
            entity_name=data.get('entityName', 'Unknown'),
            entity_type=data.get('entityType'),
            sic_code=data.get('sic'),
            sic_description=data.get('sicDescription'),
            tickers=data.get('tickers', []),
            exchanges=data.get('exchanges', []),
            ein=data.get('ein'),
            fiscal_year_end=data.get('fiscalYearEnd'),
            state_of_incorporation=data.get('stateOfIncorporation'),
            phone=data.get('phone')
        )
        
        return entity_meta, filings_meta
    
    def _parse_filings_metadata(self, data: Dict[str, Any]) -> SECFilingsMetadata:
        """Parse filings metadata from submissions response."""
        filings = data.get('filings', {}).get('recent', {})
        
        recent_filings = []
        forms = filings.get('form', [])
        dates = filings.get('filingDate', [])
        acc_nums = filings.get('accessionNumber', [])
        docs = filings.get('primaryDocument', [])
        
        for i in range(min(len(forms), 20)):  # Last 20 filings
            if i < len(forms):
                recent_filings.append(Filing(
                    accession_number=acc_nums[i] if i < len(acc_nums) else '',
                    filing_date=dates[i] if i < len(dates) else '',
                    form_type=forms[i],
                    primary_document=docs[i] if i < len(docs) else None
                ))
        
        # Count by type
        count_10k = sum(1 for f in forms if f == '10-K')
        count_10q = sum(1 for f in forms if f == '10-Q')
        count_8k = sum(1 for f in forms if f == '8-K')
        
        last_date = dates[0] if dates else None
        
        return SECFilingsMetadata(
            recent_filings=recent_filings,
            filing_count_10k=count_10k,
            filing_count_10q=count_10q,
            filing_count_8k=count_8k,
            last_filing_date=last_date
        )
    
    def get_company_facts(
        self,
        cik: str,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """Get all XBRL company facts.
        
        Args:
            cik: CIK number (will be zero-padded).
            use_cache: Whether to use cached data.
            
        Returns:
            Raw company facts data dict.
            
        Raises:
            NotFoundError: If CIK not found.
            EdgarAPIException: For API errors.
        """
        cik = cik.zfill(10)
        url = f"{self.BASE_URL}{self.COMPANY_FACTS_ENDPOINT.format(cik=cik)}"
        
        return self._make_request(
            url,
            use_cache=use_cache,
            cache_key=f"facts:{cik}",
            cache_tier=CacheTier.COMPANY_FACTS
        )
    
    def extract_financial_metrics(self, facts: Dict[str, Any]) -> FinancialMetrics:
        """Extract key financial metrics from company facts.
        
        Args:
            facts: Raw company facts data from get_company_facts().
            
        Returns:
            FinancialMetrics with extracted values.
        """
        metrics = FinancialMetrics()
        
        us_gaap = facts.get('facts', {}).get('us-gaap', {})
        dei = facts.get('facts', {}).get('dei', {})
        
        # Helper to get latest annual value
        def get_latest_annual(data_dict: Dict, tags: List[str], unit: str = 'USD'):
            for tag in tags:
                if tag in data_dict:
                    units = data_dict[tag].get('units', {}).get(unit, [])
                    annual = [u for u in units if u.get('fp') == 'FY']
                    if annual:
                        latest = max(annual, key=lambda x: x.get('end', ''))
                        return latest, annual
            return None, []
        
        # Revenue
        revenue_tags = [
            'Revenues',
            'RevenueFromContractWithCustomerExcludingAssessedTax',
            'SalesRevenueNet',
            'TotalRevenues'
        ]
        rev_data, rev_history = get_latest_annual(us_gaap, revenue_tags)
        if rev_data:
            metrics.revenue_usd = rev_data.get('val')
            metrics.fiscal_year = str(rev_data.get('fy', ''))
            metrics.period_end = rev_data.get('end')
            
            # Calculate YoY growth
            if len(rev_history) >= 2:
                sorted_hist = sorted(rev_history, key=lambda x: x.get('end', ''), reverse=True)
                current = sorted_hist[0]['val']
                previous = sorted_hist[1]['val']
                if previous and previous > 0:
                    metrics.revenue_growth_yoy = round((current - previous) / previous * 100, 2)
        
        # Net Income
        ni_data, _ = get_latest_annual(us_gaap, ['NetIncomeLoss'])
        if ni_data:
            metrics.net_income_usd = ni_data.get('val')
        
        # Total Assets
        assets_data, _ = get_latest_annual(us_gaap, ['Assets'])
        if assets_data:
            metrics.total_assets_usd = assets_data.get('val')
        
        # Employee Count (from dei namespace, shares unit)
        if 'EntityNumberOfEmployees' in dei:
            units = dei['EntityNumberOfEmployees'].get('units', {}).get('shares', [])
            if units:
                latest = max(units, key=lambda x: x.get('end', ''))
                metrics.employee_count = int(latest.get('val', 0))
        
        # Marketing/SG&A Expense
        sga_tags = ['SellingGeneralAndAdministrativeExpense', 'SellingAndMarketingExpense']
        sga_data, _ = get_latest_annual(us_gaap, sga_tags)
        if sga_data:
            metrics.marketing_spend_usd = sga_data.get('val')
        
        # R&D Expense
        rd_data, _ = get_latest_annual(us_gaap, ['ResearchAndDevelopmentExpense'])
        if rd_data:
            metrics.rd_spend_usd = rd_data.get('val')
        
        return metrics
    
    def enrich_by_cik(
        self,
        cik: str,
        ticker: Optional[str] = None
    ) -> EnrichmentResult:
        """Enrich company data by CIK.
        
        Args:
            cik: CIK number (will be zero-padded).
            ticker: Optional ticker symbol for the result.
            
        Returns:
            EnrichmentResult with profile or error information.
        """
        start_time = time.time()
        cik = cik.zfill(10)
        
        self._request_count = 0
        self._cache_hit_count = 0
        
        try:
            logger.info(f"Enriching CIK: {cik}")
            
            # Get submissions (entity metadata + filings)
            entity_meta, filings_meta = self.get_submissions(cik)
            
            # Get ticker from entity if not provided
            if not ticker and entity_meta.tickers:
                ticker = entity_meta.tickers[0]
            
            # Try to get company facts (may fail for some companies)
            financials = None
            try:
                facts = self.get_company_facts(cik)
                financials = self.extract_financial_metrics(facts)
            except NotFoundError:
                logger.warning(f"No company facts available for CIK {cik}")
            except Exception as e:
                logger.warning(f"Failed to extract financials for CIK {cik}: {e}")
            
            # Build SEC profile
            profile = SECProfile(
                cik=cik,
                ticker=ticker,
                company_name=entity_meta.entity_name,
                entity_metadata=entity_meta,
                sic_code=entity_meta.sic_code,
                sic_description=entity_meta.sic_description,
                exchange=entity_meta.exchanges[0] if entity_meta.exchanges else None,
                fiscal_year_end=entity_meta.fiscal_year_end,
                latest_financials=financials,
                filings_metadata=filings_meta,
                last_filing_date=filings_meta.last_filing_date,
                enriched_at=datetime.now(),
            )
            
            from mscan.models.enriched_brand import EnrichedBrand
            
            brand = EnrichedBrand(
                domain="",  # Will be set by caller if known
                is_publicly_traded=True,
                sec_profile=profile,
                confidence_level="high" if financials else "medium",
                data_completeness=0.8 if financials else 0.5
            )
            
            duration = time.time() - start_time
            
            return EnrichmentResult(
                success=True,
                brand=brand,
                api_calls_made=self._request_count,
                cache_hits=self._cache_hit_count,
                duration_seconds=duration
            )
            
        except NotFoundError as e:
            duration = time.time() - start_time
            return EnrichmentResult(
                success=False,
                error=EdgarAPIError(
                    error_type="not_found",
                    message=str(e),
                    status_code=404,
                    url=e.url,
                    retryable=False
                ),
                api_calls_made=self._request_count,
                cache_hits=self._cache_hit_count,
                duration_seconds=duration
            )
            
        except Exception as e:
            duration = time.time() - start_time
            logger.exception(f"Enrichment failed for CIK {cik}")
            return EnrichmentResult(
                success=False,
                error=EdgarAPIError(
                    error_type="enrichment_error",
                    message=str(e),
                    retryable=True
                ),
                api_calls_made=self._request_count,
                cache_hits=self._cache_hit_count,
                duration_seconds=duration
            )
    
    def enrich_by_ticker(self, ticker: str) -> EnrichmentResult:
        """Enrich company data by ticker symbol.
        
        Args:
            ticker: Stock ticker symbol (e.g., "AAPL").
            
        Returns:
            EnrichmentResult with profile or error information.
        """
        ticker = ticker.upper().strip()
        logger.info(f"Enriching by ticker: {ticker}")
        
        try:
            cik = self.cik_lookup.by_ticker(ticker)
            result = self.enrich_by_cik(cik, ticker=ticker)
            
            # Add domain if available in cache
            if result.success and result.brand:
                # Domain lookup would go here in Phase 2
                pass
            
            return result
            
        except TickerNotFoundError as e:
            return EnrichmentResult(
                success=False,
                error=EdgarAPIError(
                    error_type="ticker_not_found",
                    message=str(e),
                    retryable=False
                )
            )
        except Exception as e:
            logger.exception(f"Enrichment failed for ticker {ticker}")
            return EnrichmentResult(
                success=False,
                error=EdgarAPIError(
                    error_type="enrichment_error",
                    message=str(e),
                    retryable=True
                )
            )
    
    def enrich_by_name(
        self,
        name: str,
        min_confidence: float = 0.8
    ) -> EnrichmentResult:
        """Enrich company data by company name.
        
        Uses fuzzy matching to find the best matching company.
        
        Args:
            name: Company name to search for.
            min_confidence: Minimum match score (0.0-1.0) to accept.
            
        Returns:
            EnrichmentResult with profile or error information.
        """
        name = name.strip()
        logger.info(f"Enriching by name: {name}")
        
        try:
            matches = self.cik_lookup.by_name(name, limit=1)
            
            if not matches:
                return EnrichmentResult(
                    success=False,
                    error=EdgarAPIError(
                        error_type="company_not_found",
                        message=f"No companies found matching '{name}'",
                        retryable=False
                    )
                )
            
            best_match = matches[0]
            
            if best_match.match_score < min_confidence:
                return EnrichmentResult(
                    success=False,
                    error=EdgarAPIError(
                        error_type="low_confidence",
                        message=f"Best match '{best_match.company_name}' has low confidence ({best_match.match_score:.2f})",
                        retryable=False
                    )
                )
            
            result = self.enrich_by_cik(
                best_match.cik,
                ticker=best_match.ticker
            )
            
            # Adjust confidence based on name match
            if result.success and result.brand:
                if best_match.match_type != 'exact':
                    result.brand.confidence_level = "medium"
            
            return result
            
        except CompanyNotFoundError as e:
            return EnrichmentResult(
                success=False,
                error=EdgarAPIError(
                    error_type="company_not_found",
                    message=str(e),
                    retryable=False
                )
            )
        except Exception as e:
            logger.exception(f"Enrichment failed for name {name}")
            return EnrichmentResult(
                success=False,
                error=EdgarAPIError(
                    error_type="enrichment_error",
                    message=str(e),
                    retryable=True
                )
            )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics.
        
        Returns:
            Dict with rate limiter and cache statistics.
        """
        return {
            'rate_limiter': self.rate_limiter.get_stats().__dict__,
            'cache': self.cache.get_stats().__dict__,
            'cik_lookup': self.cik_lookup.get_stats(),
        }
    
    def clear_cache(self):
        """Clear all cached data."""
        self.cache.clear_all()
        logger.info("Cache cleared")
    
    def refresh_ticker_mapping(self) -> bool:
        """Refresh the ticker to CIK mapping from SEC.
        
        Returns:
            True if refresh successful, False otherwise.
        """
        return self.cik_lookup.refresh_mapping()
    
    def close(self):
        """Clean up resources and persist statistics."""
        self.cache.persist_stats()
        logger.info("EdgarClient closed")
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - clean up resources."""
        self.close()
