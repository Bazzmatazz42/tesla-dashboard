"""
Tesla IR Downloader
Downloads all remaining IR documents not covered by sec_downloader.py:

  1. Earnings press releases (EX-99.1 from 8-Ks with item 2.02)
        → company_docs/earnings_releases/TSLA-Q{Q}-{YYYY}-Earnings-Release.htm

  2. Delivery / Reg FD reports (8-Ks with item 7.01 only)
        → company_docs/others/TSLA-DELIVERY-{DATE}.htm

  3. Press releases / Other Events (8-Ks with item 8.01)
        → company_docs/others/TSLA-PR-{DATE}.htm

  4. Material agreements / notable events (8-Ks with item 1.01, 2.03 etc.)
        → company_docs/others/TSLA-8K-{DATE}.htm

  5. Tesla Impact Reports (direct download from tesla.com)
        → company_docs/others/TSLA-Impact-Report-{YEAR}.pdf

Safe to re-run — skips files already downloaded.
"""

import requests
import time
from pathlib import Path
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

TESLA_CIK     = "1318605"
EDGAR_BASE    = "https://www.sec.gov"
SUBMISSIONS   = "https://data.sec.gov/submissions/CIK0001318605.json"

SCRIPT_DIR    = Path(__file__).parent
BASE          = SCRIPT_DIR.parent / "company_docs"
EARNINGS_DIR  = BASE / "earnings_releases"
OTHERS_DIR    = BASE / "others"

