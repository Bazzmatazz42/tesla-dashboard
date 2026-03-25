"""
Tesla SEC Filing Downloader
Pulls all 10-K, 10-Q, 8-K, and DEF 14A filings from SEC EDGAR for Tesla (CIK: 0001318605).
Saves to: company_docs/sec_filings/
Naming convention:
  10-K      → TSLA-10-K-{YEAR}.pdf/.htm
  10-Q      → TSLA-10-Q-{DATE}.pdf/.htm
  8-K       → TSLA-8-K-{DATE}.pdf/.htm
  DEF 14A   → TSLA-DEF14A-{YEAR}.pdf/.htm
Safe to re-run — skips files already downloaded.
"""

import os
import time
import requests
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

TESLA_CIK     = "0001318605"
TESLA_CIK_INT = "1318605"
FORMS_TO_FETCH = {"10-K", "10-Q", "8-K", "DEF 14A"}

SCRIPT_DIR = Path(__file__).parent
OUT_DIR    = SCRIPT_DIR.parent / "company_docs" / "sec_filings"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# EDGAR requires a descriptive User-Agent with contact info
HEADERS = {
    "User-Agent": "Tesla Dashboard personal-research saumi.personal@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

EDGAR_BASE       = "https://www.sec.gov"
SUBMISSIONS_URL  = f"https://data.sec.gov/submissions/CIK{TESLA_CIK}.json"
REQUEST_DELAY    = 0.15   # stay well under EDGAR's 10 req/sec limit


# ── Helpers ───────────────────────────────────────────────────────────────────

def get(url: str, stream: bool = False) -> requests.Response:
    """GET with rate limiting and 3-attempt retry."""
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, stream=stream, timeout=30)
            r.raise_for_status()
            time.sleep(REQUEST_DELAY)
            return r
        except requests.RequestException as e:
            if attempt == 2:
                raise
            wait = 2 ** attempt
            print(f"  Retry {attempt+1}/3 ({wait}s): {e}")
            time.sleep(wait)


def output_filename(form: str, date: str) -> str:
    """
    Build a base filename (no extension) from form type and filing date.
      10-K  / DEF 14A  → use year only   (one per year)
      10-Q  / 8-K      → use full date   (multiple per year)
    """
    slug = form.replace(" ", "")
    if form in ("10-K", "DEF 14A"):
        return f"TSLA-{slug}-{date[:4]}"
    else:
        return f"TSLA-{slug}-{date}"


def already_downloaded(base: str) -> bool:
    """Return True if any file matching base.* exists in OUT_DIR."""
    return bool(list(OUT_DIR.glob(f"{base}.*")))


def download(url: str, dest: Path) -> bool:
    """Stream-download url to dest; deletes partial file on failure."""
    try:
        r = get(url, stream=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"  Download failed: {e}")
        if dest.exists():
            dest.unlink()
        return False


# ── Collect filing metadata ───────────────────────────────────────────────────

def collect_filings() -> list[dict]:
    """
    Walk the EDGAR submissions JSON (including paginated older-filings files).
    Returns a list of dicts: {form, date, accession, primary_doc}
    primary_doc is the filename of the primary document (e.g. tsla-20241231.htm)
    — this comes directly from the submissions JSON, no extra requests needed.
    """
    print(f"Fetching Tesla submissions index from EDGAR...")
    data = get(SUBMISSIONS_URL).json()

    filings = []

    def extract(block: dict):
        forms    = block.get("form", [])
        dates    = block.get("filingDate", [])
        accnos   = block.get("accessionNumber", [])
        prim_doc = block.get("primaryDocument", [])

        for form, date, acc, doc in zip(forms, dates, accnos, prim_doc):
            if form in FORMS_TO_FETCH and doc:
                filings.append({
                    "form":        form,
                    "date":        date,
                    "accession":   acc.replace("-", ""),
                    "primary_doc": doc,
                })

    extract(data.get("filings", {}).get("recent", {}))

    # Paginated older filings
    for extra in data.get("filings", {}).get("files", []):
        url = f"https://data.sec.gov/submissions/{extra['name']}"
        print(f"  Fetching older-filings page: {extra['name']}")
        try:
            extract(get(url).json())
        except Exception as e:
            print(f"  Warning — could not fetch {url}: {e}")

    return filings


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    filings = collect_filings()

    from collections import Counter
    counts = Counter(f["form"] for f in filings)
    print(f"\nFiling counts: {dict(sorted(counts.items()))}")
    print(f"Total to process: {len(filings)}\n")

    downloaded = skipped = failed = 0

    for i, f in enumerate(filings, 1):
        base = output_filename(f["form"], f["date"])

        if already_downloaded(base):
            skipped += 1
            continue

        # Build direct URL — no index fetch needed
        doc_url = f"{EDGAR_BASE}/Archives/edgar/data/{TESLA_CIK_INT}/{f['accession']}/{f['primary_doc']}"
        ext     = Path(f["primary_doc"]).suffix.lower() or ".htm"
        dest    = OUT_DIR / f"{base}{ext}"

        print(f"[{i}/{len(filings)}] {f['form']} {f['date']}  →  {dest.name}")

        if download(doc_url, dest):
            size_kb = dest.stat().st_size // 1024
            print(f"  OK ({size_kb} KB)")
            downloaded += 1
        else:
            failed += 1

    print(f"\nDone.")
    print(f"  Downloaded : {downloaded}")
    print(f"  Skipped    : {skipped}  (already existed)")
    print(f"  Failed     : {failed}")
    print(f"  Saved to   : {OUT_DIR}")


if __name__ == "__main__":
    main()
