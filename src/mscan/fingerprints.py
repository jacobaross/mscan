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


def find_unknown_domains(requests: list[str], base_domain: str, vendors: list[dict] = None) -> list[dict]:
    """
    Find third-party domains in requests that aren't in the vendor database.

    Args:
        requests: List of captured request URLs
        base_domain: The domain being scanned (to exclude first-party requests)
        vendors: List of vendor fingerprints (loads from file if not provided)

    Returns:
        List of unknown domain dicts with domain, count, and sample URLs
    """
    if vendors is None:
        vendors = load_vendors()

    # Build set of all known vendor domains
    known_domains = set()
    for vendor in vendors:
        rules = vendor.get('detection_rules', {})
        for domain in rules.get('domains', []):
            known_domains.add(domain.lower())

    # Common infrastructure domains to skip
    skip_domains = [
        'google', 'googleapis', 'gstatic', 'googlesyndication', 'googletagmanager',
        'facebook', 'fbcdn', 'doubleclick',
        'cloudflare', 'cloudfront', 'akamai', 'fastly', 'cdn',
        'jquery', 'bootstrap', 'unpkg', 'jsdelivr', 'cdnjs',
        'fonts.', 'static.', 'assets.', 'images.', 'img.',
        'amazonaws', 'azure', 'blob.core',
    ]

    # Extract and count unique domains
    domain_info = {}
    base_clean = base_domain.lower().replace('www.', '')

    for req in requests:
        parsed = urlparse(req)
        domain = parsed.netloc.lower()

        if not domain:
            continue

        # Skip first-party
        if base_clean in domain:
            continue

        # Skip common infrastructure
        if any(skip in domain for skip in skip_domains):
            continue

        # Check if matches any known vendor domain
        is_known = False
        for known in known_domains:
            if known in domain or domain in known:
                is_known = True
                break

        if is_known:
            continue

        # Extract base domain for grouping
        parts = domain.split('.')
        if len(parts) >= 2:
            base = '.'.join(parts[-2:])
        else:
            base = domain

        if base not in domain_info:
            domain_info[base] = {'domain': base, 'count': 0, 'full_domains': set(), 'sample_urls': []}

        domain_info[base]['count'] += 1
        domain_info[base]['full_domains'].add(domain)
        if len(domain_info[base]['sample_urls']) < 3:
            domain_info[base]['sample_urls'].append(req)

    # Convert to list and sort by count
    result = []
    for base, info in domain_info.items():
        result.append({
            'domain': base,
            'count': info['count'],
            'full_domains': list(info['full_domains']),
            'sample_urls': info['sample_urls']
        })

    result.sort(key=lambda x: x['count'], reverse=True)
    return result


def get_all_categories(vendors: list[dict] = None) -> list[str]:
    """Get all unique categories from vendor list."""
    if vendors is None:
        vendors = load_vendors()

    categories = set()
    for vendor in vendors:
        categories.add(vendor.get('category', 'Other/Uncategorized'))

    # Return in preferred order
    preferred_order = [
        'Direct Mail',
        'CTV',
        'Social Media',
        'Search',
        'Affiliate',
        'Performance',
        'Analytics',
        'ID & Data Infra',
        'Consent Mgmt',
        'CDP',
        'DSP',
        'Email',
        'Other',
    ]

    ordered = [c for c in preferred_order if c in categories]
    remaining = [c for c in categories if c not in preferred_order]

    return ordered + sorted(remaining)
