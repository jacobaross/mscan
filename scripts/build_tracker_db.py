#!/usr/bin/env python3
"""
Build mscan tracker database from whotracks.me data.

Reads whotracksme_raw.json, applies category mapping, and outputs tracker_db.json.
Existing vendors.json entries take priority (they are not overwritten).
"""

import json
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent / "data"
SRC_DATA_DIR = Path(__file__).parent.parent / "src" / "mscan" / "data"


# Map whotracks.me categories to mscan categories
# None = skip this category (not martech relevant)
CATEGORY_MAP = {
    "advertising": "Performance",
    "site_analytics": "Analytics",
    "social_media": "Social Media",
    "consent": "Consent Mgmt",
    "audio_video_player": "CTV",
    "customer_interaction": "Other",  # Chat widgets, etc.
    "marketing": "Performance",
    "hosting": None,  # Skip - infrastructure
    "utilities": None,  # Skip - tag managers already covered
    "extensions": None,  # Skip - browser extensions
    "misc": None,  # Skip - too generic
    "pornvertising": None,  # Skip - adult content
}

# Vendor-specific overrides for major DSPs/SSPs/platforms
# Key should match pattern name (lowercase) from whotracks.me
VENDOR_OVERRIDES = {
    # DSPs
    "appnexus": "DSP",
    "xandr": "DSP",
    "the_trade_desk": "DSP",
    "thetradedesk": "DSP",
    "trade_desk": "DSP",
    "mediamath": "DSP",
    "amobee": "DSP",
    "amazon_advertising": "DSP",
    "dv360": "DSP",
    "display_video_360": "DSP",
    "adelphic": "DSP",
    "centro": "DSP",
    "simpli.fi": "DSP",
    "stackadapt": "DSP",
    "beeswax": "DSP",
    "basis_technologies": "DSP",
    
    # SSPs
    "index_exchange": "SSP",
    "pubmatic": "SSP",
    "casalemedia": "SSP",
    "rubicon": "SSP",
    "rubiconproject": "SSP",
    "openx": "SSP",
    "sovrn": "SSP",
    "triplelift": "SSP",
    "magnite": "SSP",
    "sharethrough": "SSP",
    "gumgum": "SSP",
    "33across": "SSP",
    "teads": "SSP",
    "smart_adserver": "SSP",
    "smartadserver": "SSP",
    "freewheel": "SSP",
    "spotx": "SSP",
    "yieldmo": "SSP",
    "kargo": "SSP",
    "unruly": "SSP",
    "outbrain": "SSP",
    "taboola": "SSP",
    
    # CDPs
    "segment": "CDP",
    "tealium": "CDP",
    "mparticle": "CDP",
    "lytics": "CDP",
    "treasure_data": "CDP",
    "blueconic": "CDP",
    "salesforce_cdp": "CDP",
    "adobe_experience_platform": "CDP",
    
    # Email
    "klaviyo": "Email",
    "mailchimp": "Email",
    "sendgrid": "Email",
    "braze": "Email",
    "iterable": "Email",
    "attentive": "Email",
    "sailthru": "Email",
    "emarsys": "Email",
    "dotdigital": "Email",
    "listrak": "Email",
    "omnisend": "Email",
    "customer.io": "Email",
    
    # ID & Data Infrastructure
    "liveramp": "ID & Data Infra",
    "id5": "ID & Data Infra",
    "lotame": "ID & Data Infra",
    "oracle_bluekai": "ID & Data Infra",
    "bluekai": "ID & Data Infra",
    "neustar": "ID & Data Infra",
    "experian": "ID & Data Infra",
    "zeotap": "ID & Data Infra",
    "unified_id": "ID & Data Infra",
    "uid2": "ID & Data Infra",
    
    # Direct Mail (rare in whotracks.me but check)
    "pebblepost": "Direct Mail",
    "lob": "Direct Mail",
    
    # Affiliate
    "cj_affiliate": "Affiliate",
    "commission_junction": "Affiliate",
    "impact": "Affiliate",
    "rakuten": "Affiliate",
    "awin": "Affiliate",
    "partnerize": "Affiliate",
    "shareasale": "Affiliate",
    "refersion": "Affiliate",
    
    # Analytics (specific overrides)
    "google_analytics": "Analytics",
    "adobe_analytics": "Analytics",
    "mixpanel": "Analytics",
    "amplitude": "Analytics",
    "heap": "Analytics",
    "fullstory": "Analytics",
    "hotjar": "Analytics",
    "mouseflow": "Analytics",
    
    # Social Media
    "facebook": "Social Media",
    "meta_pixel": "Social Media",
    "facebook_pixel": "Social Media",
    "twitter": "Social Media",
    "x_pixel": "Social Media",
    "pinterest": "Social Media",
    "tiktok": "Social Media",
    "linkedin": "Social Media",
    "snapchat": "Social Media",
    "reddit": "Social Media",
}


