"""CLI entry point for the Martech Scanner."""

import json
import click
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.status import Status
from rich.table import Table
from rich import box

from mscan.scanner import scan_website_sync
from mscan.fingerprints import match_vendors, match_vendors_extended, load_vendors, get_vendors_path, find_unknown_domains, get_all_categories
from mscan.report import generate_report
from mscan.enricher import EdgarClient, ProfileBuilder

# Competitive categories - these get special attention in takeaways
COMPETITIVE_CATEGORIES = [
    'Direct Mail',
    'CTV',
]


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


def print_scan_summary(detected: list[dict], url: str, report_path: str, console: Console, enriched_brand=None):
    """Print an insightful summary of scan results with actionable takeaways."""
    from mscan.models.enriched_brand import EnrichedBrand
    
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
    header = Panel(
        f"[bold white]SCAN COMPLETE[/bold white]\n[cyan]{domain.upper()}[/cyan]",
        style="cyan",
        padding=(0, 2),
        expand=False,
    )
    console.print(header, justify="center")
    console.print()

    # === FINDINGS ===
    console.print("[bold]📊 FINDINGS[/bold]")

    if not detected:
        console.print("  [dim]No martech vendors detected from the fingerprint database.[/dim]")
        console.print("  [dim]Site may use unlisted vendors or block tracking scripts.[/dim]")
    else:
        # Show findings by category (use dynamic category order from database)
        category_order = get_all_categories()

        for cat in category_order:
            if cat in by_category:
                vendors = by_category[cat]
                vendor_names = [v['vendor_name'] for v in vendors]
                count = len(vendors)

                # Highlight competitive categories with ⚡
                if cat in COMPETITIVE_CATEGORIES:
                    console.print(f"  [yellow]⚡ {cat} ({count}):[/yellow] {', '.join(vendor_names)}")
                else:
                    console.print(f"  [white]{cat} ({count}):[/white] {', '.join(vendor_names)}")

        # Stats line
        console.print()
        total_categories = len(get_all_categories())
        console.print(f"  [dim]{len(by_category)}/{total_categories} categories - {len(detected)}/{total_in_db} vendors[/dim]")

    # === TAKEAWAY ===
    console.print()
    console.print("[bold]💡 TAKEAWAY[/bold]")

    takeaways = []

    # Check Direct Mail (competitive)
    dm_cat = 'Direct Mail'
    if dm_cat in by_category:
        dm_vendors = [v['vendor_name'] for v in by_category[dm_cat]]
        takeaways.append(f"🔶 [yellow]Competitor:[/yellow] Using {', '.join(dm_vendors)} for direct mail")
    else:
        takeaways.append("✅ [green]No direct mail vendor[/green] - potential prospect")

    # Check CTV (competitive)
    ctv_cat = 'CTV'
    if ctv_cat in by_category:
        ctv_vendors = [v['vendor_name'] for v in by_category[ctv_cat]]
        takeaways.append(f"🔶 [yellow]Competitor:[/yellow] Using {', '.join(ctv_vendors)} for CTV")
    else:
        takeaways.append("✅ [green]No CTV vendor[/green] - potential prospect")

    # Social stack assessment
    social_cat = 'Social Media'
    if social_cat in by_category:
        social_count = len(by_category[social_cat])
        if social_count >= 3:
            takeaways.append(f"📱 Heavy social presence ({social_count} platforms) - likely D2C brand")

    # Stack sophistication
    if len(detected) == 0:
        takeaways.append("⚠️  No detectable martech stack")
    elif len(detected) <= 2:
        takeaways.append("ℹ️  Basic martech stack - may be early-stage or privacy-focused")
    elif len(detected) >= 8:
        takeaways.append("🔷 Sophisticated martech stack - mature marketing operation")

    # SEC enrichment data
    if enriched_brand and enriched_brand.sec_profile:
        fin = enriched_brand.sec_profile.latest_financials
        if fin and fin.revenue_usd:
            rev_b = fin.revenue_usd / 1_000_000_000
            if rev_b >= 10:
                takeaways.append(f"📊 [cyan]SEC:[/cyan] Large public company (${rev_b:.0f}B revenue)")
            elif rev_b >= 1:
                takeaways.append(f"📊 [cyan]SEC:[/cyan] Mid-market public company (${rev_b:.1f}B revenue)")
            else:
                takeaways.append(f"📊 [cyan]SEC:[/cyan] Public company (${rev_b:.2f}B revenue)")
        
        if enriched_brand.qualification_score > 0:
            score_color = "green" if enriched_brand.qualification_score >= 70 else "yellow" if enriched_brand.qualification_score >= 40 else "red"
            takeaways.append(f"⭐ [cyan]Qualification Score:[/cyan] [{score_color}]{enriched_brand.qualification_score}/100[/{score_color}]")

    for takeaway in takeaways:
        console.print(f"  {takeaway}")

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


