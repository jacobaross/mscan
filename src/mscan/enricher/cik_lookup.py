"""CIK lookup module for resolving tickers and company names to CIK numbers.

Provides functionality to:
- Fetch and cache the SEC's company_tickers.json mapping
- Lookup CIK by ticker symbol
- Fuzzy match company names to CIK
- Handle edge cases like delisted companies and name changes
"""

import re
import json
import logging
from typing import Optional, Dict, List, Tuple, Any
from difflib import SequenceMatcher, get_close_matches
from dataclasses import dataclass

import requests

from mscan.enricher.cache_manager import CacheManager, CacheTier
from mscan.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


@dataclass
class CompanyMatch:
    """Represents a potential company match from name search."""
    cik: str
    ticker: str
    company_name: str
    match_score: float  # 0.0 to 1.0
    match_type: str  # 'exact', 'fuzzy', 'ticker'


class CIKLookupError(Exception):
    """Base exception for CIK lookup errors."""
    pass


class TickerNotFoundError(CIKLookupError):
    """Raised when a ticker symbol cannot be resolved."""
    pass


class CompanyNotFoundError(CIKLookupError):
    """Raised when a company name cannot be matched."""
    pass


class CIKLookup:
    """CIK lookup service for resolving tickers and company names.
    
    Manages the SEC's company_tickers.json mapping file with local caching
    and provides fuzzy name matching capabilities.
    
    Args:
        cache_manager: CacheManager instance for storing ticker mappings.
        rate_limiter: RateLimiter instance for API requests.
        user_agent: User-Agent string required by SEC.
        
    Example:
        >>> lookup = CIKLookup(cache_manager, rate_limiter, "YourCo contact@you.com")
        >>> cik = lookup.by_ticker("AAPL")
        >>> matches = lookup.by_name("Apple Inc", limit=3)
    """
    
    TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
    MIN_MATCH_SCORE = 0.6  # Minimum fuzzy match score (0.0 to 1.0)
    
    def __init__(
        self,
        cache_manager: CacheManager,
        rate_limiter: RateLimiter,
        user_agent: str
    ):
        self.cache = cache_manager
        self.rate_limiter = rate_limiter
        self.user_agent = user_agent
        self.headers = {"User-Agent": user_agent}
        
        # In-memory cache of ticker mappings
        self._ticker_to_cik: Dict[str, str] = {}
        self._cik_to_ticker: Dict[str, str] = {}
        self._company_names: Dict[str, str] = {}  # cik -> name
        self._name_to_cik: Dict[str, str] = {}    # normalized name -> cik
        self._loaded = False
        
        logger.debug("CIKLookup initialized")
    
    def _load_mapping(self, force_refresh: bool = False) -> bool:
        """Load ticker to CIK mapping from cache or SEC.
        
        Args:
            force_refresh: If True, ignore cache and fetch fresh data.
            
        Returns:
            True if mapping loaded successfully, False otherwise.
        """
        if self._loaded and not force_refresh:
            return True
        
        # Try cache first
        if not force_refresh:
            cached = self.cache.get("__ticker_mapping__")
            if cached:
                try:
                    self._ticker_to_cik = cached.get('ticker_to_cik', {})
                    self._cik_to_ticker = cached.get('cik_to_ticker', {})
                    self._company_names = cached.get('company_names', {})
                    self._name_to_cik = cached.get('name_to_cik', {})
                    self._loaded = True
                    logger.info(f"Loaded ticker mapping from cache ({len(self._ticker_to_cik)} entries)")
                    return True
                except Exception as e:
                    logger.warning(f"Failed to load cached mapping: {e}")
        
        # Fetch from SEC
        try:
            logger.info("Fetching ticker mapping from SEC...")
            self.rate_limiter.acquire()
            
            response = requests.get(
                self.TICKER_URL,
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Build mappings
            self._ticker_to_cik = {}
            self._cik_to_ticker = {}
            self._company_names = {}
            self._name_to_cik = {}
            
            for entry in data.values():
                ticker = entry['ticker'].upper()
                cik = str(entry['cik_str']).zfill(10)
                name = entry['title']
                
                self._ticker_to_cik[ticker] = cik
                self._cik_to_ticker[cik] = ticker
                self._company_names[cik] = name
                
                # Index normalized name for fuzzy search
                normalized = self._normalize_name(name)
                self._name_to_cik[normalized] = cik
            
            # Cache the mapping
            self.cache.set(
                "__ticker_mapping__",
                {
                    'ticker_to_cik': self._ticker_to_cik,
                    'cik_to_ticker': self._cik_to_ticker,
                    'company_names': self._company_names,
                    'name_to_cik': self._name_to_cik,
                    'fetched_at': json.dumps(str(__import__('datetime').datetime.now()))
                },
                tier=CacheTier.TICKER_MAPPING
            )
            
            self._loaded = True
            logger.info(f"Loaded ticker mapping from SEC ({len(self._ticker_to_cik)} entries)")
            return True
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch ticker mapping: {e}")
            return False
        except Exception as e:
            logger.error(f"Error processing ticker mapping: {e}")
            return False
    
    def _normalize_name(self, name: str) -> str:
        """Normalize company name for matching.
        
        - Convert to lowercase
        - Remove common suffixes (Inc, Corp, LLC, etc.)
        - Remove punctuation and extra whitespace
        
        Args:
            name: Raw company name.
            
        Returns:
            Normalized name string.
        """
        if not name:
            return ""
        
        # Lowercase
        normalized = name.lower()
        
        # Remove common suffixes
        suffixes = [
            r'\s+inc\.?$',
            r'\s+incorporated\.?$',
            r'\s+corp\.?$',
            r'\s+corporation\.?$',
            r'\s+llc\.?$',
            r'\s+ltd\.?$',
            r'\s+limited\.?$',
            r'\s+plc\.?$',
            r'\s+co\.?$',
            r'\s+company\.?$',
            r'\s+holdings\.?$',
            r'\s+group\.?$',
            r'\s+partnership\.?$',
            r'\s+lp\.?$',
            r'\s+llp\.?$',
        ]
        
        for suffix in suffixes:
            normalized = re.sub(suffix, '', normalized, flags=re.IGNORECASE)
        
        # Remove punctuation
        normalized = re.sub(r'[^\w\s]', ' ', normalized)
        
        # Normalize whitespace
        normalized = ' '.join(normalized.split())
        
        return normalized.strip()
    
    def by_ticker(self, ticker: str, allow_delisted: bool = False) -> str:
        """Lookup CIK by ticker symbol.
        
        Args:
            ticker: Stock ticker symbol (e.g., "AAPL").
            allow_delisted: If True, also check cache for delisted companies.
            
        Returns:
            Zero-padded 10-digit CIK string.
            
        Raises:
            TickerNotFoundError: If ticker cannot be resolved.
        """
        ticker = ticker.upper().strip()
        
        if not ticker:
            raise TickerNotFoundError("Empty ticker symbol")
        
        # Ensure mapping is loaded
        if not self._load_mapping():
            raise CIKLookupError("Failed to load ticker mapping")
        
        # Direct lookup
        if ticker in self._ticker_to_cik:
            cik = self._ticker_to_cik[ticker]
            logger.debug(f"Resolved {ticker} -> CIK {cik}")
            return cik
        
        # Check cache for delisted company (if allowed)
        if allow_delisted:
            cached = self.cache.get_by_ticker(ticker)
            if cached and cached.get('cik'):
                logger.debug(f"Found delisted ticker {ticker} in cache")
                return cached['cik']
        
        raise TickerNotFoundError(f"Ticker not found: {ticker}")
    
    def by_name(
        self,
        name: str,
        limit: int = 5,
        min_score: Optional[float] = None
    ) -> List[CompanyMatch]:
        """Lookup companies by name with fuzzy matching.
        
        Args:
            name: Company name to search for.
            limit: Maximum number of matches to return.
            min_score: Minimum match score (0.0-1.0). Uses class default if None.
            
        Returns:
            List of CompanyMatch objects sorted by match score (best first).
            
        Raises:
            CompanyNotFoundError: If no matches found above threshold.
        """
        min_score = min_score or self.MIN_MATCH_SCORE
        
        if not name or not name.strip():
            raise CompanyNotFoundError("Empty company name")
        
        # Ensure mapping is loaded
        if not self._load_mapping():
            raise CIKLookupError("Failed to load ticker mapping")
        
        search_name = name.strip()
        normalized_search = self._normalize_name(search_name)
        
        matches = []
        
        # Try exact match first (case insensitive)
        for cik, company_name in self._company_names.items():
            if company_name.lower() == search_name.lower():
                matches.append(CompanyMatch(
                    cik=cik,
                    ticker=self._cik_to_ticker.get(cik, ''),
                    company_name=company_name,
                    match_score=1.0,
                    match_type='exact'
                ))
                break
        
        # Try normalized exact match
        if not matches and normalized_search in self._name_to_cik:
            cik = self._name_to_cik[normalized_search]
            matches.append(CompanyMatch(
                cik=cik,
                ticker=self._cik_to_ticker.get(cik, ''),
                company_name=self._company_names.get(cik, ''),
                match_score=0.95,
                match_type='normalized'
            ))
        
        # Fuzzy match against all company names
        if len(matches) < limit:
            name_list = list(self._company_names.values())
            close_matches = get_close_matches(
                search_name,
                name_list,
                n=limit * 2,  # Get extra for filtering
                cutoff=min_score * 0.8  # Slightly lower for get_close_matches
            )
            
            for match_name in close_matches:
                # Find CIK for this name
                cik = None
                for c, n in self._company_names.items():
                    if n == match_name:
                        cik = c
                        break
                
                if not cik:
                    continue
                
                # Calculate detailed score
                score = SequenceMatcher(None, search_name.lower(), match_name.lower()).ratio()
                
                # Skip if already added as exact match
                if any(m.cik == cik for m in matches):
                    continue
                
                if score >= min_score:
                    matches.append(CompanyMatch(
                        cik=cik,
                        ticker=self._cik_to_ticker.get(cik, ''),
                        company_name=match_name,
                        match_score=round(score, 3),
                        match_type='fuzzy'
                    ))
        
        # Also try fuzzy matching normalized names
        if len(matches) < limit:
            normalized_names = list(self._name_to_cik.keys())
            close_normalized = get_close_matches(
                normalized_search,
                normalized_names,
                n=limit,
                cutoff=min_score
            )
            
            for norm_name in close_normalized:
                cik = self._name_to_cik[norm_name]
                
                # Skip if already added
                if any(m.cik == cik for m in matches):
                    continue
                
                score = SequenceMatcher(None, normalized_search, norm_name).ratio()
                
                if score >= min_score:
                    matches.append(CompanyMatch(
                        cik=cik,
                        ticker=self._cik_to_ticker.get(cik, ''),
                        company_name=self._company_names.get(cik, ''),
                        match_score=round(score, 3),
                        match_type='fuzzy_normalized'
                    ))
        
        # Sort by score and limit
        matches.sort(key=lambda x: x.match_score, reverse=True)
        matches = matches[:limit]
        
        if not matches:
            raise CompanyNotFoundError(
                f"No companies found matching '{name}' (min score: {min_score})"
            )
        
        logger.debug(f"Name search '{name}' found {len(matches)} matches")
        return matches
    
    def get_company_name(self, cik: str) -> Optional[str]:
        """Get company name by CIK.
        
        Args:
            cik: CIK number (will be zero-padded).
            
        Returns:
            Company name if found, None otherwise.
        """
        cik = cik.zfill(10)
        
        if not self._load_mapping():
            return None
        
        return self._company_names.get(cik)
    
    def get_ticker(self, cik: str) -> Optional[str]:
        """Get ticker symbol by CIK.
        
        Args:
            cik: CIK number (will be zero-padded).
            
        Returns:
            Ticker symbol if found, None otherwise.
        """
        cik = cik.zfill(10)
        
        if not self._load_mapping():
            return None
        
        return self._cik_to_ticker.get(cik)
    
    def resolve(
        self,
        identifier: str,
        prefer_ticker: bool = True
    ) -> CompanyMatch:
        """Resolve an identifier (ticker or name) to a CIK.
        
        Attempts to intelligently determine if the identifier is a ticker
        symbol or company name and resolve accordingly.
        
        Args:
            identifier: Ticker symbol or company name.
            prefer_ticker: If True, try ticker lookup first for short identifiers.
            
        Returns:
            CompanyMatch with the best resolution.
            
        Raises:
            CIKLookupError: If resolution fails.
        """
        identifier = identifier.strip()
        
        if not identifier:
            raise CIKLookupError("Empty identifier")
        
        # Heuristic: short alphanumeric strings are likely tickers
        is_likely_ticker = (
            len(identifier) <= 5 and
            identifier.isalnum() and
            identifier.isupper()
        )
        
        if is_likely_ticker and prefer_ticker:
            # Try ticker first
            try:
                cik = self.by_ticker(identifier)
                return CompanyMatch(
                    cik=cik,
                    ticker=identifier.upper(),
                    company_name=self.get_company_name(cik) or '',
                    match_score=1.0,
                    match_type='ticker'
                )
            except TickerNotFoundError:
                pass
            
            # Fall back to name search
            matches = self.by_name(identifier, limit=1)
            if matches:
                return matches[0]
        else:
            # Try name first
            try:
                matches = self.by_name(identifier, limit=1)
                if matches:
                    return matches[0]
            except CompanyNotFoundError:
                pass
            
            # Fall back to ticker
            try:
                cik = self.by_ticker(identifier)
                return CompanyMatch(
                    cik=cik,
                    ticker=identifier.upper(),
                    company_name=self.get_company_name(cik) or '',
                    match_score=1.0,
                    match_type='ticker'
                )
            except TickerNotFoundError:
                pass
        
        raise CIKLookupError(f"Could not resolve identifier: {identifier}")
    
    def list_all_tickers(self) -> List[str]:
        """Get list of all known ticker symbols.
        
        Returns:
            List of ticker symbols.
        """
        if not self._load_mapping():
            return []
        
        return list(self._ticker_to_cik.keys())
    
    def search_by_prefix(self, prefix: str, limit: int = 10) -> List[CompanyMatch]:
        """Search for companies by ticker or name prefix.
        
        Useful for autocomplete functionality.
        
        Args:
            prefix: Prefix to search for.
            limit: Maximum results to return.
            
        Returns:
            List of matching companies.
        """
        if not self._load_mapping():
            return []
        
        prefix = prefix.upper()
        matches = []
        
        # Search tickers
        for ticker, cik in self._ticker_to_cik.items():
            if ticker.startswith(prefix):
                matches.append(CompanyMatch(
                    cik=cik,
                    ticker=ticker,
                    company_name=self._company_names.get(cik, ''),
                    match_score=1.0,
                    match_type='ticker_prefix'
                ))
                if len(matches) >= limit:
                    break
        
        # Search names if room
        if len(matches) < limit:
            search_limit = limit - len(matches)
            for cik, name in self._company_names.items():
                if name.upper().startswith(prefix):
                    # Skip if already found by ticker
                    if any(m.cik == cik for m in matches):
                        continue
                    matches.append(CompanyMatch(
                        cik=cik,
                        ticker=self._cik_to_ticker.get(cik, ''),
                        company_name=name,
                        match_score=0.9,
                        match_type='name_prefix'
                    ))
                    if len(matches) >= limit:
                        break
        
        return matches
    
    def refresh_mapping(self) -> bool:
        """Force refresh of ticker mapping from SEC.
        
        Returns:
            True if refresh successful, False otherwise.
        """
        self._loaded = False
        return self._load_mapping(force_refresh=True)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get lookup service statistics.
        
        Returns:
            Dict with mapping statistics.
        """
        return {
            'loaded': self._loaded,
            'total_tickers': len(self._ticker_to_cik),
            'total_companies': len(self._company_names),
        }