def load_raw_data() -> dict:
    """Load the raw whotracks.me data."""
    path = DATA_DIR / "whotracksme_raw.json"
    if not path.exists():
        raise FileNotFoundError(f"Run fetch_whotracksme.py first: {path}")
    
    with open(path) as f:
        return json.load(f)


def load_existing_vendors() -> set[str]:
    """Load existing vendor domains to avoid duplicates."""
    path = SRC_DATA_DIR / "vendors.json"
    if not path.exists():
        return set()
    
    with open(path) as f:
        data = json.load(f)
    
    existing = set()
    for vendor in data.get("vendors", []):
        rules = vendor.get("detection_rules", {})
        for domain in rules.get("domains", []):
            # Normalize domain
            existing.add(domain.lower().replace("www.", ""))
    
    return existing


def get_category(pattern_key: str, wt_category: str) -> str | None:
    """
    Determine mscan category for a tracker.
    Returns None if should be skipped.
    """
    # Check vendor-specific overrides first
    key_lower = pattern_key.lower().replace("-", "_").replace(" ", "_")
    if key_lower in VENDOR_OVERRIDES:
        return VENDOR_OVERRIDES[key_lower]
    
    # Fall back to category mapping
    return CATEGORY_MAP.get(wt_category)


def build_tracker_db(raw_data: dict, existing_domains: set[str]) -> dict:
    """Build the tracker database from raw whotracks.me data."""
    patterns = raw_data.get("patterns", {})
    organizations = raw_data.get("organizations", {})
    
    # Build domain -> tracker info mapping
    tracker_db = {
        "source": "ghostery/trackerdb",
        "domains": {}
    }
    
    stats = {
        "total_patterns": len(patterns),
        "included": 0,
        "skipped_category": 0,
        "skipped_existing": 0,
        "skipped_no_domains": 0,
    }
    
    for pattern_key, pattern in patterns.items():
        wt_category = pattern.get("category", "misc")
        domains = pattern.get("domains", [])
        
        # Skip if no domains
        if not domains:
            stats["skipped_no_domains"] += 1
            continue
        
        # Determine category
        mscan_category = get_category(pattern_key, wt_category)
        if mscan_category is None:
            stats["skipped_category"] += 1
            continue
        
        # Get organization info if available
        org_key = pattern.get("organization")
        org_name = None
        if org_key and org_key in organizations:
            org_name = organizations[org_key].get("name")
        
        # Use pattern name or org name
        vendor_name = pattern.get("name") or org_name or pattern_key.replace("_", " ").title()
        
        # Add each domain
        for domain in domains:
            domain_clean = domain.lower().replace("www.", "")
            
            # Skip if already in vendors.json
            if domain_clean in existing_domains:
                stats["skipped_existing"] += 1
                continue
            
            tracker_db["domains"][domain_clean] = {
                "vendor": vendor_name,
                "category": mscan_category,
                "source": "whotracksme",
            }
            stats["included"] += 1
    
    tracker_db["stats"] = stats
    return tracker_db


def main():
    print("Loading raw whotracks.me data...")
    raw_data = load_raw_data()
    
    print("Loading existing vendors.json domains...")
    existing_domains = load_existing_vendors()
    print(f"  Found {len(existing_domains)} existing domains to skip")
    
    print("Building tracker database...")
    tracker_db = build_tracker_db(raw_data, existing_domains)
    
    # Save to data directory
    output_path = DATA_DIR / "tracker_db.json"
    with open(output_path, "w") as f:
        json.dump(tracker_db, f, indent=2)
    
    # Also copy to src/mscan/data for bundling
    src_output = SRC_DATA_DIR / "tracker_db.json"
    with open(src_output, "w") as f:
        json.dump(tracker_db, f, indent=2)
    
    # Print stats
    stats = tracker_db.get("stats", {})
    print(f"\nSaved to: {output_path}")
    print(f"  Also: {src_output}")
    print(f"\nStats:")
    print(f"  Total patterns: {stats.get('total_patterns', 0)}")
    print(f"  Domains included: {stats.get('included', 0)}")
    print(f"  Skipped (wrong category): {stats.get('skipped_category', 0)}")
    print(f"  Skipped (in vendors.json): {stats.get('skipped_existing', 0)}")
    print(f"  Skipped (no domains): {stats.get('skipped_no_domains', 0)}")
    
    # Show category breakdown
    categories = {}
    for domain_info in tracker_db.get("domains", {}).values():
        cat = domain_info.get("category", "Other")
        categories[cat] = categories.get(cat, 0) + 1
    
    print(f"\nBy category:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    main()