def get_categories_from_db() -> list[str]:
    """Get unique categories from vendor database, maintaining preferred order."""
    # Delegate to fingerprints module which has the canonical category order
    return get_all_categories()


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
        cat_labels = []
        for i, cat in enumerate(categories, 1):
            cat_labels.append(f"{i}={cat}")
        console.print(f"[dim]Categories: {', '.join(cat_labels)}, 0=New[/dim]")

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
    console.print(f"[bold]Adding {len(domains)} domain(s)...[/bold]")
    console.print("[dim]Tip: Type an existing vendor name to append domains to it[/dim]")
    console.print()

    # Show category reference once
    categories = get_categories_from_db()
    cat_labels = []
    for i, cat in enumerate(categories, 1):
        cat_labels.append(f"{i}={cat}")
    console.print(f"[dim]Categories: {', '.join(cat_labels)}, 0=New[/dim]")
    console.print()

    new_vendors = []
    appended_domains = []  # Track domains appended to existing vendors

    # Load existing vendors for matching
    existing_vendors = load_vendors()
    vendor_name_map = {v['vendor_name'].lower(): v for v in existing_vendors}

    for i, domain_info in enumerate(domains, 1):
        domain = domain_info['domain']
        default_name = _smart_vendor_name(domain)

        console.print(f"[cyan][{i}/{len(domains)}][/cyan] [bold]{domain}[/bold]")

        # Prompt for vendor name
        vendor_name = click.prompt("  Name", default=default_name)

        # Check if this matches an existing vendor
        existing_vendor = vendor_name_map.get(vendor_name.lower())
        if existing_vendor:
            # Ask to append
            append = click.confirm(
                f"  Found existing '{existing_vendor['vendor_name']}'. Append domain?",
                default=True
            )
            if append:
                appended_domains.append({
                    'vendor': existing_vendor,
                    'domains': domain_info['full_domains']
                })
                console.print(f"  [green]✓[/green] Added to {existing_vendor['vendor_name']} ({existing_vendor['category']})")
                console.print()
                continue

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

        # Add to map so subsequent domains can reference it
        vendor_name_map[vendor_name.lower()] = new_vendor

        # Show category name
        console.print(f"  [green]✓[/green] {vendor_name} ({category})")
        console.print()

    # Save all changes
    if new_vendors or appended_domains:
        vendors_file = get_vendors_path()
        with open(vendors_file, 'r') as f:
            data = json.load(f)

        # Add new vendors
        data['vendors'].extend(new_vendors)

        # Append domains to existing vendors
        for append_info in appended_domains:
            for vendor in data['vendors']:
                if vendor['vendor_name'] == append_info['vendor']['vendor_name']:
                    # Add new domains, avoiding duplicates
                    existing = set(vendor['detection_rules']['domains'])
                    for new_domain in append_info['domains']:
                        if new_domain not in existing:
                            vendor['detection_rules']['domains'].append(new_domain)
                    break

        data['vendors'].sort(key=lambda v: (v['category'], v['vendor_name']))

        with open(vendors_file, 'w') as f:
            json.dump(data, f, indent=2)

        # Summary message
        msgs = []
        if new_vendors:
            msgs.append(f"added {len(new_vendors)} new vendor(s)")
        if appended_domains:
            msgs.append(f"appended domains to {len(appended_domains)} existing vendor(s)")
        console.print(f"[green]Done! {', '.join(msgs).capitalize()}.[/green]")


