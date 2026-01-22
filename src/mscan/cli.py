"""CLI entry point for the Martech Scanner."""

import json
import subprocess
import click
from pathlib import Path
from urllib.parse import urlparse

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.status import Status

from mscan.scanner import scan_website_sync
from mscan.fingerprints import match_vendors, load_vendors, get_vendors_path, find_unknown_domains
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

                count_prefix = f"[{len(vendors)}]"

                # Highlight competitive categories
                if cat in COMPETITIVE_CATEGORIES:
                    console.print(f"  [yellow]{count_prefix} {short_name}:[/yellow] {', '.join(vendor_names)}")
                else:
                    console.print(f"  [dim]{count_prefix}[/dim] [white]{short_name}:[/white] {', '.join(vendor_names)}")

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


def show_unknown_domains(unknown_domains: list[dict], console: Console):
    """Display unknown domains and allow user to add them as vendors."""
    from rich.table import Table

    console.print()
    console.rule("[bold]UNKNOWN DOMAINS[/bold]", style="cyan")
    console.print()
    console.print("[dim]These third-party domains were detected but aren't in the vendor database.[/dim]")
    console.print()

    # Show table of unknown domains
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=3)
    table.add_column("Domain", style="green")
    table.add_column("Requests", justify="right")
    table.add_column("Full Domains", style="dim")

    top_domains = unknown_domains[:20]  # Show top 20
    for i, item in enumerate(top_domains, 1):
        full_domains = ', '.join(item['full_domains'][:2])
        if len(item['full_domains']) > 2:
            full_domains += f" (+{len(item['full_domains']) - 2})"
        table.add_row(
            str(i),
            item['domain'],
            str(item['count']),
            full_domains
        )

    console.print(table)

    if len(unknown_domains) > 20:
        console.print(f"[dim]...and {len(unknown_domains) - 20} more[/dim]")

    console.print()
    console.print("[bold]Add vendors?[/bold] Enter numbers (e.g., 1,3,5 or 1 3 5), or press Enter to exit:")
    selection = click.prompt("Selection", default="", show_default=False)

    if not selection.strip():
        return

    # Parse selection - support "1,3,5" or "1 3 5" or "1, 3, 5"
    selection = selection.replace(',', ' ')
    selected_indices = []
    for part in selection.split():
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(top_domains):
                selected_indices.append(idx)

    if selected_indices:
        selected_domains = [top_domains[i] for i in selected_indices]
        add_vendors_batch(selected_domains, console)


def _smart_vendor_name(domain: str) -> str:
    """Generate a smart default vendor name from domain."""
    # Get first part of domain: somevendor.io -> somevendor
    name = domain.split('.')[0]
    # Handle hyphens: ad-track -> Ad Track
    name = ' '.join(word.title() for word in name.split('-'))
    return name


# Preferred category order for display
CATEGORY_ORDER = [
    'Direct Mail and Offline Attribution',
    'CTV and Streaming Attribution',
    'Social Media Advertising',
    'Search and Display Advertising',
    'Affiliate and Performance Marketing',
    'Analytics and Experimentation',
    'Identity and Data Infrastructure',
    'Consent Management',
    'Other/Uncategorized',
]


def get_categories_from_db() -> list[str]:
    """Get unique categories from vendor database, maintaining preferred order."""
    vendors = load_vendors()
    existing = set(v['category'] for v in vendors)

    # Start with preferred order categories that exist
    ordered = [c for c in CATEGORY_ORDER if c in existing]
    # Add any new categories not in preferred order
    for cat in sorted(existing):
        if cat not in ordered:
            ordered.append(cat)

    return ordered


def prompt_for_category(console: Console, inline: bool = False) -> str:
    """Prompt user to select a category, with option to create new one.

    Args:
        console: Rich console for output
        inline: If True, show compact format for batch operations

    Returns:
        Selected or newly created category name
    """
    categories = get_categories_from_db()

    if inline:
        # Compact format for batch add
        short_names = []
        for i, cat in enumerate(categories, 1):
            short = CATEGORY_SHORT_NAMES.get(cat, cat.split()[0])
            short_names.append(f"{i}={short}")
        console.print(f"[dim]Categories: {', '.join(short_names)}, 0=New[/dim]")

        cat_choice = click.prompt("  Category", type=int, default=len(categories))
    else:
        # Full format for single add
        console.print("\n[bold]Select category:[/bold]")
        for i, cat in enumerate(categories, 1):
            console.print(f"  {i}. {cat}")
        console.print(f"  0. [cyan]+ Add new category[/cyan]")

        cat_choice = click.prompt("Category number", type=int, default=len(categories))

    if cat_choice == 0:
        # Create new category
        new_cat = click.prompt("  New category name")
        if new_cat.strip():
            console.print(f"  [green]✓[/green] New category: {new_cat}")
            return new_cat.strip()
        else:
            return 'Other/Uncategorized'
    elif 1 <= cat_choice <= len(categories):
        return categories[cat_choice - 1]
    else:
        return 'Other/Uncategorized'


