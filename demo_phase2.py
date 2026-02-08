#!/usr/bin/env python3
"""Demo script for Phase 2 SEC EDGAR CLI integration.

This demonstrates the new CLI commands:
- mscan enrich <ticker>
- mscan profile <ticker>
- Programmatic use of ProfileBuilder
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from mscan.enricher import EdgarClient, ProfileBuilder
from mscan.models.enriched_brand import FinancialMetrics, SECProfile
from datetime import datetime


def demo_enrichment():
    """Demo the enrichment workflow."""
    print("=" * 80)
    print("PHASE 2 DEMO: SEC EDGAR CLI Integration")
    print("=" * 80)
    print()
    
    # Initialize clients
    user_agent = "mscan-demo test@example.com"
    
    with EdgarClient(user_agent=user_agent) as client:
        builder = ProfileBuilder()
        
        print("1. Testing EdgarClient.enrich_by_ticker()...")
        print("-" * 80)
        
        result = client.enrich_by_ticker("AAPL")
        
        if result.success:
            print(f"✅ Successfully enriched: {result.brand.sec_profile.company_name}")
            print(f"   CIK: {result.brand.sec_profile.cik}")
            print(f"   Ticker: {result.brand.sec_profile.ticker}")
            
            if result.brand.sec_profile.latest_financials:
                fin = result.brand.sec_profile.latest_financials
                if fin.revenue_usd:
                    rev_b = fin.revenue_usd / 1_000_000_000
                    print(f"   Revenue: ${rev_b:.1f}B")
                if fin.employee_count:
                    print(f"   Employees: {fin.employee_count:,}")
            
            print(f"   API calls: {result.api_calls_made}")
            print(f"   Cache hits: {result.cache_hits}")
            print(f"   Duration: {result.duration_seconds:.2f}s")
        else:
            print(f"❌ Enrichment failed: {result.error.message if result.error else 'Unknown error'}")
        
        print()
        print("2. Testing ProfileBuilder.build_profile_from_enrichment()...")
        print("-" * 80)
        
        # Simulate scan data
        scan_data = {
            "detected_technologies": [
                {"vendor": "Google Analytics", "category": "Analytics"},
                {"vendor": "Meta Pixel", "category": "Social Media"},
                {"vendor": "The Trade Desk", "category": "DSP"}
            ],
            "scanned_at": datetime.now()
        }
        
        brand = builder.build_profile_from_enrichment(
            domain="apple.com",
            enrichment_result=result,
            scan_data=scan_data
        )
        
        print(f"✅ Profile built successfully")
        print(f"   Domain: {brand.domain}")
        print(f"   Public: {brand.is_publicly_traded}")
        print(f"   Qualification Score: {brand.qualification_score}/100")
        print(f"   Confidence: {brand.confidence_level}")
        print(f"   Data Completeness: {brand.data_completeness:.0%}")
        print()
        
        print("   Insights ({0}):".format(len(brand.insights)))
        for i, insight in enumerate(brand.insights[:3], 1):
            print(f"     {i}. {insight}")
        if len(brand.insights) > 3:
            print(f"     ... and {len(brand.insights) - 3} more")
        print()
        
        print("   Recommendations ({0}):".format(len(brand.recommendations)))
        for i, rec in enumerate(brand.recommendations[:3], 1):
            print(f"     {i}. {rec}")
        if len(brand.recommendations) > 3:
            print(f"     ... and {len(brand.recommendations) - 3} more")
        print()
        
        print("3. Testing qualification scoring...")
        print("-" * 80)
        
        # Test different company sizes
        test_companies = [
            ("Mega Corp", 500_000_000_000, 200_000),    # $500B, 200K employees
            ("Large Corp", 50_000_000_000, 50_000),     # $50B, 50K employees
            ("Mid-Market", 5_000_000_000, 10_000),      # $5B, 10K employees
            ("Growth Co", 500_000_000, 1_000),          # $500M, 1K employees
            ("Startup", 50_000_000, 200),               # $50M, 200 employees
        ]
        
        for name, revenue, employees in test_companies:
            fin = FinancialMetrics(
                revenue_usd=revenue,
                employee_count=employees,
                fiscal_year="2024"
            )
            sec_profile = SECProfile(
                cik="0000000000",
                company_name=name,
                latest_financials=fin,
                enriched_at=datetime.now()
            )
            test_brand = builder.build_profile(
                domain=f"{name.lower().replace(' ', '')}.com",
                sec_profile=sec_profile
            )
            
            rev_display = f"${revenue / 1_000_000_000:.1f}B" if revenue >= 1_000_000_000 else f"${revenue / 1_000_000:.0f}M"
            print(f"   {name:15} | Revenue: {rev_display:8} | Employees: {employees:7,} | Score: {test_brand.qualification_score:3}/100")
        
        print()
        print("4. CLI Commands Available:")
        print("-" * 80)
        print("   mscan enrich AAPL              # Enrich by ticker")
        print("   mscan enrich apple.com         # Enrich by domain")
        print("   mscan enrich 'Apple Inc'       # Enrich by company name")
        print("   mscan enrich --file list.txt   # Batch enrichment")
        print("   mscan profile AAPL             # Display full profile")
        print("   mscan scan apple.com --enrich  # Scan + enrich in one")
        print()
        
        print("=" * 80)
        print("DEMO COMPLETE ✅")
        print("=" * 80)


if __name__ == "__main__":
    demo_enrichment()