@click.group()
def cli():
    """Martech Intelligence Scanner - Identify marketing tech on any website."""
    pass


@cli.command()
@click.argument('url')
@click.option('--timeout', '-t', default=10, help='Seconds to wait for network activity per page')
@click.option('--pages', '-p', default=1, help='Maximum internal pages to scan beyond homepage')
@click.option('--headless', is_flag=True, help='Run in headless mode (may be blocked by bot detection)')
@click.option('--system-browser', '-s', is_flag=True, help='Use system Chromium (bypasses Akamai/bot detection)')
@click.option('--show-report', '-r', is_flag=True, help='Display full report in terminal after scan')
@click.option('--enrich', '-e', is_flag=True, help='Enrich with SEC EDGAR data if public company')
def scan(url: str, timeout: int, pages: int, headless: bool, system_browser: bool, show_report: bool, enrich: bool):
    """Scan a website for martech vendors.

    URL can be a domain (example.com) or full URL (https://example.com)
    """
    console = Console()
    url = normalize_url(url)
    base_domain = extract_domain_name(url)

    console.print(f"[bold]Scanning {url}...[/bold]")
    console.print(f"  Timeout: {timeout}s per page")
    console.print(f"  Max pages: {pages + 1} (homepage + {pages} internal)")
    if enrich:
        console.print(f"  [cyan]SEC enrichment enabled[/cyan]")
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
            system_browser=system_browser,
            status_callback=update_status
        )

    pages_scanned = scan_results.get('pages_scanned', [])
    requests = scan_results.get('requests', [])
    console.print(f"[green]✓[/green] Scanned {len(pages_scanned)} pages, captured {len(requests)} network requests")

    # Phase 2: Match vendors (vendors.json + tracker_db.json fallback)
    detected = match_vendors_extended(requests)
    console.print(f"[green]✓[/green] Matched {len(detected)} vendors from database")

    # Phase 3: Find unknown domains
    unknown_domains = find_unknown_domains(requests, base_domain)
    console.print(f"[green]✓[/green] Found {len(unknown_domains)} unknown third-party domains")

    # Phase 4: SEC Enrichment (if enabled)
    enriched_brand = None
    if enrich:
        console.print(f"[bold green]Enriching with SEC data...[/bold green]")
        try:
            user_agent = _get_user_agent()
            with EdgarClient(user_agent=user_agent) as client:
                builder = ProfileBuilder()
                
                # Try to enrich by domain name (as company name)
                company_name = base_domain.replace('www.', '').split('.')[0].capitalize()
                
                with console.status(f"[green]Looking up {company_name}...", spinner="dots"):
                    result = client.enrich_by_name(company_name)
                
                if result.success:
                    scan_data = {
                        'vendors': detected,
                        'scanned_at': datetime.now()
                    }
                    enriched_brand = builder.build_profile_from_enrichment(
                        base_domain, result, scan_data
                    )
                    console.print(f"[green]✓[/green] Enriched: [cyan]{enriched_brand.sec_profile.company_name}[/cyan]")
                    if enriched_brand.sec_profile.latest_financials:
                        fin = enriched_brand.sec_profile.latest_financials
                        if fin.revenue_usd:
                            rev_b = fin.revenue_usd / 1_000_000_000
                            console.print(f"    Revenue: ${rev_b:.1f}B | Score: {enriched_brand.qualification_score}")
                else:
                    console.print(f"[yellow]⚠[/yellow] Could not enrich (may be private company)")
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow] Enrichment failed: {str(e)}")

    # Phase 5: Generate report
    report_path = generate_report(scan_results, detected, unknown_domains)
    console.print(f"[green]✓[/green] Report generated")

    # Print insightful summary
    print_scan_summary(detected, url, report_path, console, enriched_brand)

    # Show full report if requested via flag
    if show_report:
        console.print()
        console.rule("[bold]FULL REPORT[/bold]", style="cyan")
        with open(report_path, 'r') as f:
            console.print(f.read())
    
    # Show enriched profile if available
    if enriched_brand:
        console.print()
        console.print("[bold cyan]View enriched profile?[/bold cyan] (y/n)")
        if click.confirm("", default=False):
            console.print()
            _display_profile(console, enriched_brand)

    # Interactive options loop
    while True:
        console.print()
        console.print("[bold]Options:[/bold]")
        console.print("  [cyan]v[/cyan] - View full report")
        if unknown_domains:
            console.print(f"  [cyan]u[/cyan] - View {len(unknown_domains)} unknown domains (potential new vendors)")
        console.print("  [cyan]Enter[/cyan] - Exit")

        choice = click.prompt("Choice", default="", show_default=False)

        if choice.lower() == 'v':
            console.print()
            console.rule("[bold]FULL REPORT[/bold]", style="cyan")
            with open(report_path, 'r') as f:
                console.print(f.read())
        elif choice.lower() == 'u' and unknown_domains:
            show_unknown_domains(unknown_domains, console)
            break  # Exit after unknown domains workflow
        else:
            break  # Exit on Enter or any other input


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

    # Use dynamic category order from database
    category_order = get_all_categories()

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


