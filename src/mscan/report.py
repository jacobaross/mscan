"""Report generation for martech scan results."""

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from mscan.fingerprints import get_all_categories, load_vendors


# Category display order: direct competitors first, then others
CATEGORY_ORDER = [
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


def generate_report(
    scan_results: dict,
    detected_vendors: list[dict],
    output_dir: str = None
) -> str:
    """
    Generate a plain text report from scan results.

    Args:
        scan_results: Results from scanner containing requests and pages scanned
        detected_vendors: List of detected vendors with details
        output_dir: Directory to save report (defaults to ./reports/)

    Returns:
        Path to the generated report file
    """
    if output_dir is None:
        output_dir = Path.cwd() / 'reports'

    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)

    base_url = scan_results.get('base_url', '')
    brand_name = _extract_brand_name(base_url)
    scan_date = datetime.now().strftime('%Y-%m-%d %H:%M')
    pages_scanned = scan_results.get('pages_scanned', [])

    # Build report sections
    header = _build_header(brand_name, base_url, scan_date, len(pages_scanned))
    summary = _build_summary(detected_vendors)
    vendor_table = _build_vendor_table(detected_vendors)

    report = f"{header}\n\n{summary}\n\n{vendor_table}"

    # Save report
    safe_brand = brand_name.lower().replace(' ', '-').replace('.', '-')
    filename = f"{safe_brand}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
    report_path = output_dir / filename

    with open(report_path, 'w') as f:
        f.write(report)

    return str(report_path)


def _extract_brand_name(url: str) -> str:
    """Extract brand name from URL."""
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path
    domain = domain.replace('www.', '')

    # Get the main part of the domain
    parts = domain.split('.')
    if len(parts) >= 2:
        return parts[0].title()

    return domain.title()


def _build_header(brand_name: str, url: str, scan_date: str, pages_count: int) -> str:
    """Build the report header section."""
    width = 60
    title = f"MARTECH SCAN: {brand_name.upper()}"

    lines = [
        "=" * width,
        title.center(width),
        "=" * width,
        "",
        f"  URL:          {url}",
        f"  Scanned:      {scan_date}",
        f"  Pages:        {pages_count}",
    ]
    return '\n'.join(lines)


def _build_summary(detected_vendors: list[dict]) -> str:
    """Build the summary section based on detected vendors."""
    width = 60
    lines = [
        "",
        "-" * width,
        "SUMMARY".center(width),
        "-" * width,
    ]

    if not detected_vendors:
        lines.append("")
        lines.append("  No martech vendors detected from the fingerprint database.")
        lines.append("  Site may use unlisted vendors or block tracking scripts.")
        return '\n'.join(lines)

    # Group by category for analysis
    by_category = {}
    for vendor in detected_vendors:
        cat = vendor['category']
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(vendor)

    lines.append("")

    # Direct Mail
    if 'Direct Mail' in by_category:
        vendors = by_category['Direct Mail']
        names = [v['vendor_name'] for v in vendors]
        details = [v['details'] for v in vendors if v.get('details')]
        detail_str = f" ({details[0]})" if details else ""
        lines.append(f"  * Direct Mail: {', '.join(names)}{detail_str}")

    # CTV
    if 'CTV' in by_category:
        vendors = by_category['CTV']
        names = [v['vendor_name'] for v in vendors]
        lines.append(f"  * CTV/Streaming: {', '.join(names)}")

    # Social
    if 'Social Media' in by_category:
        vendors = by_category['Social Media']
        names = [v['vendor_name'] for v in vendors]
        if len(names) >= 3:
            lines.append(f"  * Social (heavy): {', '.join(names)}")
        else:
            lines.append(f"  * Social: {', '.join(names)}")

    # Affiliate
    if 'Affiliate' in by_category:
        vendors = by_category['Affiliate']
        names = [v['vendor_name'] for v in vendors]
        lines.append(f"  * Affiliate: {', '.join(names)}")

    # Performance
    if 'Performance' in by_category:
        vendors = by_category['Performance']
        names = [v['vendor_name'] for v in vendors]
        lines.append(f"  * Performance: {', '.join(names)}")

    # Analytics depth
    if 'Analytics' in by_category:
        vendors = by_category['Analytics']
        names = [v['vendor_name'] for v in vendors]
        lines.append(f"  * Analytics: {', '.join(names)}")

    # Identity
    if 'ID & Data Infra' in by_category:
        vendors = by_category['ID & Data Infra']
        names = [v['vendor_name'] for v in vendors]
        lines.append(f"  * Identity: {', '.join(names)}")

    # Consent
    if 'Consent Mgmt' in by_category:
        vendors = by_category['Consent Mgmt']
        names = [v['vendor_name'] for v in vendors]
        lines.append(f"  * Consent: {', '.join(names)}")

    # Summary stat
    total = len(detected_vendors)
    categories = len(by_category)
    lines.append("")
    lines.append(f"  Total: {total} vendors across {categories} categories")

    return '\n'.join(lines)


