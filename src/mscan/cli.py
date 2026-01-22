"""CLI entry point for the Martech Scanner."""

import json
import click
from pathlib import Path
from urllib.parse import urlparse

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from mscan.scanner import scan_website_sync
from mscan.fingerprints import match_vendors, load_vendors, get_vendors_path
from mscan.report import generate_report

# Competitive categories - these get special attention in takeaways
COMPETITIVE_CATEGORIES = [
    'Direct Mail and Offline Attribution',
    'CTV and Streaming Attribution',
]

CATEGORY_SHORT_NAMES = {
    'Direct Mail and Offline Attribution': 'Direct Mail',
    'CTV and Streaming Attribution': 'CTV',
    'Social Media Advertising': 'Social',
    'Search and Display Advertising': 'Search/Display',
    'Affiliate and Performance Marketing': 'Affiliate',
    'Analytics and Experimentation': 'Analytics',
    'Identity and Data Infrastructure': 'Identity',
    'Consent Management': 'Consent',
}


def normalize_url(url: str) -> str:
    """Ensure URL has a scheme."""
    if not url.startswith(('http://', 'https://')):
        url = f'https://{url}'
    return url


def extract_domain_name(url: str) -> str:
    """Extract clean domain name from URL."""
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path
    return domain.replace('www.', '')


def print_scan_summary(detected: list[dict], url: str, report_path: str, console: Console):
    """Print an insightful summary of scan results with actionable takeaways."""
    domain = extract_domain_name(url)
    all_vendors = load_vendors()
    total_in_db = len(all_vendors)

    # Group detected vendors by category
    by_category = {}
    for vendor in detected:
        cat = vendor['category']
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(vendor)

    # Build the summary text
    console.print()
    console.rule(f"[bold]SCAN COMPLETE: {domain.upper()}[/bold]", style="cyan")
    console.print()

    # === FINDINGS ===
    console.print("[bold]FINDINGS[/bold]")

    if not detected:
        console.print("  [dim]No martech vendors detected from the fingerprint database.[/dim]")
        console.print("  [dim]Site may use unlisted vendors or block tracking scripts.[/dim]")
    else:
        # Show findings by category (prioritize competitive categories)
        category_order = [
            'Direct Mail and Offline Attribution',
            'CTV and Streaming Attribution',
            'Social Media Advertising',
            'Search and Display Advertising',
            'Affiliate and Performance Marketing',
            'Analytics and Experimentation',
            'Identity and Data Infrastructure',
            'Consent Management',
        ]

        for cat in category_order:
            if cat in by_category:
                short_name = CATEGORY_SHORT_NAMES.get(cat, cat)
                vendors = by_category[cat]
                vendor_names = [v['vendor_name'] for v in vendors]

                # Add details if available
                details = [v['details'] for v in vendors if v.get('details')]
                detail_str = f" [dim]({details[0]})[/dim]" if details else ""

                # Count indicator for multiple vendors
                count_str = f" [dim]({len(vendors)} vendors)[/dim]" if len(vendors) > 1 else ""

                # Highlight competitive categories
                if cat in COMPETITIVE_CATEGORIES:
                    console.print(f"  [yellow]{short_name}:[/yellow] {', '.join(vendor_names)}{detail_str}{count_str}")
                else:
                    console.print(f"  [white]{short_name}:[/white] {', '.join(vendor_names)}{detail_str}{count_str}")

        # Stats line
        console.print()
        console.print(f"  [dim]Categories: {len(by_category)} of 8  |  Vendors: {len(detected)} of {total_in_db} in database[/dim]")

    # === TAKEAWAY ===
    console.print()
    console.print("[bold]TAKEAWAY[/bold]")

    takeaways = []

    # Check Direct Mail (competitive)
    dm_cat = 'Direct Mail and Offline Attribution'
    if dm_cat in by_category:
        dm_vendors = [v['vendor_name'] for v in by_category[dm_cat]]
        takeaways.append(f"[yellow]Competitor alert:[/yellow] Using {', '.join(dm_vendors)} for direct mail")
    else:
        takeaways.append("[green]No direct mail vendor[/green] - potential prospect")

    # Check CTV (competitive)
    ctv_cat = 'CTV and Streaming Attribution'
    if ctv_cat in by_category:
        ctv_vendors = [v['vendor_name'] for v in by_category[ctv_cat]]
        takeaways.append(f"[yellow]Competitor alert:[/yellow] Using {', '.join(ctv_vendors)} for CTV")
    else:
        takeaways.append("[green]No CTV vendor[/green] - potential prospect")

    # Social stack assessment
    social_cat = 'Social Media Advertising'
    if social_cat in by_category:
        social_count = len(by_category[social_cat])
        if social_count >= 3:
            takeaways.append(f"Heavy social presence ({social_count} platforms) - likely D2C brand")

    # Stack sophistication
    if len(detected) == 0:
        takeaways.append("No detectable martech stack")
    elif len(detected) <= 2:
        takeaways.append("Basic martech stack - may be early-stage or privacy-focused")
    elif len(detected) >= 8:
        takeaways.append("Sophisticated martech stack - mature marketing operation")

    for takeaway in takeaways:
        console.print(f"  → {takeaway}")

    # === REPORT ===
    console.print()
    console.print(f"[dim]Report saved: {report_path}[/dim]")


