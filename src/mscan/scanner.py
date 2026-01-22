"""Website scanning logic using Playwright."""

import asyncio
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# Patterns that indicate a product page (retail sites)
PRODUCT_PATTERNS = [
    '/product/', '/products/',
    '/p/', '/item/', '/items/',
    '/dp/', '/gp/product/',  # Amazon-style
    '/shop/',  # if followed by more path segments
    '/buy/',
    '/sku/',
]


def _score_product_likelihood(url: str) -> int:
    """Score how likely a URL is to be a product page. Higher = more likely."""
    score = 0
    parsed = urlparse(url)
    path = parsed.path.lower()

    # Check for product patterns
    for pattern in PRODUCT_PATTERNS:
        if pattern in path:
            score += 10

    # URLs with long alphanumeric segments often are product pages
    # e.g., /p/ABC123-blue-widget or /products/mattress-purple-queen
    segments = path.split('/')
    for seg in segments:
        if len(seg) > 5 and any(c.isdigit() for c in seg):
            score += 5
        # Long slug-like segments with hyphens are often product names
        if len(seg) > 10 and '-' in seg:
            score += 3

    return score


async def scan_website(url: str, timeout_seconds: int = 10, max_internal_pages: int = 3, headless: bool = False, system_browser: bool = False, status_callback=None) -> dict:
    """
    Scan a website and capture all network requests.

    Args:
        url: The URL to scan
        timeout_seconds: How long to wait for network activity per page
        max_internal_pages: Maximum number of internal pages to scan beyond homepage
        headless: Run in headless mode (may be blocked by bot detection)
        system_browser: Use system Chromium instead of bundled (bypasses some bot detection)

    Returns:
        Dictionary with scan results including all captured URLs and pages scanned
    """
    def status(msg):
        if status_callback:
            status_callback(msg)

    all_requests = set()
    pages_scanned = []
    base_domain = urlparse(url).netloc.replace('www.', '')

    status("Warming up the browser...")

    async with async_playwright() as p:
        # Default to headed mode to avoid bot detection
        if system_browser:
            # For system browser: minimal args to avoid fingerprinting
            import shutil
            system_chromium = shutil.which('chromium') or shutil.which('google-chrome') or shutil.which('chromium-browser')
            launch_args = {
                'headless': headless,
                'executable_path': system_chromium,
                'args': ['--disable-blink-features=AutomationControlled']
            }
        else:
            # For bundled Chromium: extra args needed for compatibility
            launch_args = {
                'headless': headless,
                'args': [
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                ]
            }

        browser = await p.chromium.launch(**launch_args)

        status("Putting on disguise...")

        # Use a realistic user agent (updated for system browser)
        if system_browser:
            # Match typical system Chromium version
            user_agent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
        else:
            user_agent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'

        # Context options - skip locale for system browser (triggers Akamai detection)
        context_opts = {
            'user_agent': user_agent,
            'viewport': {'width': 1920, 'height': 1080},
            'java_script_enabled': True,
        }
        if not system_browser:
            context_opts['locale'] = 'en-US'
            context_opts['timezone_id'] = 'America/New_York'

        context = await browser.new_context(**context_opts)

        # Only add webdriver-hiding script for bundled Chromium
        # System browsers don't expose webdriver, and the script itself can trigger detection
        if not system_browser:
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

        # Scan homepage first
        status("Visiting homepage...")
        homepage_requests, internal_links = await _scan_page(context, url, timeout_seconds, base_domain, status)
        all_requests.update(homepage_requests)
        pages_scanned.append(url)

        # Scan additional internal pages, prioritizing product pages
        scanned_paths = {urlparse(url).path or '/'}

        # Score and sort links by product page likelihood
        scored_links = []
        for link in internal_links:
            path = urlparse(link).path or '/'
            if path not in scanned_paths:
                score = _score_product_likelihood(link)
                scored_links.append((score, link, path))

        # Sort by score descending, take top candidates
        scored_links.sort(key=lambda x: x[0], reverse=True)

        pages_to_scan = []
        for score, link, path in scored_links:
            if len(pages_to_scan) >= max_internal_pages:
                break
            pages_to_scan.append(link)
            scanned_paths.add(path)

        for i, page_url in enumerate(pages_to_scan):
            status(f"Exploring page {i + 2} of {len(pages_to_scan) + 1}...")
            try:
                page_requests, _ = await _scan_page(context, page_url, timeout_seconds, base_domain, status)
                all_requests.update(page_requests)
                pages_scanned.append(page_url)
            except Exception:
                pass  # Silently skip failed pages

        await browser.close()

    return {
        'requests': list(all_requests),
        'pages_scanned': pages_scanned,
        'base_url': url
    }


async def _scan_page(context, url: str, timeout_seconds: int, base_domain: str, status_callback=None) -> tuple[set, list]:
    """
    Scan a single page and return captured requests and internal links.

    Returns:
        Tuple of (set of request URLs, list of internal links)
    """
    def status(msg):
        if status_callback:
            status_callback(msg)

    captured_requests = set()
    internal_links = []

    page = await context.new_page()

    # Capture all network requests
    def handle_request(request):
        captured_requests.add(request.url)

    page.on('request', handle_request)

    try:
        # Navigate to page - use 'load' event (DOM ready) with short timeout
        # Don't use 'networkidle' - retail sites with trackers never reach it
        status("Waiting for page to load...")
        try:
            await page.goto(url, wait_until='load', timeout=15000)
        except PlaywrightTimeout:
            # Page took too long - continue anyway, we're capturing requests
            status("Page slow to respond... (continuing anyway)")

        # Additional wait for lazy-loaded scripts with periodic status updates
        wait_messages = [
            "Watching for sneaky trackers",
            "Waiting for lazy scripts",
            "Catching stragglers",
            "Almost done with this page",
        ]
        for i in range(timeout_seconds):
            msg_idx = min(i // 3, len(wait_messages) - 1)  # Change message every 3 seconds
            status(f"{wait_messages[msg_idx]}... ({len(captured_requests)} requests)")
            await asyncio.sleep(1)

        status("Cataloging the surveillance...")
        # Extract internal links for further scanning
        links = await page.evaluate('''() => {
            const links = Array.from(document.querySelectorAll('a[href]'));
            return links.map(a => a.href).filter(href => href.startsWith('http'));
        }''')

        # Filter to same-domain links
        for link in links:
            link_domain = urlparse(link).netloc.replace('www.', '')
            if link_domain == base_domain:
                internal_links.append(link)

    except PlaywrightTimeout:
        # Already handled above, but just in case
        pass
    except Exception:
        # Silently handle other errors - we still got requests
        pass
    finally:
        await page.close()

    return captured_requests, internal_links


def scan_website_sync(url: str, timeout_seconds: int = 10, max_internal_pages: int = 3, headless: bool = False, system_browser: bool = False, status_callback=None) -> dict:
    """Synchronous wrapper for scan_website."""
    return asyncio.run(scan_website(url, timeout_seconds, max_internal_pages, headless, system_browser, status_callback))
