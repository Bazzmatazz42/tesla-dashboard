"""
Tesla Delivery & Production Extractor
Pulls quarterly vehicle delivery and production data from Tesla's 8-K filings on EDGAR.
Tesla files a delivery/production press release (EX-99.1) via 8-K Item 7.01 each quarter.

Writes to tesla-dashboard/data.js  (updates window.TSLA.deliveries and .production arrays)
"""

import requests
import json
import re
import time
from pathlib import Path
from bs4 import BeautifulSoup
from datetime import date

HEADERS  = {"User-Agent": "Tesla Dashboard personal-research saumi.personal@gmail.com"}
CIK      = "1318605"
SCRIPT_DIR = Path(__file__).parent
DATA_JS    = SCRIPT_DIR.parent / "data.js"

SUBS_URLS = [
    "https://data.sec.gov/submissions/CIK0001318605.json",
    "https://data.sec.gov/submissions/CIK0001318605-submissions-001.json",
]

# ── Quarter inference from filing date ────────────────────────────────────────

def infer_quarter(filing_date: str) -> str | None:
    """
    Tesla files delivery 8-Ks in early Jan/Apr/Jul/Oct.
    Map filing month → quarter reported.
    """
    try:
        d = date.fromisoformat(filing_date)
    except ValueError:
        return None

    # Jan = Q4 of prior year, Apr = Q1, Jul = Q2, Oct = Q3
    # Allow a window: Jan(1-20)=Q4prev, Feb–Mar=Q4 or Q1 special,
    # Mar-Apr(1-15)=Q1, Jun-Jul(1-15)=Q2, Sep-Oct(1-15)=Q3
    m, day, y = d.month, d.day, d.year
    if m == 1 and day <= 20:
        return f"Q4-{y-1}"
    if m in (3, 4) and day <= 20:
        return f"Q1-{y}"
    if m in (6, 7) and day <= 15:
        return f"Q2-{y}"
    if m in (9, 10) and day <= 15:
        return f"Q3-{y}"
    if m == 2 and day <= 28:
        return f"Q4-{y-1}"  # rare late Q4 filing
    return None

# ── Collect all delivery 8-K filings ─────────────────────────────────────────

def collect_delivery_filings() -> list[dict]:
    filings = []
    for url in SUBS_URLS:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()

        # Older page has flat structure; main page has data['filings']['recent']
        if "filings" in data:
            raw = data["filings"]["recent"]
        else:
            raw = data

        forms    = raw["form"]
        dates    = raw["filingDate"]
        items    = raw.get("items", [""] * len(forms))
        accnums  = raw["accessionNumber"]

        for i, form in enumerate(forms):
            if form != "8-K":
                continue
            item_str = str(items[i])
            d = dates[i]
            # Tesla used 7.01 for delivery reports until 2022
            # From 2023+ they switched to 2.02, filed in first 10 days of Jan/Apr/Jul/Oct
            is_delivery = False
            if "7.01" in item_str:
                is_delivery = True
            elif "2.02" in item_str and "7.01" not in item_str:
                # Early-month filing = delivery report; mid/late-month = earnings report
                try:
                    day = int(d.split("-")[2])
                    month = int(d.split("-")[1])
                    if month in (1, 4, 7, 10) and day <= 12:
                        is_delivery = True
                except (ValueError, IndexError):
                    pass

            if is_delivery:
                q = infer_quarter(d)
                if q:
                    filings.append({
                        "quarter":  q,
                        "date":     d,
                        "acc":      accnums[i],
                    })

    # Deduplicate by quarter (keep most recent filing for that quarter)
    by_q = {}
    for f in filings:
        q = f["quarter"]
        if q not in by_q or f["date"] > by_q[q]["date"]:
            by_q[q] = f

    result = sorted(by_q.values(), key=lambda x: x["quarter"], reverse=True)
    print(f"  Found {len(result)} unique delivery quarters from EDGAR")
    return result

# ── Fetch EX-99.1 exhibit for a filing ───────────────────────────────────────