@click.group()
def cli():
    """Martech Intelligence Scanner - Identify marketing tech on any website."""
    pass


@cli.command()
@click.argument('url')
@click.option('--timeout', '-t', default=10, help='Seconds to wait for network activity per page')
@click.option('--pages', '-p', default=3, help='Maximum internal pages to scan beyond homepage')
@click.option('--headless', is_flag=True, help='Run in headless mode (may be blocked by bot detection)')
@click.option('--show-report', '-r', is_flag=True, help='Display full report in terminal after scan')
def scan(url: str, timeout: int, pages: int, headless: bool, show_report: bool):
    """Scan a website for martech vendors.

    URL can be a domain (example.com) or full URL (https://example.com)
    """
    console = Console()
    url = normalize_url(url)

    console.print(f"[bold]Scanning {url}...[/bold]")
    console.print(f"  Timeout: {timeout}s per page")
    console.print(f"  Max pages: {pages + 1} (homepage + {pages} internal)")
    console.print()

    # Phase 1: Scan website
    console.print("[dim]Phase 1: Scanning website...[/dim]")
    scan_results = scan_website_sync(url, timeout_seconds=timeout, max_internal_pages=pages, headless=headless)

    pages_scanned = scan_results.get('pages_scanned', [])
    requests = scan_results.get('requests', [])
    console.print(f"  Scanned {len(pages_scanned)} pages")
    console.print(f"  Captured {len(requests)} network requests")

    # Phase 2: Match vendors
    console.print("[dim]Phase 2: Matching vendors...[/dim]")
    detected = match_vendors(requests)
    console.print(f"  Detected {len(detected)} vendors")

    # Phase 3: Generate report
    console.print("[dim]Phase 3: Generating report...[/dim]")
    report_path = generate_report(scan_results, detected)

    # Print insightful summary
    print_scan_summary(detected, url, report_path, console)

    # Show full report if requested
    if show_report:
        console.print()
        console.rule("[bold]FULL REPORT[/bold]", style="cyan")
        with open(report_path, 'r') as f:
            console.print(f.read())