@cli.command('batch')
@click.argument('file', type=click.Path(exists=True))
@click.option('--timeout', '-t', default=10, help='Seconds to wait for network activity per page')
@click.option('--pages', '-p', default=1, help='Maximum internal pages to scan beyond homepage')
@click.option('--headless', is_flag=True, help='Run in headless mode (may be blocked by bot detection)')
@click.option('--system-browser', '-s', is_flag=True, help='Use system Chromium (bypasses Akamai/bot detection)')
@click.option('--csv', 'csv_output', type=click.Path(), default=None, help='Export results to CSV file')
def batch(file: str, timeout: int, pages: int, headless: bool, system_browser: bool, csv_output: str):
    """Batch scan multiple domains from a file.

    FILE can be a text file with one domain per line, or a CSV file.
    Lines starting with # are treated as comments and skipped.

    Example:
        mscan batch domains.txt
        mscan batch domains.txt --csv results.csv
    """
    import csv as csv_module
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

    console = Console()

    # Read domains from file
    domains = []
    file_path = Path(file)

    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            # Handle CSV - take first column
            if ',' in line:
                line = line.split(',')[0].strip()
            # Remove quotes if present
            line = line.strip('"\'')
            if line:
                domains.append(line)

    if not domains:
        console.print("[red]No domains found in file[/red]")
        return

    console.print(f"[bold]Batch scanning {len(domains)} domains...[/bold]")
    console.print(f"  Timeout: {timeout}s per page | Max pages: {pages + 1}")
    console.print()

    # Get all categories for table columns
    all_categories = get_all_categories()

    # Store results for each domain
    results = []

    # Scan each domain with progress
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("Scanning...", total=len(domains))

        for domain in domains:
            url = normalize_url(domain)
            domain_name = extract_domain_name(url)
            progress.update(task, description=f"Scanning {domain_name}...")

            try:
                # Scan website
                scan_results = scan_website_sync(
                    url,
                    timeout_seconds=timeout,
                    max_internal_pages=pages,
                    headless=headless,
                    system_browser=system_browser,
                    status_callback=None  # No status updates in batch mode
                )

                requests = scan_results.get('requests', [])

                # Match vendors (vendors.json + tracker_db.json fallback)
                detected = match_vendors_extended(requests)

                # Find unknown domains
                unknown_domains = find_unknown_domains(requests, domain_name)

                # Group detected by category
                by_category = {}
                for vendor in detected:
                    cat = vendor['category']
                    if cat not in by_category:
                        by_category[cat] = []
                    by_category[cat].append(vendor['vendor_name'])

                # Store result
                results.append({
                    'domain': domain_name,
                    'status': 'ok',
                    'by_category': by_category,
                    'unknown': [u['domain'] for u in unknown_domains[:10]],  # Top 10
                    'unknown_count': len(unknown_domains)
                })

            except Exception as e:
                results.append({
                    'domain': domain_name,
                    'status': 'error',
                    'error': str(e),
                    'by_category': {},
                    'unknown': [],
                    'unknown_count': 0
                })

            progress.advance(task)

    console.print()

    # Determine which categories have any data across all results
    categories_with_data = set()
    for result in results:
        if result['status'] == 'ok':
            for cat in result['by_category']:
                if result['by_category'][cat]:
                    categories_with_data.add(cat)

    # Always include competitive categories even if empty
    for cat in COMPETITIVE_CATEGORIES:
        categories_with_data.add(cat)

    # Filter to only categories with data, maintaining order
    display_categories = [cat for cat in all_categories if cat in categories_with_data]

    # Build and display results table
    table = Table(title="Batch Scan Results", show_header=True, header_style="bold", box=None)
    table.add_column("Brand", style="cyan", no_wrap=True)

    # Short category names for display
    category_short_names = {
        'Direct Mail': 'Direct Mail',
        'CTV': 'CTV',
        'Social Media': 'Social',
        'Search': 'Search',
        'Affiliate': 'Affiliate',
        'Performance': 'Performance',
        'Analytics': 'Analytics',
        'ID & Data Infra': 'ID/Data',
        'Consent Mgmt': 'Consent',
        'CDP': 'CDP',
        'DSP': 'DSP',
        'Email': 'Email',
        'Other': 'Other',
        'SSP': 'SSP',
    }

    for cat in display_categories:
        short_name = category_short_names.get(cat, cat)
        if cat in COMPETITIVE_CATEGORIES:
            table.add_column(short_name, style="yellow")
        else:
            table.add_column(short_name, style="white")

    table.add_column("Unknown", style="dim")

    # Vendor name shortening map
    vendor_short = {
        'PebblePost': 'PebblePost',
        'LS Direct': 'LS Direct',
        'Meta Pixel': 'Meta',
        'Snapchat Pixel': 'Snap',
        'TikTok Pixel': 'TikTok',
        'X/Twitter Pixel': 'X',
        'Pinterest Tag': 'Pinterest',
        'LinkedIn Insight': 'LinkedIn',
        'Reddit Pixel': 'Reddit',
        'Google Ads': 'GAds',
        'MSFT/Bing': 'Bing',
        'Google Analytics': 'GA',
        'Adobe Analytics': 'Adobe',
        'The Trade Desk': 'TTD',
        'MNTN/SHOU': 'MNTN',
    }

    def shorten_vendor(name):
        return vendor_short.get(name, name.replace(' Pixel', '').replace(' Tag', ''))

    # Add rows for each domain
    for result in results:
        if result['status'] == 'error':
            row = [result['domain']] + ['[red]ERR[/red]'] * (len(display_categories) + 1)
        else:
            row = [result['domain']]
            for cat in display_categories:
                vendors = result['by_category'].get(cat, [])
                if vendors:
                    short_names = [shorten_vendor(v) for v in vendors]
                    row.append(', '.join(short_names))
                else:
                    row.append('-')
            # Unknown trackers column
            if result['unknown']:
                if result['unknown_count'] <= 5:
                    row.append(', '.join(result['unknown']))
                else:
                    top_3 = result['unknown'][:3]
                    row.append(f"{', '.join(top_3)} +{result['unknown_count'] - 3}")
            else:
                row.append('-')
        table.add_row(*row)

    console.print(table)

    # Summary stats
    successful = sum(1 for r in results if r['status'] == 'ok')
    failed = sum(1 for r in results if r['status'] == 'error')
    console.print()
    console.print(f"[dim]Scanned: {successful} successful, {failed} failed[/dim]")

    # Export to CSV if requested
    if csv_output:
        csv_path = Path(csv_output)
        with open(csv_path, 'w', newline='') as f:
            writer = csv_module.writer(f)

            # Header row
            header = ['Brand'] + all_categories + ['Unknown Trackers']
            writer.writerow(header)

            # Data rows
            for result in results:
                if result['status'] == 'error':
                    row = [result['domain']] + ['ERROR'] * (len(all_categories) + 1)
                else:
                    row = [result['domain']]
                    for cat in all_categories:
                        vendors = result['by_category'].get(cat, [])
                        row.append(', '.join(vendors) if vendors else '')
                    # Unknown trackers
                    row.append(', '.join(result['unknown']) if result['unknown'] else '')
                writer.writerow(row)

        console.print(f"[green]Results exported to {csv_path}[/green]")


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