def add_vendors_batch(domains: list[dict], console: Console):
    """Batch workflow to add multiple vendors efficiently."""
    console.print()
    console.print(f"[bold]Adding {len(domains)} vendors...[/bold]")
    console.print()

    # Show category reference once
    categories = get_categories_from_db()
    short_names = []
    for i, cat in enumerate(categories, 1):
        short = CATEGORY_SHORT_NAMES.get(cat, cat.split()[0])
        short_names.append(f"{i}={short}")
    console.print(f"[dim]Categories: {', '.join(short_names)}, 0=New[/dim]")
    console.print()

    new_vendors = []

    for i, domain_info in enumerate(domains, 1):
        domain = domain_info['domain']
        default_name = _smart_vendor_name(domain)

        console.print(f"[cyan][{i}/{len(domains)}][/cyan] [bold]{domain}[/bold]")

        # Prompt for vendor name
        vendor_name = click.prompt("  Name", default=default_name)

        # Prompt for category with option for new
        categories = get_categories_from_db()  # Refresh in case new one was added
        cat_choice = click.prompt(f"  Category (0-{len(categories)})", type=int, default=len(categories))

        if cat_choice == 0:
            new_cat = click.prompt("  New category name")
            category = new_cat.strip() if new_cat.strip() else 'Other/Uncategorized'
            console.print(f"  [cyan]+ New category:[/cyan] {category}")
        elif 1 <= cat_choice <= len(categories):
            category = categories[cat_choice - 1]
        else:
            category = 'Other/Uncategorized'

        # Create vendor entry
        new_vendor = {
            "vendor_name": vendor_name,
            "category": category,
            "detection_rules": {
                "domains": domain_info['full_domains'],
                "url_patterns": []
            }
        }
        new_vendors.append(new_vendor)

        # Show short category name
        short_cat = CATEGORY_SHORT_NAMES.get(category, category.split(' and ')[0].split()[0])
        console.print(f"  [green]✓[/green] {vendor_name} ({short_cat})")
        console.print()

    # Save all at once
    if new_vendors:
        vendors_file = get_vendors_path()
        with open(vendors_file, 'r') as f:
            data = json.load(f)

        data['vendors'].extend(new_vendors)
        data['vendors'].sort(key=lambda v: (v['category'], v['vendor_name']))

        with open(vendors_file, 'w') as f:
            json.dump(data, f, indent=2)

        console.print(f"[green]Done! Added {len(new_vendors)} vendors to database.[/green]")


@click.group()
def cli():
    """Martech Intelligence Scanner - Identify marketing tech on any website."""
    pass


@cli.command()
@click.argument('url')
@click.option('--timeout', '-t', default=10, help='Seconds to wait for network activity per page')
@click.option('--pages', '-p', default=1, help='Maximum internal pages to scan beyond homepage')
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

    # Phase 1: Scan website with live status updates
    with console.status("[bold green]Starting scan...", spinner="dots") as status:
        def update_status(msg):
            status.update(f"[bold green]{msg}")

        scan_results = scan_website_sync(
            url,
            timeout_seconds=timeout,
            max_internal_pages=pages,
            headless=headless,
            status_callback=update_status
        )

    pages_scanned = scan_results.get('pages_scanned', [])
    requests = scan_results.get('requests', [])
    console.print(f"[green]✓[/green] Scanned {len(pages_scanned)} pages, captured {len(requests)} network requests")

    # Phase 2: Match vendors
    detected = match_vendors(requests)
    console.print(f"[green]✓[/green] Matched {len(detected)} vendors from database")

    # Phase 3: Find unknown domains
    base_domain = extract_domain_name(url)
    unknown_domains = find_unknown_domains(requests, base_domain)
    console.print(f"[green]✓[/green] Found {len(unknown_domains)} unknown third-party domains")

    # Phase 4: Generate report
    report_path = generate_report(scan_results, detected)
    console.print(f"[green]✓[/green] Report generated")

    # Print insightful summary
    print_scan_summary(detected, url, report_path, console)

    # Show full report if requested via flag
    if show_report:
        console.print()
        console.rule("[bold]FULL REPORT[/bold]", style="cyan")
        with open(report_path, 'r') as f:
            console.print(f.read())

    # Interactive options
    console.print()
    console.print("[bold]Options:[/bold]")
    console.print("  [cyan]v[/cyan] - View report in nvim")
    if unknown_domains:
        console.print(f"  [cyan]u[/cyan] - View {len(unknown_domains)} unknown domains (potential new vendors)")
    console.print("  [cyan]Enter[/cyan] - Exit")

    choice = click.prompt("Choice", default="", show_default=False)

    if choice.lower() == 'v':
        subprocess.run(['nvim', report_path])
    elif choice.lower() == 'u' and unknown_domains:
        show_unknown_domains(unknown_domains, console)


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
        category = prompt_for_category(console, inline=False)

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