def fetch_exhibit(acc: str) -> str | None:
    """Fetch the EX-99.1 HTML text from a given accession number."""
    acc_fmt = acc.replace("-", "")
    base    = f"https://www.sec.gov/Archives/edgar/data/{CIK}/{acc_fmt}"

    # Get filing index to find exhibit filename
    # Index filename uses the original acc with dashes, e.g. 0001564590-22-033053-index.html
    exhibit_url = None
    for idx_suffix in [f"{acc}-index.html", f"{acc_fmt}-index.html", "index.htm"]:
        try:
            r = requests.get(f"{base}/{idx_suffix}", headers=HEADERS, timeout=20)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a"):
                    href = a.get("href", "")
                    fname = href.split("/")[-1].lower()
                    # Match both old (tsla-ex991_6.htm) and new (exhibit9911.htm) naming
                    if (re.search(r"ex.?99", fname) or "exhibit99" in fname) and fname.endswith(".htm"):
                        exhibit_url = f"https://www.sec.gov{href}" if href.startswith("/") else f"{base}/{fname}"
                        break
            if exhibit_url:
                break
        except Exception:
            continue

    if not exhibit_url:
        return None

    try:
        r = requests.get(exhibit_url, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None

# ── Parse delivery/production numbers from exhibit HTML ───────────────────────

def parse_numbers(html: str) -> dict:
    """
    Returns dict with keys:
      total_delivered, total_produced,
      mx_delivered, mx_produced,
      my3_delivered, my3_produced,
      cybertruck_delivered, cybertruck_produced,
      other_delivered, other_produced
    All values are integers or None.
    """
    soup = BeautifulSoup(html, "html.parser")

    result = {
        "total_delivered":       None,
        "total_produced":        None,
        "mx_delivered":          None,
        "mx_produced":           None,
        "my3_delivered":         None,
        "my3_produced":          None,
        "cybertruck_delivered":  None,
        "cybertruck_produced":   None,
        "other_delivered":       None,
        "other_produced":        None,
        "energy_deployed_gwh":   None,
    }

    def to_int(s: str) -> int | None:
        # Strip everything except digits; handles split numbers like "258,5 8 0"
        digits = re.sub(r"[^\d]", "", str(s))
        try:
            return int(digits) if digits else None
        except ValueError:
            return None

    def cell_text(cell) -> str:
        """Concatenate all text in a cell, stripping whitespace."""
        return "".join(cell.stripped_strings)

    # ── Strategy 1: HTML table parsing (handles split numbers) ────────────────
    # Find tables that contain production/delivery data
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            label = cell_text(cells[0]).strip()

            # Need at least 3 cells: label, production, deliveries
            if len(cells) < 3:
                continue

            # Get first two numeric cells after the label
            nums = []
            for cell in cells[1:]:
                t = re.sub(r"[^\d]", "", cell_text(cell))
                if t and len(t) >= 4:  # at least 4 digits = ≥1000
                    nums.append(int(t))
                if len(nums) == 2:
                    break

            if len(nums) < 2:
                continue

            prod, deliv = nums[0], nums[1]

            if re.search(r"Model S/?X", label, re.IGNORECASE):
                result["mx_produced"]  = prod
                result["mx_delivered"] = deliv
            elif re.search(r"Model [3Y]/?[3Y]", label, re.IGNORECASE):
                result["my3_produced"]  = prod
                result["my3_delivered"] = deliv
            elif re.search(r"Cybertruck", label, re.IGNORECASE):
                result["cybertruck_produced"]  = prod
                result["cybertruck_delivered"] = deliv
            elif re.search(r"Other Models?", label, re.IGNORECASE):
                result["other_produced"]  = prod
                result["other_delivered"] = deliv
            elif re.search(r"^\s*Total\s*$", label, re.IGNORECASE):
                result["total_produced"]  = prod
                result["total_delivered"] = deliv

    # Validate: total should be plausible (>= 1000)
    for k in list(result):
        v = result[k]
        if v is not None and v < 100:
            result[k] = None  # reject obviously wrong values

    # ── Strategy 2: narrative text fallback ───────────────────────────────────
    text = soup.get_text(" ", strip=True)

    if result["total_delivered"] is None:
        # "produced X vehicles and delivered Y vehicles"
        m = re.search(
            r"produced\s+(?:over\s+|approximately\s+)?([\d,]+)\s+(?:total\s+)?vehicles\s+and\s+delivered\s+(?:over\s+|approximately\s+)?([\d,]+)",
            text, re.IGNORECASE)
        if m:
            result["total_produced"]  = to_int(m.group(1))
            result["total_delivered"] = to_int(m.group(2))

    if result["total_delivered"] is None:
        m = re.search(r"delivered\s+(?:over\s+|approximately\s+)?([\d,]+)\s+(?:new\s+|total\s+)?vehicles", text, re.IGNORECASE)
        if m:
            result["total_delivered"] = to_int(m.group(1))

    if result["total_produced"] is None:
        m = re.search(r"produced\s+(?:over\s+|approximately\s+)?([\d,]+)\s+(?:total\s+)?vehicles", text, re.IGNORECASE)
        if m:
            result["total_produced"] = to_int(m.group(1))

    # Narrative model breakdown e.g. "50,900 Model 3 and 12,100 Model S and X"
    if result["my3_delivered"] is None:
        m = re.search(r"([\d,]+)\s+Model 3\b", text, re.IGNORECASE)
        if m:
            v = to_int(m.group(1))
            if v and v >= 1000:
                result["my3_delivered"] = v
    if result["mx_delivered"] is None:
        m = re.search(r"([\d,]+)\s+Model S\b", text, re.IGNORECASE)
        if m:
            v = to_int(m.group(1))
            if v and v >= 100:
                result["mx_delivered"] = v

    # Derive total from model breakdown if still missing
    if result["total_delivered"] is None:
        parts = [result["mx_delivered"], result["my3_delivered"],
                 result["cybertruck_delivered"], result["other_delivered"]]
        if any(v is not None for v in parts):
            result["total_delivered"] = sum(v for v in parts if v is not None)

    # ── Energy storage GWh ────────────────────────────────────────────────────
    m = re.search(r"deployed\s+([\d.]+)\s*GWh", text, re.IGNORECASE)
    if m:
        try:
            result["energy_deployed_gwh"] = float(m.group(1))
        except ValueError:
            pass

    return result

# ── Main ──────────────────────────────────────────────────────────────────────

def extract_all() -> list[dict]:
    print("Collecting Tesla delivery 8-K filings from EDGAR...")
    filings = collect_delivery_filings()

    records = []
    for f in filings:
        q   = f["quarter"]
        acc = f["acc"]
        print(f"  {q}  ({f['date']})  acc={acc}", end="  ")

        html = fetch_exhibit(acc)
        if not html:
            print("SKIP (no exhibit found)")
            continue

        nums = parse_numbers(html)

        if nums["total_delivered"] is None and nums["total_produced"] is None:
            print("SKIP (no numbers parsed)")
            continue

        # Q4 press releases report full-year totals; flag for later derivation
        is_q4 = q.startswith("Q4-")
        record = {
            "quarter":             q,
            "date":                f["date"],
            "total_delivered":     nums["total_delivered"],
            "total_produced":      nums["total_produced"],
            "mx_delivered":        nums["mx_delivered"],
            "mx_produced":         nums["mx_produced"],
            "my3_delivered":       nums["my3_delivered"],
            "my3_produced":        nums["my3_produced"],
            "cybertruck_delivered": nums["cybertruck_delivered"],
            "cybertruck_produced":  nums["cybertruck_produced"],
            "other_delivered":     nums["other_delivered"],
            "other_produced":      nums["other_produced"],
            "energy_deployed_gwh": nums["energy_deployed_gwh"],
            "is_annual_total":     is_q4,  # Q4 reports give FY totals; app derives Q4 standalone
        }
        records.append(record)

        total_d = nums["total_delivered"]
        total_p = nums["total_produced"]
        print(f"delivered={total_d:,}  produced={total_p:,}" if total_d and total_p
              else f"delivered={total_d}  produced={total_p}")

        time.sleep(0.15)  # EDGAR rate limit courtesy

    return records

# ── Write to data.js ──────────────────────────────────────────────────────────

def update_data_js(records: list):
    text = DATA_JS.read_text(encoding="utf-8")

    # Replace deliveries array
    json_str = json.dumps(records, indent=4)
    new_block = f"  deliveries: {json_str},"

    pattern = r"(  deliveries:\s*\[).*?(\],)"
    new_text = re.sub(pattern, new_block, text, flags=re.DOTALL, count=1)

    if new_text == text:
        print("  WARNING: could not locate deliveries array in data.js")
        out = SCRIPT_DIR.parent / "extracted_deliveries.json"
        out.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"  Written to: {out}")
        return

    DATA_JS.write_text(new_text, encoding="utf-8")
    print(f"\n  data.js updated — {len(records)} quarterly delivery records written.")

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    records = extract_all()

    if not records:
        print("No records extracted.")
        return

    print(f"\nSample (newest 6):")
    for r in records[:6]:
        print(f"  {r['quarter']:<8}  delivered={r['total_delivered']:>7,}  produced={r['total_produced']:>7,}"
              if r['total_delivered'] and r['total_produced']
              else f"  {r['quarter']:<8}  delivered={r['total_delivered']}  produced={r['total_produced']}")

    update_data_js(records)
    print("Done.")


if __name__ == "__main__":
    main()