@cli.command('list-vendors')
@click.option('--category', '-c', default=None, help='Filter by category')
def list_vendors(category):
    """List all vendors in the fingerprint database with detection rules."""
    from rich.console import Console
    from rich.table import Table

    vendors = load_vendors()
    console = Console()

    # Filter by category if specified
    if category:
        vendors = [v for v in vendors if category.lower() in v['category'].lower()]
        if not vendors:
            click.echo(f"No vendors found in category matching '{category}'")
            return

    # Group by category
    by_category = {}
    for vendor in vendors:
        cat = vendor['category']
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(vendor)

    # Category order
    category_order = [
        'Direct Mail and Offline Attribution',
        'Social Media Advertising',
        'Search and Display Advertising',
        'Affiliate and Performance Marketing',
        'CTV and Streaming Attribution',
        'Analytics and Experimentation',
        'Identity and Data Infrastructure',
        'Consent Management',
    ]

    sorted_categories = [c for c in category_order if c in by_category]
    sorted_categories += [c for c in by_category if c not in category_order]

    console.print(f"\n[bold]Vendor Fingerprint Database[/bold] ({len(vendors)} vendors)\n")

    for cat in sorted_categories:
        table = Table(title=cat, title_style="bold cyan", show_header=True, header_style="bold")
        table.add_column("Vendor", style="white", min_width=20)
        table.add_column("Domains", style="green", min_width=35)
        table.add_column("URL Patterns", style="yellow", min_width=20)

        for vendor in sorted(by_category[cat], key=lambda v: v['vendor_name']):
            rules = vendor.get('detection_rules', {})
            domains = ', '.join(rules.get('domains', []))
            patterns = ', '.join(rules.get('url_patterns', [])) or '-'
            table.add_row(vendor['vendor_name'], domains, patterns)

        console.print(table)
        console.print()