HEADERS = {
    "User-Agent": "Tesla Dashboard personal-research saumi.personal@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

REQUEST_DELAY = 0.15  # EDGAR rate limit: stay under 10 req/sec

# 8-K items we want to download exhibits from
# Governance-only items (5.02, 5.03, 5.07, 5.08) have no useful exhibits — skip
SKIP_ONLY_ITEMS = {"5.02", "5.03", "5.07", "5.08"}

# Tesla Impact Report direct URLs (newest → oldest)
IMPACT_REPORTS = [
    ("2024", "https://www.tesla.com/ns_videos/2024-tesla-impact-report.pdf"),
    ("2023", "https://www.tesla.com/ns_videos/2023-tesla-impact-report.pdf"),
    ("2022", "https://www.tesla.com/ns_videos/2022-tesla-impact-report.pdf"),
    ("2021", "https://www.tesla.com/ns_videos/2021-tesla-impact-report.pdf"),
    ("2020", "https://www.tesla.com/ns_videos/2020-tesla-impact-report.pdf"),
    ("2019", "https://www.tesla.com/ns_videos/tesla_2019_impact_report.pdf"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def get(url: str, stream: bool = False) -> requests.Response:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, stream=stream, timeout=30)
            r.raise_for_status()
            time.sleep(REQUEST_DELAY)
            return r
        except requests.RequestException as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def already_exists(directory: Path, base: str) -> bool:
    return bool(list(directory.glob(f"{base}.*")))


def download_file(url: str, dest: Path) -> bool:
    try:
        r = get(url, stream=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
        size_kb = dest.stat().st_size // 1024
        print(f"  Saved: {dest.name} ({size_kb} KB)")
        return True
    except Exception as e:
        print(f"  Failed: {e}")
        if dest.exists():
            dest.unlink()
        return False


def get_quarter_label(report_date: str) -> str:
    """'2025-09-30' → 'Q3-2025'"""
    try:
        year, month, _ = report_date.split("-")
        q = (int(month) - 1) // 3 + 1
        return f"Q{q}-{year}"
    except Exception:
        return None


def items_are_governance_only(items_str: str) -> bool:
    """Return True if this 8-K only covers governance items with no useful exhibits."""
    parts = set(items_str.split(","))
    return parts.issubset(SKIP_ONLY_ITEMS)


# ── EDGAR: collect all 8-K filings ───────────────────────────────────────────

def collect_8k_filings() -> list[dict]:
    print("Fetching Tesla submissions index...")
    data = get(SUBMISSIONS).json()
    filings = []

    def extract(block: dict):
        forms       = block.get("form", [])
        dates       = block.get("filingDate", [])
        report_dates= block.get("reportDate", [])
        accnos      = block.get("accessionNumber", [])
        items_list  = block.get("items", [""] * len(forms))

        for form, date, rdate, acc, items in zip(forms, dates, report_dates, accnos, items_list):
            if form == "8-K":
                filings.append({
                    "date":        date,
                    "report_date": rdate,
                    "accession":   acc.replace("-", ""),
                    "accession_orig": acc,
                    "items":       items or "",
                })

    extract(data.get("filings", {}).get("recent", {}))
    for extra in data.get("filings", {}).get("files", []):
        url = f"https://data.sec.gov/submissions/{extra['name']}"
        print(f"  Fetching older filings: {extra['name']}")
        try:
            extract(get(url).json())
        except Exception as e:
            print(f"  Warning: {e}")

    print(f"Found {len(filings)} total 8-K filings.")
    return filings


# ── EDGAR: get EX-99.x exhibit URLs from a filing index ──────────────────────

def get_exhibit_urls(accession_nd: str, accession_orig: str) -> list[tuple[str, str]]:
    """
    Fetch the filing index HTML and return list of (exhibit_type, full_url) tuples
    for all EX-99.x documents.
    """
    url = (f"{EDGAR_BASE}/Archives/edgar/data/{TESLA_CIK}/"
           f"{accession_nd}/{accession_orig}-index.htm")
    try:
        r = get(url)
    except Exception as e:
        print(f"  Index fetch failed: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    exhibits = []

    for row in soup.select("table tr"):
        cols = row.find_all("td")
        if len(cols) < 4:
            continue
        ex_type = cols[3].get_text(strip=True)   # e.g. "EX-99.1"
        if not ex_type.startswith("EX-99"):
            continue
        link = cols[2].find("a")
        if not link:
            continue
        href = link.get("href", "")
        if href:
            full_url = (EDGAR_BASE + href) if href.startswith("/") else href
            exhibits.append((ex_type, full_url))

    return exhibits


# ── Categorise a filing and determine output path ─────────────────────────────

def categorise(filing: dict) -> tuple[Path, str] | None:
    """
    Returns (output_directory, base_filename) or None if we should skip.
    """
    items = filing["items"]
    date  = filing["date"]

    if items_are_governance_only(items):
        return None

    # Earnings release (item 2.02 present)
    if "2.02" in items:
        label = get_quarter_label(filing.get("report_date", ""))
        if label:
            base = f"TSLA-{label}-Earnings-Release"
        else:
            base = f"TSLA-EARNINGS-{date}"
        return (EARNINGS_DIR, base)

    # Delivery / Reg FD report (item 7.01, no 2.02)
    if "7.01" in items:
        return (OTHERS_DIR, f"TSLA-DELIVERY-{date}")

    # Press release / Other Events (item 8.01)
    if "8.01" in items:
        return (OTHERS_DIR, f"TSLA-PR-{date}")

    # Material agreement, financing, other notable events
    return (OTHERS_DIR, f"TSLA-8K-{date}")


# ── Part 1: Download 8-K exhibits ────────────────────────────────────────────

def download_8k_exhibits():
    filings = collect_8k_filings()
    downloaded = skipped = failed = no_exhibit = 0

    for i, filing in enumerate(filings, 1):
        result = categorise(filing)
        if result is None:
            skipped += 1
            continue

        out_dir, base = result

        if already_exists(out_dir, base):
            skipped += 1
            continue

        print(f"[{i}/{len(filings)}] {filing['date']}  items={filing['items']}  → {base}")

        exhibits = get_exhibit_urls(filing["accession"], filing["accession_orig"])
        if not exhibits:
            print(f"  No EX-99 exhibits found.")
            no_exhibit += 1
            continue

        # Download the first EX-99.1 (primary press release exhibit)
        ex_type, ex_url = exhibits[0]
        ext = Path(ex_url).suffix.lower() or ".htm"
        dest = out_dir / f"{base}{ext}"
        if download_file(ex_url, dest):
            downloaded += 1
        else:
            failed += 1

    print(f"\n8-K exhibits — Downloaded: {downloaded} | Skipped: {skipped} | "
          f"No exhibit: {no_exhibit} | Failed: {failed}")


# ── Part 2: Download Tesla Impact Reports ────────────────────────────────────

def download_impact_reports():
    print("\n--- Tesla Impact Reports ---")
    OTHERS_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = skipped = failed = 0

    for year, url in IMPACT_REPORTS:
        base = f"TSLA-Impact-Report-{year}"
        if already_exists(OTHERS_DIR, base):
            print(f"  {base} — already exists, skipping.")
            skipped += 1
            continue
        print(f"  {base}...")
        dest = OTHERS_DIR / f"{base}.pdf"
        try:
            if download_file(url, dest):
                downloaded += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  {year}: {e}")
            failed += 1

    print(f"Impact Reports — Downloaded: {downloaded} | Skipped: {skipped} | Failed: {failed}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    EARNINGS_DIR.mkdir(parents=True, exist_ok=True)
    OTHERS_DIR.mkdir(parents=True, exist_ok=True)

    download_8k_exhibits()
    download_impact_reports()

    print("\nAll done.")
    print(f"  Earnings releases → {EARNINGS_DIR}")
    print(f"  Press releases / other → {OTHERS_DIR}")


if __name__ == "__main__":
    main()