def _build_vendor_table(detected_vendors: list[dict]) -> str:
    """Build a single vendor table with category sections."""
    width = 60
    col_vendor = 24
    col_status = 10
    col_details = 22

    lines = [
        "",
        "-" * width,
        "VENDOR DETAILS".center(width),
        "-" * width,
    ]

    all_vendors = load_vendors()

    # Create lookup for detected vendors
    detected_names = {v['vendor_name'] for v in detected_vendors}
    detected_lookup = {v['vendor_name']: v for v in detected_vendors}

    # Group vendors by category
    vendors_by_cat = {}
    for vendor in all_vendors:
        cat = vendor['category']
        if cat not in vendors_by_cat:
            vendors_by_cat[cat] = []
        vendors_by_cat[cat].append(vendor)

    # Table header
    lines.append("")
    header = f"  {'Vendor':<{col_vendor}} {'Status':<{col_status}} {'Details':<{col_details}}"
    lines.append(header)
    lines.append("  " + "-" * (width - 4))

    # Process categories in defined order
    for category in CATEGORY_ORDER:
        if category not in vendors_by_cat:
            continue

        category_vendors = vendors_by_cat[category]

        # Category separator
        short_cat = _short_category_name(category)
        lines.append("")
        lines.append(f"  [{short_cat}]")

        for vendor in sorted(category_vendors, key=lambda v: v['vendor_name']):
            name = vendor['vendor_name']
            if name in detected_names:
                detected_info = detected_lookup[name]
                status = "YES"
                details = detected_info.get('details', '')
                if not details and detected_info.get('matching_domains'):
                    details = detected_info['matching_domains'][0]
                # Truncate details if too long
                if len(details) > col_details:
                    details = details[:col_details-3] + "..."
            else:
                status = "-"
                details = ""

            # Truncate vendor name if too long
            display_name = name if len(name) <= col_vendor else name[:col_vendor-3] + "..."
            lines.append(f"  {display_name:<{col_vendor}} {status:<{col_status}} {details:<{col_details}}")

    lines.append("")
    lines.append("=" * width)

    return '\n'.join(lines)


def _short_category_name(category: str) -> str:
    """Return a shortened category name for display."""
    mapping = {
        'Direct Mail': 'DIRECT MAIL',
        'CTV': 'CTV/STREAMING',
        'Social Media': 'SOCIAL',
        'Search': 'SEARCH',
        'Affiliate': 'AFFILIATE',
        'Performance': 'PERFORMANCE',
        'Analytics': 'ANALYTICS',
        'ID & Data Infra': 'IDENTITY',
        'Consent Mgmt': 'CONSENT',
        'CDP': 'CDP',
        'DSP': 'DSP',
        'Email': 'EMAIL',
        'Other': 'OTHER',
    }
    return mapping.get(category, category.upper())
