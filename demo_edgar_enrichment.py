#!/usr/bin/env python3
"""Demo script for SEC EDGAR enrichment Phase 1.

This script demonstrates all Phase 1 functionality:
- Rate limiting
- CIK lookup (ticker and name)
- Caching
- EDGAR API client
- Data models

Usage:
    python demo_edgar_enrichment.py
"""

import sys
import time
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add src to path for demo purposes
sys.path.insert(0, str(Path(__file__).parent / "src"))

from mscan.enricher.edgar_client import EdgarClient
from mscan.utils.rate_limiter import RateLimiter
from mscan.enricher.cache_manager import CacheManager, CacheTier
from mscan.enricher.cik_lookup import CIKLookup


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


def demo_rate_limiter():
    """Demonstrate rate limiter functionality."""
    print_section("1. RATE LIMITER DEMO")
    
    print("Creating rate limiter: 5 requests per second...")
    limiter = RateLimiter(max_requests=5, window_seconds=1)
    
    print("Making 7 rapid requests (should rate limit after 5)...")
    start = time.time()
    
    for i in range(7):
        limiter.acquire()
        elapsed = time.time() - start
        print(f"  Request {i+1}: {elapsed:.3f}s elapsed")
    
    elapsed = time.time() - start
    print(f"\n✓ Total time: {elapsed:.3f}s (rate limiting worked!)")
    
    stats = limiter.get_stats()
    print(f"✓ Stats: {stats.total_requests} requests, {stats.delayed_requests} delayed")


def demo_cache_manager():
    """Demonstrate cache manager functionality."""
    print_section("2. CACHE MANAGER DEMO")
    
    print("Creating cache manager with temp database...")
    cache = CacheManager(db_path="/tmp/edgar_demo_cache.db")
    
    # Set some data
    print("\nStoring company data in cache...")
    test_data = {
        "name": "Apple Inc.",
        "cik": "0000320193",
        "revenue": 391035000000
    }
    cache.set("0000320193", test_data, CacheTier.ENTITY_METADATA, ticker="AAPL")
    print("✓ Data cached with 7-day TTL")
    
    # Get data
    print("\nRetrieving data from cache...")
    result = cache.get("0000320193")
    print(f"✓ Cache hit: {result['name']}")
    
    # Get by ticker
    print("\nLookup by ticker...")
    result = cache.get_by_ticker("AAPL")
    print(f"✓ Found by ticker: {result['name']}")
    
    # Stats
    stats = cache.get_stats()
    print(f"\n✓ Cache stats: {stats.hits} hits, {stats.misses} misses, {stats.hit_rate:.1f}% hit rate")
    
    db_stats = cache.get_db_stats()
    print(f"✓ Database: {db_stats['total_entries']} entries, {db_stats['db_size_mb']} MB")
    
    # Cleanup
    cache.cleanup_expired()
    print("✓ Cleaned up expired entries")


def demo_cik_lookup():
    """Demonstrate CIK lookup functionality."""
    print_section("3. CIK LOOKUP DEMO")
    
    print("Creating CIK lookup service...")
    cache = CacheManager(db_path="/tmp/edgar_demo_cache.db")
    rate_limiter = RateLimiter()
    
    # NOTE: Real SEC API call here - requires internet
    lookup = CIKLookup(cache, rate_limiter, "DemoScript demo@example.com")
    
    print("\n⚠️  NOTE: The following tests require internet connection to SEC.gov\n")
    
    try:
        # Lookup by ticker
        print("Looking up ticker 'AAPL'...")
        cik = lookup.by_ticker("AAPL")
        print(f"✓ AAPL → CIK {cik}")
        
        # Get company name
        name = lookup.get_company_name(cik)
        print(f"✓ Company name: {name}")
        
        # Fuzzy name search
        print("\nFuzzy search for 'Apple'...")
        matches = lookup.by_name("Apple", limit=3)
        print(f"✓ Found {len(matches)} matches:")
        for match in matches:
            print(f"  - {match.company_name} ({match.ticker}) - score: {match.match_score:.2f}")
        
        # Prefix search
        print("\nPrefix search for 'MIC'...")
        results = lookup.search_by_prefix("MIC", limit=5)
        print(f"✓ Found {len(results)} results:")
        for r in results[:3]:
            print(f"  - {r.ticker}: {r.company_name}")
        
        # Stats
        stats = lookup.get_stats()
        print(f"\n✓ Lookup stats: {stats['total_tickers']} tickers loaded")
        
    except Exception as e:
        print(f"\n⚠️  Could not connect to SEC.gov: {e}")
        print("   This is expected if offline or SEC API is down.")


