#!/usr/bin/env python3
"""
Fetch tracker database from Ghostery TrackerDB (whotracks.me).

Downloads the latest trackerdb.json release and saves to data/whotracksme_raw.json.
"""

import json
import urllib.request
from pathlib import Path


# TrackerDB release API endpoint
RELEASES_API = "https://api.github.com/repos/ghostery/trackerdb/releases/latest"

DATA_DIR = Path(__file__).parent.parent / "data"


def get_latest_release_url() -> str:
    """Get the download URL for trackerdb.json from latest release."""
    print("Fetching latest release info...")
    
    req = urllib.request.Request(
        RELEASES_API,
        headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "mscan"}
    )
    
    with urllib.request.urlopen(req, timeout=30) as resp:
        release = json.load(resp)
    
    # Find trackerdb.json asset
    for asset in release.get("assets", []):
        if asset["name"] == "trackerdb.json":
            print(f"Found release: {release['tag_name']}")
            return asset["browser_download_url"]
    
    raise RuntimeError("trackerdb.json not found in latest release")


def download_trackerdb(url: str) -> dict:
    """Download trackerdb.json from the given URL."""
    print(f"Downloading trackerdb.json...")
    
    req = urllib.request.Request(url, headers={"User-Agent": "mscan"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    
    return data


def main():
    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Get latest release URL
    url = get_latest_release_url()
    
    # Download the data
    data = download_trackerdb(url)
    
    # Save raw data
    output_path = DATA_DIR / "whotracksme_raw.json"
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    
    # Print stats
    patterns = data.get("patterns", {})
    domains = data.get("domains", {})
    categories = data.get("categories", {})
    
    print(f"\nSaved to: {output_path}")
    print(f"  Patterns: {len(patterns)}")
    print(f"  Domains: {len(domains)}")
    print(f"  Categories: {list(categories.keys())}")


if __name__ == "__main__":
    main()
