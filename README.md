# mscan

CLI tool to scan websites and identify their marketing technology (martech) stack by matching network requests against a vendor fingerprint database.

## Installation

```bash
# Install the package
pip install -e .

# Install Playwright browser
playwright install chromium

# Optional: Install man page
sudo cp man/mscan.1 /usr/local/share/man/man1/
```

## Usage

### Scan a website

```bash
mscan scan example.com
mscan scan https://example.com --timeout 15 --pages 5
mscan scan example.com --headless  # Use headless mode (may be blocked)
```

### List vendors in database

```bash
mscan list-vendors
mscan list-vendors --category "Analytics"
```

### Add a new vendor

```bash
mscan add-vendor "Vendor Name" -s sample-site.com
```

## Output

Scan results are saved to `./reports/` as plain text files with:
- Summary of detected vendors by category
- Full vendor table showing which vendors were detected

## Documentation

Full documentation is available via man page:

```bash
man mscan
```

Or view directly: `man man/mscan.1`