@cli.command('manage-categories')
def manage_categories():
    """Manage vendor categories - rename or delete."""
    from rich.table import Table

    console = Console()
    vendors = load_vendors()

    # Count vendors per category
    cat_counts = {}
    for v in vendors:
        cat = v['category']
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    # Get ordered categories
    categories = get_categories_from_db()

    while True:
        console.print("\n[bold]Categories in database:[/bold]\n")

        table = Table(show_header=True, header_style="bold")
        table.add_column("#", style="dim", width=3)
        table.add_column("Category", style="white")
        table.add_column("Vendors", justify="right")

        for i, cat in enumerate(categories, 1):
            count = cat_counts.get(cat, 0)
            table.add_row(str(i), cat, str(count))

        console.print(table)

        console.print("\n[bold]Options:[/bold]")
        console.print("  [cyan]a[/cyan] - Add a new category")
        console.print("  [cyan]r[/cyan] - Rename a category")
        console.print("  [cyan]d[/cyan] - Delete empty category")
        console.print("  [cyan]Enter[/cyan] - Exit")

        choice = click.prompt("Choice", default="", show_default=False)

        if not choice.strip():
            break

        if choice.lower() == 'a':
            # Add new category
            new_cat = click.prompt("  New category name")
            if new_cat.strip():
                new_cat = new_cat.strip()
                if new_cat in categories:
                    console.print(f"  [yellow]Category '{new_cat}' already exists[/yellow]")
                else:
                    categories.append(new_cat)
                    cat_counts[new_cat] = 0
                    console.print(f"  [green]✓[/green] Added '{new_cat}' (will persist when a vendor uses it)")
            else:
                console.print("  [yellow]No category name provided[/yellow]")

        elif choice.lower() == 'r':
            # Rename category
            cat_num = click.prompt("Category number to rename", type=int)
            if 1 <= cat_num <= len(categories):
                old_name = categories[cat_num - 1]
                count = cat_counts.get(old_name, 0)
                console.print(f"  Current name: [cyan]{old_name}[/cyan]")
                new_name = click.prompt("  New name", default=old_name)

                if new_name.strip() and new_name.strip() != old_name:
                    new_name = new_name.strip()
                    # Update all vendors with this category
                    vendors_file = get_vendors_path()
                    with open(vendors_file, 'r') as f:
                        data = json.load(f)

                    updated = 0
                    for v in data['vendors']:
                        if v['category'] == old_name:
                            v['category'] = new_name
                            updated += 1

                    data['vendors'].sort(key=lambda v: (v['category'], v['vendor_name']))

                    with open(vendors_file, 'w') as f:
                        json.dump(data, f, indent=2)

                    console.print(f"  [green]✓[/green] Renamed '{old_name}' → '{new_name}' ({updated} vendors updated)")

                    # Refresh data
                    vendors = load_vendors()
                    cat_counts = {}
                    for v in vendors:
                        cat = v['category']
                        cat_counts[cat] = cat_counts.get(cat, 0) + 1
                    categories = get_categories_from_db()
                else:
                    console.print("  [yellow]No change[/yellow]")
            else:
                console.print("  [red]Invalid category number[/red]")

        elif choice.lower() == 'd':
            # Delete empty category
            cat_num = click.prompt("Category number to delete", type=int)
            if 1 <= cat_num <= len(categories):
                cat_name = categories[cat_num - 1]
                count = cat_counts.get(cat_name, 0)

                if count > 0:
                    console.print(f"  [red]Cannot delete '{cat_name}' - has {count} vendors[/red]")
                else:
                    console.print(f"  [green]✓[/green] Category '{cat_name}' removed (was empty)")
                    # Note: empty categories aren't stored, they just won't appear next time
                    categories = [c for c in categories if c != cat_name]
            else:
                console.print("  [red]Invalid category number[/red]")


