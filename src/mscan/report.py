"""Report generation for martech scan results."""

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from mscan.fingerprints import get_all_categories, load_vendors

# Competitive categories - these get special attention in takeaways
COMPETITIVE_CATEGORIES = [
    'Direct Mail',
    'CTV',
]


def generate_report(
    scan_results: dict,
    detected_vendors: list[dict],
    unknown_domains: list[dict] = None,
    output_dir: str = None
) -> str:
    """
    Generate a plain text report from scan results.

    Args:
        scan_results: Results from scanner containing requests and pages scanned
        detected_vendors: List of detected vendors with details
        unknown_domains: List of unknown third-party domains
        output_dir: Directory to save report (defaults to ./reports/)

    Returns:
        Path to the generated report file
    """
    if output_dir is None:
        output_dir = Path.cwd() / 'reports'

    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)

    if unknown_domains is None:
        unknown_domains = []

    base_url = scan_results.get('base_url', '')
    brand_name = _extract_brand_name(base_url)
    scan_date = datetime.now().strftime('%Y-%m-%d %H:%M')
    pages_scanned = scan_results.get('pages_scanned', [])

    # Build report sections
    header = _build_header(brand_name, base_url, scan_date, len(pages_scanned))
    findings = _build_findings(detected_vendors)
    takeaways = _build_takeaways(detected_vendors)
    unknown_table = _build_unknown_domains_table(unknown_domains)

    report = f"{header}\n\n{findings}\n\n{takeaways}\n\n{unknown_table}"

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


def _build_findings(detected_vendors: list[dict]) -> str:
    """Build the FINDINGS section mirroring terminal output."""
    lines = ["FINDINGS"]

    if not detected_vendors:
        lines.append("  No martech vendors detected from the fingerprint database.")
        lines.append("  Site may use unlisted vendors or block tracking scripts.")
        return '\n'.join(lines)

    # Group by category
    by_category = {}
    for vendor in detected_vendors:
        cat = vendor['category']
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(vendor)

    # Get category order and totals
    category_order = get_all_categories()
    all_vendors = load_vendors()
    total_in_db = len(all_vendors)
    total_categories = len(category_order)

    # Show findings by category
    for cat in category_order:
        if cat in by_category:
            vendors = by_category[cat]
            vendor_names = [v['vendor_name'] for v in vendors]
            count_prefix = f"[{len(vendors)}]"
            lines.append(f"  {count_prefix} {cat}: {', '.join(vendor_names)}")

    # Stats line
    lines.append("")
    lines.append(f"  Categories: {len(by_category)} of {total_categories}  |  Vendors: {len(detected_vendors)} of {total_in_db} in database")

    return '\n'.join(lines)


def _build_takeaways(detected_vendors: list[dict]) -> str:
    """Build the TAKEAWAY section with actionable insights."""
    lines = ["TAKEAWAY"]

    # Group by category
    by_category = {}
    for vendor in detected_vendors:
        cat = vendor['category']
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(vendor)

    takeaways = []

    # Check Direct Mail (competitive)
    dm_cat = 'Direct Mail'
    if dm_cat in by_category:
        dm_vendors = [v['vendor_name'] for v in by_category[dm_cat]]
        takeaways.append(f"Competitor alert: Using {', '.join(dm_vendors)} for direct mail")
    else:
        takeaways.append("No direct mail vendor - potential prospect")

    # Check CTV (competitive)
    ctv_cat = 'CTV'
    if ctv_cat in by_category:
        ctv_vendors = [v['vendor_name'] for v in by_category[ctv_cat]]
        takeaways.append(f"Competitor alert: Using {', '.join(ctv_vendors)} for CTV")
    else:
        takeaways.append("No CTV vendor - potential prospect")

    # Social stack assessment
    social_cat = 'Social Media'
    if social_cat in by_category:
        social_count = len(by_category[social_cat])
        if social_count >= 3:
            takeaways.append(f"Heavy social presence ({social_count} platforms) - likely D2C brand")

    # Stack sophistication
    if len(detected_vendors) == 0:
        takeaways.append("No detectable martech stack")
    elif len(detected_vendors) <= 2:
        takeaways.append("Basic martech stack - may be early-stage or privacy-focused")
    elif len(detected_vendors) >= 8:
        takeaways.append("Sophisticated martech stack - mature marketing operation")

    for takeaway in takeaways:
        lines.append(f"  → {takeaway}")

    return '\n'.join(lines)


def _build_unknown_domains_table(unknown_domains: list[dict]) -> str:
    """Build the UNKNOWN DOMAINS table with box-drawing characters."""
    lines = ["UNKNOWN DOMAINS"]

    if not unknown_domains:
        lines.append("  No unknown third-party domains detected.")
        return '\n'.join(lines)

    lines.append("")

    # Calculate column widths based on content
    col_num_width = max(3, len(str(len(unknown_domains))))
    col_domain_width = max(20, max(len(d['domain']) for d in unknown_domains))
    col_requests_width = max(8, max(len(str(d['count'])) for d in unknown_domains))

    # Calculate full domains column - show up to 60 chars
    def format_full_domains(full_domains: list[str]) -> str:
        if len(full_domains) == 1:
            return full_domains[0]
        result = ', '.join(full_domains[:2])
        if len(full_domains) > 2:
            result += f" (+{len(full_domains) - 2})"
        return result

    full_domain_strs = [format_full_domains(d['full_domains']) for d in unknown_domains]
    col_full_width = max(20, min(60, max(len(s) for s in full_domain_strs)))

    # Build table
    # Header row
    top_border = f"┏━{'━' * col_num_width}━┳━{'━' * col_domain_width}━┳━{'━' * col_requests_width}━┳━{'━' * col_full_width}━┓"
    header_row = f"┃ {'#':<{col_num_width}} ┃ {'Domain':<{col_domain_width}} ┃ {'Requests':>{col_requests_width}} ┃ {'Full Domains':<{col_full_width}} ┃"
    header_sep = f"┡━{'━' * col_num_width}━╇━{'━' * col_domain_width}━╇━{'━' * col_requests_width}━╇━{'━' * col_full_width}━┩"

    lines.append(top_border)
    lines.append(header_row)
    lines.append(header_sep)

    # Data rows
    for i, domain_info in enumerate(unknown_domains, 1):
        domain = domain_info['domain']
        requests = str(domain_info['count'])
        full_domains_str = full_domain_strs[i - 1]

        # Truncate if needed
        if len(domain) > col_domain_width:
            domain = domain[:col_domain_width - 3] + "..."
        if len(full_domains_str) > col_full_width:
            full_domains_str = full_domains_str[:col_full_width - 3] + "..."

        row = f"│ {i:<{col_num_width}} │ {domain:<{col_domain_width}} │ {requests:>{col_requests_width}} │ {full_domains_str:<{col_full_width}} │"
        lines.append(row)

    # Bottom border
    bottom_border = f"└─{'─' * col_num_width}─┴─{'─' * col_domain_width}─┴─{'─' * col_requests_width}─┴─{'─' * col_full_width}─┘"
    lines.append(bottom_border)

    return '\n'.join(lines)