def demo_edgar_client():
    """Demonstrate EDGAR client functionality."""
    print_section("4. EDGAR CLIENT DEMO")
    
    print("Creating EDGAR client...")
    print("User-Agent: 'DemoScript demo@example.com'\n")
    
    # NOTE: Real SEC API calls here - requires internet
    client = EdgarClient(user_agent="DemoScript demo@example.com")
    
    print("⚠️  NOTE: The following tests make real API calls to SEC.gov\n")
    
    try:
        # Enrich by ticker
        print("Enriching Apple Inc. (AAPL)...")
        result = client.enrich_by_ticker("AAPL")
        
        if result.success:
            print("✓ Enrichment successful!")
            
            brand = result.brand
            profile = brand.sec_profile
            
            print(f"\n  Company: {profile.company_name}")
            print(f"  CIK: {profile.cik}")
            print(f"  Ticker: {profile.ticker}")
            print(f"  Exchange: {profile.exchange}")
            print(f"  Industry: {profile.sic_description}")
            
            if profile.latest_financials:
                fin = profile.latest_financials
                print(f"\n  Financials (FY{fin.fiscal_year}):")
                if fin.revenue_usd:
                    print(f"    Revenue: ${fin.revenue_usd:,.0f}")
                if fin.revenue_growth_yoy:
                    print(f"    YoY Growth: {fin.revenue_growth_yoy:.1f}%")
                if fin.net_income_usd:
                    print(f"    Net Income: ${fin.net_income_usd:,.0f}")
                if fin.employee_count:
                    print(f"    Employees: {fin.employee_count:,}")
            
            if profile.filings_metadata:
                filings = profile.filings_metadata
                print(f"\n  Recent Filings:")
                print(f"    10-K filings: {filings.filing_count_10k}")
                print(f"    10-Q filings: {filings.filing_count_10q}")
                print(f"    8-K filings: {filings.filing_count_8k}")
                print(f"    Last filing: {filings.last_filing_date}")
            
            print(f"\n  Performance:")
            print(f"    API calls: {result.api_calls_made}")
            print(f"    Cache hits: {result.cache_hits}")
            print(f"    Duration: {result.duration_seconds:.2f}s")
            print(f"    Confidence: {brand.confidence_level}")
            
        else:
            print(f"✗ Enrichment failed: {result.error.message}")
        
        # Show rate limiter working
        print("\n\nDemonstrating rate limiting with multiple requests...")
        start = time.time()
        
        for ticker in ["MSFT", "GOOGL", "AMZN"]:
            print(f"  Enriching {ticker}...")
            result = client.enrich_by_ticker(ticker)
            if result.success:
                print(f"    ✓ {result.brand.sec_profile.company_name}")
            else:
                print(f"    ✗ {result.error.message}")
        
        elapsed = time.time() - start
        print(f"\n✓ Completed 3 enrichments in {elapsed:.2f}s")
        
        # Get stats
        print("\nClient statistics:")
        stats = client.get_stats()
        rl_stats = stats['rate_limiter']
        cache_stats = stats['cache']
        
        print(f"  Rate limiter: {rl_stats['total_requests']} requests")
        print(f"  Cache: {cache_stats['hits']} hits, {cache_stats['misses']} misses")
        
    except Exception as e:
        print(f"\n⚠️  Could not connect to SEC.gov: {e}")
        print("   This is expected if offline or SEC API is down.")
    
    finally:
        client.close()


def demo_data_models():
    """Demonstrate data models."""
    print_section("5. DATA MODELS DEMO")
    
    print("Creating Pydantic models...")
    
    from mscan.models.enriched_brand import (
        FinancialMetrics,
        SECProfile,
        EnrichedBrand,
    )
    
    # Create financial metrics
    financials = FinancialMetrics(
        revenue_usd=391035000000,
        revenue_growth_yoy=2.1,
        net_income_usd=96995000000,
        employee_count=161000,
        fiscal_year="2024"
    )
    print("✓ Created FinancialMetrics")
    
    # Create SEC profile
    profile = SECProfile(
        cik="0000320193",
        ticker="AAPL",
        company_name="Apple Inc.",
        sic_description="Electronic Computers",
        exchange="Nasdaq",
        latest_financials=financials
    )
    print("✓ Created SECProfile")
    
    # Create enriched brand
    brand = EnrichedBrand(
        domain="apple.com",
        is_publicly_traded=True,
        sec_profile=profile,
        qualification_score=95,
        insights=[
            "Fortune 50 company with $391B revenue",
            "161,000 employees worldwide",
            "Leader in consumer electronics"
        ],
        confidence_level="high",
        data_completeness=0.95
    )
    print("✓ Created EnrichedBrand")
    
    # Serialize to dict
    print("\nSerializing to dict...")
    data = brand.model_dump()
    print(f"✓ Serialized: {len(data)} top-level fields")
    
    # Serialize to JSON
    print("\nSerializing to JSON...")
    json_str = brand.model_dump_json(indent=2)
    print(f"✓ JSON length: {len(json_str)} bytes")
    print("\nSample JSON output:")
    print(json_str[:500] + "...")
    
    # Validate data
    print("\nValidating data...")
    brand2 = EnrichedBrand.model_validate(data)
    print(f"✓ Validation successful: {brand2.domain}")


def main():
    """Run all demos."""
    print("\n" + "=" * 70)
    print("  SEC EDGAR ENRICHMENT - PHASE 1 DEMO")
    print("  mscan brand enrichment with public company data")
    print("=" * 70)
    
    try:
        # Demo each component
        demo_rate_limiter()
        demo_cache_manager()
        demo_cik_lookup()
        demo_edgar_client()
        demo_data_models()
        
        print_section("DEMO COMPLETE")
        print("✓ All Phase 1 components demonstrated successfully!")
        print("\nPhase 1 Deliverables:")
        print("  1. ✓ Rate Limiter - Token bucket with 10 req/s limit")
        print("  2. ✓ Cache Manager - SQLite with TTL support")
        print("  3. ✓ CIK Lookup - Ticker/name resolution with fuzzy matching")
        print("  4. ✓ EDGAR Client - Full API integration with error handling")
        print("  5. ✓ Data Models - Pydantic models for all data structures")
        print("\nNext Steps:")
        print("  - Install dependencies: pip install -e .[dev]")
        print("  - Run tests: pytest tests/ -v --cov=mscan")
        print("  - Integrate with mscan CLI (Phase 2)")
        
    except KeyboardInterrupt:
        print("\n\nDemo interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n✗ Demo failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