def _get_user_agent() -> str:
    """Get user agent for SEC EDGAR API from config or use default."""
    # Try to get from config file if it exists
    config_path = Path.home() / '.mscan' / 'config.json'
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
                return config.get('edgar_user_agent', 'mscan user@example.com')
        except Exception:
            pass
    return 'mscan user@example.com'


@cli.command('enrich')
@click.argument('identifier', required=False)
@click.option('--file', '-f', type=click.Path(exists=True), help='File with domains/tickers (one per line)')
@click.option('--refresh', is_flag=True, help='Force refresh from SEC EDGAR API')
@click.option('--output', '-o', type=click.Path(), help='Output file for results (JSON)')
def enrich(identifier: str, file: str, refresh: bool, output: str):
    """Enrich company data with SEC EDGAR information.
    
    IDENTIFIER can be a ticker (AAPL), domain (apple.com), or company name.
    Use --file for batch enrichment of multiple companies.
    
    Examples:
        mscan enrich AAPL                    # By ticker
        mscan enrich apple.com               # By domain
        mscan enrich "Apple Inc"             # By company name
        mscan enrich AAPL --refresh          # Force refresh
        mscan enrich --file companies.txt    # Batch enrichment
    """
    console = Console()
    
    # Validate input
    if not identifier and not file:
        console.print("[red]Error: Provide an identifier or use --file[/red]")
        raise click.UsageError("Must provide identifier or --file")
    
    if identifier and file:
        console.print("[red]Error: Cannot use both identifier and --file[/red]")
        raise click.UsageError("Use either identifier or --file, not both")
    
    # Get identifiers to process
    identifiers = []
    if file:
        with open(file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    identifiers.append(line)
        console.print(f"[bold]Batch enriching {len(identifiers)} companies...[/bold]\n")
    else:
        identifiers = [identifier]
    
    # Initialize clients
    user_agent = _get_user_agent()
    
    try:
        with EdgarClient(user_agent=user_agent) as client:
            builder = ProfileBuilder()
            results = []
            
            for idx, ident in enumerate(identifiers, 1):
                if len(identifiers) > 1:
                    console.print(f"[{idx}/{len(identifiers)}] Enriching: [cyan]{ident}[/cyan]")
                else:
                    console.print(f"Enriching: [cyan]{ident}[/cyan]")
                
                # Determine if ticker, domain, or name
                ident_clean = ident.strip()
                is_ticker = (
                    len(ident_clean) <= 5 and 
                    ident_clean.isalpha() and 
                    ident_clean.isupper()
                )
                
                # Attempt enrichment
                try:
                    if is_ticker:
                        result = client.enrich_by_ticker(ident_clean)
                    elif '.' in ident_clean and not ident_clean.isupper():
                        # Looks like a domain
                        # First try to resolve ticker from domain (future feature)
                        # For now, try name lookup
                        domain = ident_clean.replace('https://', '').replace('http://', '').strip('/')
                        result = client.enrich_by_name(domain.split('.')[0].capitalize())
                        if not result.success:
                            # Try direct name
                            result = client.enrich_by_name(ident_clean)
                    else:
                        # Treat as company name
                        result = client.enrich_by_name(ident_clean)
                    
                    # Build profile
                    domain = ident_clean if '.' in ident_clean else f"{ident_clean.lower()}.com"
                    brand = builder.build_profile_from_enrichment(domain, result)
                    results.append({
                        'identifier': ident,
                        'success': True,
                        'brand': brand.model_dump() if hasattr(brand, 'model_dump') else brand.dict()
                    })
                    
                    # Print summary
                    if result.success:
                        console.print(f"  [green]✓[/green] {brand.sec_profile.company_name if brand.sec_profile else 'Unknown'}")
                        if brand.sec_profile and brand.sec_profile.latest_financials:
                            fin = brand.sec_profile.latest_financials
                            if fin.revenue_usd:
                                rev_b = fin.revenue_usd / 1_000_000_000
                                console.print(f"    Revenue: ${rev_b:.1f}B | Score: {brand.qualification_score}")
                    else:
                        console.print(f"  [yellow]⚠[/yellow] {result.error.message if result.error else 'Unknown error'}")
                    
                except Exception as e:
                    console.print(f"  [red]✗[/red] Error: {str(e)}")
                    results.append({
                        'identifier': ident,
                        'success': False,
                        'error': str(e)
                    })
            
            # Print summary for batch
            if len(identifiers) > 1:
                success_count = sum(1 for r in results if r.get('success'))
                console.print(f"\n[bold]Completed:[/bold] {success_count}/{len(identifiers)} successful")
            
            # Save to file if requested
            if output:
                with open(output, 'w') as f:
                    json.dump(results, f, indent=2, default=str)
                console.print(f"[green]Results saved to {output}[/green]")
    
    except Exception as e:
        console.print(f"[red]Error initializing EDGAR client: {e}[/red]")
        raise click.Abort()


@cli.command('profile')
@click.argument('identifier')
@click.option('--refresh', is_flag=True, help='Force refresh from SEC EDGAR API')
def profile(identifier: str, refresh: bool):
    """Display detailed enriched profile for a company.
    
    IDENTIFIER can be a ticker (AAPL), domain (apple.com), or company name.
    
    Examples:
        mscan profile AAPL                    # By ticker
        mscan profile apple.com               # By domain
        mscan profile "Apple Inc"             # By company name
    """
    console = Console()
    console.print(f"[bold]Loading profile for:[/bold] [cyan]{identifier}[/cyan]\n")
    
    user_agent = _get_user_agent()
    
    try:
        with EdgarClient(user_agent=user_agent) as client:
            builder = ProfileBuilder()
            
            # Determine lookup method
            ident_clean = identifier.strip()
            is_ticker = (
                len(ident_clean) <= 5 and 
                ident_clean.isalpha() and 
                ident_clean.isupper()
            )
            
            # Get enrichment result
            with console.status("[green]Fetching SEC data...", spinner="dots"):
                if is_ticker:
                    result = client.enrich_by_ticker(ident_clean)
                else:
                    result = client.enrich_by_name(ident_clean)
            
            if not result.success:
                console.print(f"[red]Error:[/red] {result.error.message if result.error else 'Failed to enrich'}")
                return
            
            # Build and display profile
            domain = ident_clean if '.' in ident_clean else f"{ident_clean.lower()}.com"
            brand = builder.build_profile_from_enrichment(domain, result)
            
            # Display profile
            _display_profile(console, brand)
    
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")


def _display_profile(console: Console, brand):
    """Display a rich profile output."""
    
    # Header
    if brand.sec_profile:
        header_text = f"[bold white]{brand.sec_profile.company_name}[/bold white]"
        if brand.sec_profile.ticker:
            header_text += f" [cyan]({brand.sec_profile.ticker})[/cyan]"
        console.print(Panel(header_text, style="bold blue", expand=False))
    else:
        console.print(Panel(f"[bold white]{brand.domain}[/bold white]", style="bold blue", expand=False))
    
    console.print()
    
    # Basic Info
    if brand.sec_profile:
        console.print("[bold]📋 COMPANY INFORMATION[/bold]")
        info_table = Table(show_header=False, box=None)
        info_table.add_column("Field", style="dim")
        info_table.add_column("Value", style="white")
        
        if brand.sec_profile.sic_description:
            info_table.add_row("Industry", brand.sec_profile.sic_description)
        if brand.sec_profile.exchange:
            info_table.add_row("Exchange", brand.sec_profile.exchange)
        if brand.sec_profile.fiscal_year_end:
            info_table.add_row("Fiscal Year End", brand.sec_profile.fiscal_year_end)
        
        console.print(info_table)
        console.print()
    
    # Financials
    if brand.sec_profile and brand.sec_profile.latest_financials:
        fin = brand.sec_profile.latest_financials
        console.print("[bold]💰 FINANCIAL METRICS[/bold]")
        
        fin_table = Table(show_header=True, header_style="bold")
        fin_table.add_column("Metric", style="white")
        fin_table.add_column("Value", justify="right", style="green")
        fin_table.add_column("Details", style="dim")
        
        if fin.revenue_usd:
            rev_b = fin.revenue_usd / 1_000_000_000
            growth = f" ({fin.revenue_growth_yoy:+.1f}%)" if fin.revenue_growth_yoy else ""
            fin_table.add_row("Revenue", f"${rev_b:.2f}B", f"FY{fin.fiscal_year or 'Unknown'}{growth}")
        
        if fin.net_income_usd:
            income_b = fin.net_income_usd / 1_000_000_000
            fin_table.add_row("Net Income", f"${income_b:.2f}B", "")
        
        if fin.total_assets_usd:
            assets_b = fin.total_assets_usd / 1_000_000_000
            fin_table.add_row("Total Assets", f"${assets_b:.2f}B", "")
        
        if fin.employee_count:
            fin_table.add_row("Employees", f"{fin.employee_count:,}", "")
        
        if fin.marketing_spend_usd:
            mkt_m = fin.marketing_spend_usd / 1_000_000
            if fin.revenue_usd:
                mkt_pct = (fin.marketing_spend_usd / fin.revenue_usd) * 100
                fin_table.add_row("Marketing Spend", f"${mkt_m:.0f}M", f"{mkt_pct:.1f}% of revenue")
            else:
                fin_table.add_row("Marketing Spend", f"${mkt_m:.0f}M", "")
        
        if fin.rd_spend_usd:
            rd_m = fin.rd_spend_usd / 1_000_000
            if fin.revenue_usd:
                rd_pct = (fin.rd_spend_usd / fin.revenue_usd) * 100
                fin_table.add_row("R&D Spend", f"${rd_m:.0f}M", f"{rd_pct:.1f}% of revenue")
            else:
                fin_table.add_row("R&D Spend", f"${rd_m:.0f}M", "")
        
        console.print(fin_table)
        console.print()
    
    # Qualification Score
    score_color = "green" if brand.qualification_score >= 70 else "yellow" if brand.qualification_score >= 40 else "red"
    console.print(f"[bold]📊 QUALIFICATION SCORE:[/bold] [{score_color}]{brand.qualification_score}/100[/{score_color}]")
    console.print(f"[dim]Confidence: {brand.confidence_level} | Data completeness: {brand.data_completeness:.0%}[/dim]")
    console.print()
    
    # Insights
    if brand.insights:
        console.print("[bold]💡 INSIGHTS[/bold]")
        for insight in brand.insights:
            console.print(f"  • {insight}")
        console.print()
    
    # Recommendations
    if brand.recommendations:
        console.print("[bold]🎯 RECOMMENDATIONS[/bold]")
        for rec in brand.recommendations:
            console.print(f"  • {rec}")
        console.print()
    
    # Detected Technologies
    if brand.detected_technologies:
        console.print(f"[bold]🔧 DETECTED TECHNOLOGIES ({len(brand.detected_technologies)})[/bold]")
        
        # Group by category
        by_category = {}
        for tech in brand.detected_technologies:
            cat = tech.get('category', 'Unknown')
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(tech.get('vendor', 'Unknown'))
        
        tech_table = Table(show_header=True, header_style="bold")
        tech_table.add_column("Category", style="cyan")
        tech_table.add_column("Vendors", style="white")
        
        for cat, vendors in sorted(by_category.items()):
            tech_table.add_row(cat, ", ".join(vendors))
        
        console.print(tech_table)


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
