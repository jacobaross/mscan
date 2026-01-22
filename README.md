# mscan

```
╔═══════════════════════╗
║   ❯ scanning...       ║
║   ▰▰▰▰▰▰▰▱▱▱  78%     ║    mscan
║                       ║    Martech Intelligence Scanner
║   «G» «META» «PBL»    ║
╚═══════════════════════╝
```

**Martech Intelligence Scanner** — CLI tool that scans websites and exposes their marketing/advertising technology stack by sniffing network requests and matching them against a fingerprint database.

## What It Does

Point mscan at any website and it will:

- Fire up a real browser (Chromium via Playwright)
- Capture all network requests as the page loads
- Match requests against 40+ known martech vendors
- Surface unknown third-party domains for investigation
- Generate actionable intelligence reports

Perfect for competitive analysis, sales prospecting, or just satisfying your curiosity about what's tracking you.

## Installation

Requires Python 3.10+

**macOS**
```bash
git clone https://github.com/jacobaross/mscan.git
cd mscan
python3 -m venv venv
source venv/bin/activate
pip install -e .
playwright install chromium
```

**Linux**
```bash
git clone https://github.com/jacobaross/mscan.git
cd mscan
pip install -e .
playwright install chromium
```

## Quick Start

```bash
# Scan a website
mscan scan nike.com

# Scan with longer timeout and more pages
mscan scan bestbuy.com --timeout 15 --pages 3

# Headless mode (faster but may be blocked)
mscan scan target.com --headless
```

## Sample Output

```
━━━━━━━━━━━━━━━━ SCAN COMPLETE: NIKE.COM ━━━━━━━━━━━━━━━━

FINDINGS
  [2] Analytics: Google Analytics, Hotjar
  [1] Social Media: Meta Pixel
  [1] Performance: Criteo
  [1] Consent Mgmt: OneTrust

TAKEAWAY
  → No direct mail vendor - potential prospect
  → No CTV vendor - potential prospect

Report saved: ./reports/nike-20260122-143022.txt

Options:
  v - View full report
  u - View 12 unknown domains (potential new vendors)
  Enter - Exit
```

## Commands

| Command | Description |
|---------|-------------|
| `mscan scan <url>` | Scan a website for martech vendors |
| `mscan list-vendors` | List all vendors in the database |
| `mscan add-vendor <name> -s <url>` | Add a new vendor by scanning a sample site |
| `mscan manage-vendors` | Rename, move, or delete vendors |
| `mscan manage-categories` | Rename or delete categories |

### Scan Options

```bash
-t, --timeout SECONDS   # Wait time per page (default: 10)
-p, --pages NUM         # Internal pages to scan beyond homepage (default: 1)
--headless              # Run browser in headless mode
-s, --system-browser    # Use system Chromium (bypasses Akamai/bot detection)
-r, --show-report       # Print full report to terminal
```

## Vendor Categories

| Category | Examples |
|----------|----------|
| Direct Mail | PebblePost, Postie, LS Direct, Postpilot |
| CTV | MNTN, Tatari, Innovid, Teads, Tvsquared |
| Social Media | Meta Pixel, TikTok, Pinterest, Snapchat, LinkedIn, X/Twitter |
| Search | Google Ads, Microsoft/Bing |
| Performance | Criteo, Taboola, Applovin |
| Analytics | Google Analytics, Amplitude, Heap, Hotjar, FullStory, Quantum Metric |
| Affiliate | CJ Affiliate, Impact, Rakuten |
| DSP | The Trade Desk, Adform |
| SSP | Pubmatic |
| CDP | Segment, Demdex |
| Email | Klaviyo, Bluecore |
| Identity | LiveRamp, LiveIntent, Tapad |
| Consent | OneTrust, Cookiebot, TrustArc |
| Other | Shopify |

## Adding New Vendors

When mscan finds unknown domains, press `u` to review them:

```
UNKNOWN DOMAINS
  #  Domain              Requests  Full Domains
  1  newtracker.io       47        cdn.newtracker.io, api.newtracker.io
  2  shop.app            23        shop.app

Add vendors? Enter numbers (e.g., 1,3,5): 1,2
```

Type an existing vendor name to append domains to it, or enter a new name to create a vendor:

```
[1/2] newtracker.io
  Name [Newtracker]: New Tracker Inc
  Category (0-9) [9]: 6
  ✓ New Tracker Inc (Analytics)

[2/2] shop.app
  Name [Shop]: Shopify
  Found existing 'Shopify'. Append domain? [Y/n]: y
  ✓ Added to Shopify (Other)

Done! Added 1 new vendor(s), appended domains to 1 existing vendor(s).
```

## Documentation

Full docs via man page:

```bash
# If installed system-wide
man mscan

# Or directly
man man/mscan.1
```

## How It Works

Unlike static HTML analyzers, mscan runs a real browser to catch:

- JavaScript-loaded tracking pixels
- Lazy-loaded analytics scripts
- Third-party requests triggered by user simulation
- Requests that only fire after page interaction

The scanner prioritizes product pages on e-commerce sites since these often have additional conversion tracking.

## License

MIT
