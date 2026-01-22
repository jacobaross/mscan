"""Website scanning logic using Playwright."""

import asyncio
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright


async def scan_website(url: str, timeout_seconds: int = 10, max_internal_pages: int = 3, headless: bool = False) -> dict:
    """
    Scan a website and capture all network requests.

    Args:
        url: The URL to scan
        timeout_seconds: How long to wait for network activity per page
        max_internal_pages: Maximum number of internal pages to scan beyond homepage
        headless: Run in headless mode (may be blocked by bot detection)

    Returns:
        Dictionary with scan results including all captured URLs and pages scanned
    """
    all_requests = set()
    pages_scanned = []
    base_domain = urlparse(url).netloc.replace('www.', '')

    async with async_playwright() as p:
        # Default to headed mode to avoid bot detection
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ]
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='en-US',
            timezone_id='America/New_York',
            java_script_enabled=True,
        )

        # Remove webdriver flag to avoid detection
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # Scan homepage first
        homepage_requests, internal_links = await _scan_page(context, url, timeout_seconds, base_domain)
        all_requests.update(homepage_requests)
        pages_scanned.append(url)

        # Scan additional internal pages
        scanned_paths = {urlparse(url).path or '/'}
        pages_to_scan = []

        for link in internal_links:
            path = urlparse(link).path or '/'
            if path not in scanned_paths and len(pages_to_scan) < max_internal_pages:
                pages_to_scan.append(link)
                scanned_paths.add(path)

        for page_url in pages_to_scan:
            try:
                page_requests, _ = await _scan_page(context, page_url, timeout_seconds, base_domain)
                all_requests.update(page_requests)
                pages_scanned.append(page_url)
            except Exception as e:
                print(f"  Warning: Failed to scan {page_url}: {e}")

        await browser.close()

    return {
        'requests': list(all_requests),
        'pages_scanned': pages_scanned,
        'base_url': url
    }


async def _scan_page(context, url: str, timeout_seconds: int, base_domain: str) -> tuple[set, list]:
    """
    Scan a single page and return captured requests and internal links.

    Returns:
        Tuple of (set of request URLs, list of internal links)
    """
    captured_requests = set()
    internal_links = []

    page = await context.new_page()

    # Capture all network requests
    def handle_request(request):
        captured_requests.add(request.url)

    page.on('request', handle_request)

    try:
        # Navigate to page and wait for network to settle
        await page.goto(url, wait_until='networkidle', timeout=60000)

        # Additional wait for lazy-loaded scripts
        await asyncio.sleep(timeout_seconds)

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

    except Exception as e:
        print(f"  Error loading page {url}: {e}")
    finally:
        await page.close()

    return captured_requests, internal_links


def scan_website_sync(url: str, timeout_seconds: int = 10, max_internal_pages: int = 3, headless: bool = False) -> dict:
    """Synchronous wrapper for scan_website."""
    return asyncio.run(scan_website(url, timeout_seconds, max_internal_pages, headless))
