"""Fingerprint database management and vendor matching."""

import json
import re
from importlib import resources
from pathlib import Path
from urllib.parse import urlparse, parse_qs


def load_vendors(vendors_file: str = None) -> list[dict]:
    """Load vendor fingerprints from JSON file."""
    if vendors_file is None:
        # Use importlib.resources to find the bundled vendors.json
        try:
            with resources.files('mscan.data').joinpath('vendors.json').open('r') as f:
                data = json.load(f)
        except (TypeError, FileNotFoundError):
            # Fallback for development mode
            vendors_file = Path(__file__).parent / 'data' / 'vendors.json'
            with open(vendors_file, 'r') as f:
                data = json.load(f)
    else:
        with open(vendors_file, 'r') as f:
            data = json.load(f)

    return data.get('vendors', [])


def get_vendors_path() -> Path:
    """Get the path to the vendors.json file for writing."""
    return Path(__file__).parent / 'data' / 'vendors.json'


def match_vendors(requests: list[str], vendors: list[dict] = None) -> list[dict]:
    """
    Match captured requests against vendor fingerprints.

    Args:
        requests: List of captured request URLs
        vendors: List of vendor fingerprints (loads from file if not provided)

    Returns:
        List of detected vendors with details
    """
    if vendors is None:
        vendors = load_vendors()

    detected = []

    for vendor in vendors:
        match_result = _check_vendor_match(requests, vendor)
        if match_result['detected']:
            detected.append({
                'vendor_name': vendor['vendor_name'],
                'category': vendor['category'],
                'detected': True,
                'matching_domains': match_result['matching_domains'],
                'details': match_result['details']
            })

    return detected


def _check_vendor_match(requests: list[str], vendor: dict) -> dict:
    """Check if a vendor's fingerprint matches any of the captured requests."""
    rules = vendor.get('detection_rules', {})
    domains = rules.get('domains', [])
    url_patterns = rules.get('url_patterns', [])

    matching_domains = []
    details = []

    for request_url in requests:
        parsed = urlparse(request_url)
        request_domain = parsed.netloc.lower()
        full_url = request_url.lower()

        # Check domain matches
        for domain in domains:
            if domain.lower() in request_domain or domain.lower() in full_url:
                if domain not in matching_domains:
                    matching_domains.append(domain)

                # Try to extract client IDs from URL patterns
                for pattern in url_patterns:
                    extracted = _extract_id_from_url(request_url, pattern)
                    if extracted and extracted not in details:
                        details.append(extracted)

    return {
        'detected': len(matching_domains) > 0,
        'matching_domains': matching_domains,
        'details': ', '.join(details) if details else ''
    }


def _extract_id_from_url(url: str, pattern: str) -> str | None:
    """Try to extract a client ID or identifier from a URL based on a pattern."""
    # Handle query parameter patterns (e.g., "lcid=", "id=")
    if '=' in pattern:
        param_name = pattern.rstrip('=')
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        if param_name in params:
            return f"{param_name}={params[param_name][0]}"

    # Handle patterns like "UA-", "G-", "AW-" (Google IDs)
    if pattern.endswith('-'):
        match = re.search(rf'({re.escape(pattern)}[\w-]+)', url)
        if match:
            return match.group(1)

    # Handle path patterns like "gtag/js"
    if pattern in url:
        # Try to extract associated ID
        match = re.search(rf'{re.escape(pattern)}[?&]id=([^&]+)', url)
        if match:
            return match.group(1)

    return None


def get_all_categories(vendors: list[dict] = None) -> list[str]:
    """Get all unique categories from vendor list."""
    if vendors is None:
        vendors = load_vendors()

    categories = set()
    for vendor in vendors:
        categories.add(vendor.get('category', 'Other/Uncategorized'))

    # Return in preferred order
    preferred_order = [
        'Direct Mail and Offline Attribution',
        'Social Media Advertising',
        'Search and Display Advertising',
        'Affiliate and Performance Marketing',
        'CTV and Streaming Attribution',
        'Analytics and Experimentation',
        'Identity and Data Infrastructure',
        'Consent Management',
        'Other/Uncategorized'
    ]

    ordered = [c for c in preferred_order if c in categories]
    remaining = [c for c in categories if c not in preferred_order]

    return ordered + sorted(remaining)