@cli.command('manage-vendors')
@click.option('--category', '-c', default=None, help='Filter to specific category')
def manage_vendors(category):
    """Manage vendors - rename, delete, or move between categories."""
    from rich.table import Table

    console = Console()

    while True:
        vendors = load_vendors()

        # Filter by category if specified
        if category:
            vendors = [v for v in vendors if category.lower() in v['category'].lower()]
            if not vendors:
                console.print(f"[red]No vendors found in category matching '{category}'[/red]")
                return

        # Group by category for display
        by_category = {}
        for v in vendors:
            cat = v['category']
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(v)

        categories = get_categories_from_db()
        sorted_cats = [c for c in categories if c in by_category]

        console.print("\n[bold]Vendors in database:[/bold]\n")

        # Build flat list with indices
        vendor_list = []
        for cat in sorted_cats:
            console.print(f"[cyan]{cat}[/cyan]")
            for v in sorted(by_category[cat], key=lambda x: x['vendor_name']):
                vendor_list.append(v)
                idx = len(vendor_list)
                domains = v.get('detection_rules', {}).get('domains', [])
                domain_str = domains[0] if domains else '-'
                if len(domains) > 1:
                    domain_str += f" (+{len(domains)-1})"
                console.print(f"  [dim]{idx:3}.[/dim] {v['vendor_name']} [dim]({domain_str})[/dim]")
            console.print()

        console.print(f"[dim]Total: {len(vendor_list)} vendors[/dim]")

        console.print("\n[bold]Options:[/bold]")
        console.print("  [cyan]r[/cyan] - Rename a vendor")
        console.print("  [cyan]m[/cyan] - Move vendor to different category")
        console.print("  [cyan]d[/cyan] - Delete a vendor")
        console.print("  [cyan]Enter[/cyan] - Exit")

        choice = click.prompt("Choice", default="", show_default=False)

        if not choice.strip():
            break

        if choice.lower() == 'r':
            # Rename vendor
            vendor_num = click.prompt("Vendor number to rename", type=int)
            if 1 <= vendor_num <= len(vendor_list):
                vendor = vendor_list[vendor_num - 1]
                old_name = vendor['vendor_name']
                console.print(f"  Current name: [cyan]{old_name}[/cyan]")
                new_name = click.prompt("  New name", default=old_name)

                if new_name.strip() and new_name.strip() != old_name:
                    vendors_file = get_vendors_path()
                    with open(vendors_file, 'r') as f:
                        data = json.load(f)

                    for v in data['vendors']:
                        if v['vendor_name'] == old_name and v['category'] == vendor['category']:
                            v['vendor_name'] = new_name.strip()
                            break

                    data['vendors'].sort(key=lambda v: (v['category'], v['vendor_name']))

                    with open(vendors_file, 'w') as f:
                        json.dump(data, f, indent=2)

                    console.print(f"  [green]✓[/green] Renamed '{old_name}' → '{new_name.strip()}'")
                else:
                    console.print("  [yellow]No change[/yellow]")
            else:
                console.print("  [red]Invalid vendor number[/red]")

        elif choice.lower() == 'm':
            # Move vendor to different category
            vendor_num = click.prompt("Vendor number to move", type=int)
            if 1 <= vendor_num <= len(vendor_list):
                vendor = vendor_list[vendor_num - 1]
                old_cat = vendor['category']
                console.print(f"  Vendor: [cyan]{vendor['vendor_name']}[/cyan]")
                console.print(f"  Current category: [dim]{old_cat}[/dim]")

                new_cat = prompt_for_category(console, inline=False)

                if new_cat != old_cat:
                    vendors_file = get_vendors_path()
                    with open(vendors_file, 'r') as f:
                        data = json.load(f)

                    for v in data['vendors']:
                        if v['vendor_name'] == vendor['vendor_name'] and v['category'] == old_cat:
                            v['category'] = new_cat
                            break

                    data['vendors'].sort(key=lambda v: (v['category'], v['vendor_name']))

                    with open(vendors_file, 'w') as f:
                        json.dump(data, f, indent=2)

                    console.print(f"  [green]✓[/green] Moved '{vendor['vendor_name']}' to '{new_cat}'")
                else:
                    console.print("  [yellow]No change[/yellow]")
            else:
                console.print("  [red]Invalid vendor number[/red]")

        elif choice.lower() == 'd':
            # Delete vendor
            vendor_num = click.prompt("Vendor number to delete", type=int)
            if 1 <= vendor_num <= len(vendor_list):
                vendor = vendor_list[vendor_num - 1]
                console.print(f"  Vendor: [cyan]{vendor['vendor_name']}[/cyan] ({vendor['category']})")

                if click.confirm("  Are you sure you want to delete this vendor?", default=False):
                    vendors_file = get_vendors_path()
                    with open(vendors_file, 'r') as f:
                        data = json.load(f)

                    data['vendors'] = [
                        v for v in data['vendors']
                        if not (v['vendor_name'] == vendor['vendor_name'] and v['category'] == vendor['category'])
                    ]

                    with open(vendors_file, 'w') as f:
                        json.dump(data, f, indent=2)

                    console.print(f"  [green]✓[/green] Deleted '{vendor['vendor_name']}'")
                else:
                    console.print("  [yellow]Cancelled[/yellow]")
            else:
                console.print("  [red]Invalid vendor number[/red]")


if __name__ == '__main__':
    cli()