@cli.command('add-vendor')
@click.argument('vendor_name')
@click.option('--sample-url', '-s', required=True, help='URL of a website known to use this vendor')
@click.option('--category', '-c', default=None, help='Vendor category (will prompt if not provided)')
@click.option('--timeout', '-t', default=10, help='Seconds to wait for network activity')
def add_vendor(vendor_name: str, sample_url: str, category: str, timeout: int):
    """Add a new vendor by discovering its fingerprint from a sample website.

    Example: mscan add-vendor "Acme Analytics" -s example.com
    """
    from rich.console import Console
    from rich.table import Table
    from urllib.parse import urlparse
    import re

    console = Console()
    sample_url = normalize_url(sample_url)

    # Check if vendor already exists
    vendors = load_vendors()
    existing_names = [v['vendor_name'].lower() for v in vendors]
    if vendor_name.lower() in existing_names:
        console.print(f"[red]Vendor '{vendor_name}' already exists in database[/red]")
        return

    console.print(f"\n[bold]Adding vendor:[/bold] {vendor_name}")
    console.print(f"[bold]Sample site:[/bold] {sample_url}\n")

    # Scan the sample website
    console.print("Scanning sample website...")
    scan_results = scan_website_sync(sample_url, timeout_seconds=timeout, max_internal_pages=0, headless=False)
    requests = scan_results.get('requests', [])
    console.print(f"  Captured {len(requests)} network requests\n")

    # Extract unique domains and find candidates matching vendor name
    vendor_lower = vendor_name.lower().replace(' ', '')
    vendor_words = vendor_name.lower().split()

    domain_counts = {}
    url_patterns = {}

    for req in requests:
        parsed = urlparse(req)
        domain = parsed.netloc.lower()

        # Skip common/known domains
        skip_domains = ['google', 'facebook', 'doubleclick', 'googleapis', 'gstatic',
                       'cloudflare', 'akamai', 'fastly', 'cdn', 'jquery', 'bootstrap']
        if any(skip in domain for skip in skip_domains):
            continue

        # Count domain occurrences
        # Extract base domain (remove subdomains for grouping)
        parts = domain.split('.')
        if len(parts) >= 2:
            base_domain = '.'.join(parts[-2:])
        else:
            base_domain = domain

        if base_domain not in domain_counts:
            domain_counts[base_domain] = {'count': 0, 'full_domains': set(), 'urls': []}
        domain_counts[base_domain]['count'] += 1
        domain_counts[base_domain]['full_domains'].add(domain)
        if len(domain_counts[base_domain]['urls']) < 3:
            domain_counts[base_domain]['urls'].append(req)

    # Score domains by relevance to vendor name
    scored_domains = []
    for domain, info in domain_counts.items():
        score = info['count']

        # Boost score if domain contains vendor name or words
        domain_clean = domain.replace('.', '').replace('-', '')
        if vendor_lower in domain_clean:
            score += 100
        for word in vendor_words:
            if len(word) > 2 and word in domain_clean:
                score += 50

        scored_domains.append({
            'domain': domain,
            'full_domains': list(info['full_domains']),
            'count': info['count'],
            'score': score,
            'urls': info['urls']
        })

    # Sort by score
    scored_domains.sort(key=lambda x: x['score'], reverse=True)

    # Show top candidates
    console.print("[bold]Candidate domains (sorted by relevance):[/bold]\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=3)
    table.add_column("Domain", style="green")
    table.add_column("Requests", justify="right")
    table.add_column("Score", justify="right")

    top_candidates = scored_domains[:15]
    for i, item in enumerate(top_candidates, 1):
        table.add_row(
            str(i),
            item['domain'],
            str(item['count']),
            str(item['score'])
        )

    console.print(table)
    console.print()

    # Prompt user to select domains
    console.print("[bold]Enter domain numbers to include (comma-separated), or 'q' to quit:[/bold]")
    selection = click.prompt("Selection", default="1")

    if selection.lower() == 'q':
        console.print("[yellow]Cancelled[/yellow]")
        return

    # Parse selection
    selected_indices = []
    for part in selection.split(','):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(top_candidates):
                selected_indices.append(idx)

    if not selected_indices:
        console.print("[red]No valid domains selected[/red]")
        return

    selected_domains = []
    for idx in selected_indices:
        selected_domains.extend(top_candidates[idx]['full_domains'])

    console.print(f"\n[bold]Selected domains:[/bold] {', '.join(selected_domains)}\n")

    # Look for URL patterns in the selected domain requests
    pattern_candidates = []
    for idx in selected_indices:
        for url in top_candidates[idx]['urls']:
            # Look for common ID patterns
            patterns_found = re.findall(r'[?&]([a-zA-Z_]+)=([^&]+)', url)
            for param, value in patterns_found:
                if len(value) > 3 and len(value) < 50:
                    pattern_candidates.append(f"{param}=")

    # Dedupe and show pattern candidates
    pattern_candidates = list(set(pattern_candidates))[:5]

    if pattern_candidates:
        console.print("[bold]Potential URL patterns found:[/bold]")
        for p in pattern_candidates:
            console.print(f"  - {p}")
        console.print()

        console.print("Enter patterns to include (comma-separated), or press Enter to skip:")
        pattern_input = click.prompt("Patterns", default="")
        selected_patterns = [p.strip() for p in pattern_input.split(',') if p.strip()]
    else:
        selected_patterns = []

    # Get category if not provided
    if not category:
        console.print("\n[bold]Select category:[/bold]")
        categories = [
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
        for i, cat in enumerate(categories, 1):
            console.print(f"  {i}. {cat}")

        cat_choice = click.prompt("Category number", type=int, default=9)
        if 1 <= cat_choice <= len(categories):
            category = categories[cat_choice - 1]
        else:
            category = 'Other/Uncategorized'

    # Create new vendor entry
    new_vendor = {
        "vendor_name": vendor_name,
        "category": category,
        "detection_rules": {
            "domains": selected_domains,
            "url_patterns": selected_patterns
        }
    }

    # Show summary
    console.print("\n[bold]New vendor entry:[/bold]")
    console.print(json.dumps(new_vendor, indent=2))

    # Confirm
    if click.confirm("\nAdd this vendor to the database?", default=True):
        # Load, append, save
        vendors_file = get_vendors_path()
        with open(vendors_file, 'r') as f:
            data = json.load(f)

        data['vendors'].append(new_vendor)

        # Sort by category then name
        data['vendors'].sort(key=lambda v: (v['category'], v['vendor_name']))

        with open(vendors_file, 'w') as f:
            json.dump(data, f, indent=2)

        console.print(f"\n[green]Successfully added '{vendor_name}' to vendors.json[/green]")
    else:
        console.print("[yellow]Cancelled[/yellow]")


if __name__ == '__main__':
    cli()
