"""
Tesla Segment Revenue & COGS Extractor
Parses ALL 10-Q and 10-K HTML filings from 2010 to present.

Three historical eras:
  2010-2014: "Automotive sales" + "Development services"
  2015-2016: "Automotive" + "Services and other" (no energy line yet)
  2017+:     Full modern breakdown (auto sales/leasing/credits, energy, services)

Q4 is derived: FY (from 10-K col 1) minus 9M YTD (from Q3 10-Q col 3).

Writes to tesla-dashboard/data.js (updates window.TSLA.segments array).
"""

import re
import json
from pathlib import Path
from bs4 import BeautifulSoup

SCRIPT_DIR  = Path(__file__).parent
FILINGS_DIR = SCRIPT_DIR.parent / "company_docs" / "sec_filings"
DATA_JS     = SCRIPT_DIR.parent / "data.js"

# ── Quarter mapping ────────────────────────────────────────────────────────────

def filename_to_quarter(fname: str) -> tuple[str, str] | None:
    fname = fname.lower()

    # 10-Q: TSLA-10-Q-YYYY-MM-DD.htm  →  filing month determines quarter
    m = re.match(r"tsla-10-q-(\d{4})-(\d{2})-\d{2}", fname)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if mo in (4, 5):   return f"Q1-{y}", f"{y}-03-31"
        if mo in (7, 8):   return f"Q2-{y}", f"{y}-06-30"
        if mo in (10, 11): return f"Q3-{y}", f"{y}-09-30"
        return None

    # 10-K: TSLA-10-K-YYYY.htm  →  filename year = filing year, FY = year - 1
    # e.g. TSLA-10-K-2025.htm filed Feb 2025 → covers FY2024
    m = re.match(r"tsla-10-k-(\d{4})", fname)
    if m:
        fy = int(m.group(1)) - 1
        return f"FY-{fy}", f"{fy}-12-31"

    return None

# ── Unit detection ─────────────────────────────────────────────────────────────

def detect_unit_multiplier(soup: BeautifulSoup) -> int:
    """Returns 1_000_000 (millions) or 1_000 (thousands)."""
    text = soup.get_text(" ")
    # Use \b to avoid matching "contain millions / thousands of parts"
    if re.search(r"\bin\s+millions", text, re.I):
        return 1_000_000
    if re.search(r"\bin\s+thousands", text, re.I):
        return 1_000
    return 1_000_000

# ── Income statement parser ────────────────────────────────────────────────────

# Revenue-only keys: skip if we're in the COGS section
_REV_ONLY  = {"automotive_sales_rev", "_auto_era_rev", "_dev_svc_rev"}
# COGS-only keys: skip if we're NOT in the COGS section
_COGS_ONLY = {"automotive_sales_cogs", "energy_cogs", "services_cogs",
              "_auto_era_cogs", "_dev_svc_cogs"}

TARGET_ROWS = {
    # ── Revenue (modern 2017+) ────────────────────────────────────────────────
    "automotive_sales_rev":   re.compile(r"automotive\s+sales", re.I),
    "automotive_credits_rev": re.compile(r"automotive\s+regulatory\s+credits", re.I),
    "automotive_leasing_rev": re.compile(r"automotive\s+leasing", re.I),
    "total_automotive_rev":   re.compile(r"total\s+automotive\s+revenues?", re.I),
    "energy_rev":             re.compile(r"energy\s+generation\s+and\s+storage", re.I),
    "services_rev":           re.compile(r"services\s+and\s+other", re.I),
    "total_revenues":         re.compile(r"^total\s+revenues?$", re.I),
    # ── Revenue (era aliases) ─────────────────────────────────────────────────
    "_auto_era_rev":          re.compile(r"^automotive$", re.I),             # 2015-2016
    "_dev_svc_rev":           re.compile(r"^development\s+services$", re.I), # 2010-2014
    # ── COGS (modern 2017+) ───────────────────────────────────────────────────
    "automotive_sales_cogs":  re.compile(r"automotive\s+sales$", re.I),
    "total_automotive_cogs":  re.compile(r"total\s+automotive\s+cost", re.I),
    "energy_cogs":            re.compile(r"energy\s+generation\s+and\s+storage$", re.I),
    "services_cogs":          re.compile(r"services\s+and\s+other$", re.I),
    "total_cogs":             re.compile(r"total\s+cost\s+of\s+revenues?", re.I),
    # ── COGS (era aliases) ────────────────────────────────────────────────────
    "_auto_era_cogs":         re.compile(r"^automotive$", re.I),             # 2015-2016
    "_dev_svc_cogs":          re.compile(r"^development\s+services$", re.I), # 2010-2014
    # ── P&L ──────────────────────────────────────────────────────────────────
    "gross_profit":           re.compile(r"^(?:total\s+)?gross\s+profit(?:\s*\(loss\))?$", re.I),
    "r_and_d":                re.compile(r"research\s+and\s+development", re.I),
    "sga":                    re.compile(r"selling,?\s+general\s+and\s+admin", re.I),
    "op_income":              re.compile(r"(?:income|loss)\s+from\s+operations", re.I),
    "net_income":             re.compile(r"net\s+(?:income|loss)\s+attributable\s+to\s+common", re.I),
}


def parse_income_statement(soup: BeautifulSoup, target_col: int = 1) -> dict | None:
    """
    Finds the full income statement table (must have revenues AND cost of revenues).
    target_col: 1 = first data column (Q standalone / FY current)
                3 = Nine Months YTD (Q3 10-Q only)
    Returns a raw dict of matched fields, or None if table not found.
    """
    unit = detect_unit_multiplier(soup)

    for table in soup.find_all("table"):
        if len(table.find_all("tr")) < 5:
            continue
        full_text = table.get_text(" ")
        if not re.search(r"total\s+revenues?", full_text, re.I):
            continue
        if not re.search(r"automotive", full_text, re.I):
            continue
        if not re.search(r"cost\s+of\s+revenues?", full_text, re.I):
            continue  # skip segment-revenue-only tables (seen in 10-K)

        def extract_val(cells):
            # Require at least one digit — excludes lone ")" cells from split parens
            numeric = [
                c for c in cells[1:]
                if re.search(r"\d", c.get_text(strip=True))
            ]
            if target_col - 1 < len(numeric):
                raw = numeric[target_col - 1].get_text(strip=True)
                raw = raw.replace("(", "-").replace(")", "")
                raw = re.sub(r"[^\d.\-]", "", raw)
                try:
                    return int(float(raw) * unit) if raw and raw != "-" else None
                except ValueError:
                    return None
            return None

        result = {}
        in_cogs = False

        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            label = re.sub(r"\s+", " ", cells[0].get_text(" ", strip=True))

            if re.search(r"cost\s+of\s+revenues?", label, re.I):
                in_cogs = True

            for key, pattern in TARGET_ROWS.items():
                if not pattern.search(label):
                    continue
                if key in _REV_ONLY and in_cogs:
                    continue
                if key in _COGS_ONLY and not in_cogs:
                    continue
                val = extract_val(cells)
                if val is not None and key not in result:
                    result[key] = val

        if not result.get("total_revenues"):
            continue

        # Apply era aliases: map pre-2017 labels to canonical field names
        # 2015-2016: "Automotive" → total_automotive_rev/cogs
        if result.get("total_automotive_rev") is None:
            result["total_automotive_rev"] = result.get("_auto_era_rev")
        if result.get("total_automotive_cogs") is None:
            result["total_automotive_cogs"] = result.get("_auto_era_cogs")
        # 2010-2014: "Automotive sales" (no total line) → use as total_automotive_rev
        if result.get("total_automotive_rev") is None:
            result["total_automotive_rev"] = result.get("automotive_sales_rev")
        if result.get("total_automotive_cogs") is None:
            result["total_automotive_cogs"] = result.get("automotive_sales_cogs")
        # 2010-2014: "Development services" → services_rev/cogs
        if result.get("services_rev") is None:
            result["services_rev"] = result.get("_dev_svc_rev")
        if result.get("services_cogs") is None:
            result["services_cogs"] = result.get("_dev_svc_cogs")

        return result

    return None

# ── Record builder ─────────────────────────────────────────────────────────────

_FIELDS = [
    "automotive_sales_rev", "automotive_credits_rev", "automotive_leasing_rev",
    "total_automotive_rev", "energy_rev", "services_rev", "total_revenues",
    "automotive_sales_cogs", "total_automotive_cogs", "energy_cogs",
    "services_cogs", "total_cogs",
    "gross_profit", "r_and_d", "sga", "op_income", "net_income",
]


def _parse_filing(fpath: Path, quarter_label: str, period_end: str, col: int) -> dict | None:
    try:
        html = fpath.read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        print(f"READ ERROR: {e}")
        return None

    data = parse_income_statement(soup, target_col=col)
    if not data:
        return None

    rec = {
        "quarter":    quarter_label,
        "period_end": period_end,
        "source":     "10-Q" if "10-Q" in fpath.name else "10-K",
    }
    for f in _FIELDS:
        rec[f] = data.get(f)
    return rec


def _subtract_records(fy: dict, ytd9m: dict, year: int) -> dict:
    """Derive Q4 = FY - 9M YTD for every numeric field."""
    rec = {
        "quarter":    f"Q4-{year}",
        "period_end": f"{year}-12-31",
        "source":     "derived (10-K minus 9M)",
    }
    for f in _FIELDS:
        a, b = fy.get(f), ytd9m.get(f)
        rec[f] = (a - b) if (a is not None and b is not None) else None
    return rec

# ── Main extraction ────────────────────────────────────────────────────────────

def extract_all() -> list[dict]:
    records     = []
    seen        = set()
    ytd9m_by_year = {}
    fy_by_year    = {}

    # ── Step 1: Q1 / Q2 / Q3 from all 10-Qs ──────────────────────────────────
    for fpath in sorted(FILINGS_DIR.glob("TSLA-10-Q-*.htm")):
        mapping = filename_to_quarter(fpath.name)
        if not mapping:
            continue
        quarter_label, period_end = mapping
        filing_month = int(fpath.name.split("-")[4])

        if quarter_label not in seen:
            print(f"  {quarter_label}  ({fpath.name})", end="  ")
            rec = _parse_filing(fpath, quarter_label, period_end, col=1)
            if rec:
                rev = rec.get("total_revenues")
                gp  = rec.get("gross_profit")
                print(f"rev=${rev/1e6:.0f}M  gp=${gp/1e6:.0f}M" if rev and gp else f"rev={rev}")
                records.append(rec)
                seen.add(quarter_label)
            else:
                print("SKIP (table not found)")

        # Q3 10-Q → also extract Nine Months YTD (col 3) for Q4 derivation
        if filing_month in (10, 11):
            year = int(quarter_label.split("-")[1])
            if year not in ytd9m_by_year:
                print(f"  9M-{year}  ({fpath.name})", end="  ")
                rec9m = _parse_filing(fpath, f"9M-{year}", f"{year}-09-30", col=3)
                if rec9m:
                    ytd9m_by_year[year] = rec9m
                    rev = rec9m.get("total_revenues")
                    print(f"rev=${rev/1e6:.0f}M" if rev else "no rev")
                else:
                    print("SKIP")

    # ── Step 2: FY totals from all 10-Ks ─────────────────────────────────────
    for fpath in sorted(FILINGS_DIR.glob("TSLA-10-K-*.htm")):
        mapping = filename_to_quarter(fpath.name)
        if not mapping:
            continue
        fy_label, period_end = mapping
        fy_year = int(fy_label.split("-")[1])
        if fy_year < 2010:
            continue  # no useful segment data before 2010

        print(f"  {fy_label}  ({fpath.name})", end="  ")
        rec = _parse_filing(fpath, fy_label, period_end, col=1)
        if rec:
            rev = rec.get("total_revenues")
            print(f"rev=${rev/1e6:.0f}M" if rev else "no rev")
            fy_by_year[fy_year] = rec
        else:
            print("SKIP")

    # ── Step 3: Derive Q4 = FY − 9M YTD ──────────────────────────────────────
    for year, fy_rec in sorted(fy_by_year.items()):
        q4_label = f"Q4-{year}"
        if q4_label in seen:
            continue
        if year in ytd9m_by_year:
            q4 = _subtract_records(fy_rec, ytd9m_by_year[year], year)
            rev = q4.get("total_revenues")
            print(f"  {q4_label}  (derived)  rev=${rev/1e6:.0f}M" if rev else f"  {q4_label} derived (no rev)")
            records.append(q4)
            seen.add(q4_label)
        else:
            print(f"  {q4_label}: skipped — no 9M YTD")

    # ── Sort newest first ──────────────────────────────────────────────────────
    def sort_key(r):
        m = re.match(r"Q(\d)-(\d{4})", r["quarter"])
        return (int(m.group(2)), int(m.group(1))) if m else (0, 0)

    records.sort(key=sort_key, reverse=True)
    return records

# ── Write to data.js ───────────────────────────────────────────────────────────

def update_data_js(records: list):
    text     = DATA_JS.read_text(encoding="utf-8")
    json_str = json.dumps(records, indent=4)
    new_block = f"  segments: {json_str},"

    pattern  = r"segments:\s*\[.*?\],"
    new_text = re.sub(pattern, new_block.lstrip(), text, flags=re.DOTALL, count=1)

    if new_text == text:
        out = SCRIPT_DIR.parent / "extracted_segments.json"
        out.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"  WARNING: regex replace failed — written to {out}")
        return

    DATA_JS.write_text(new_text, encoding="utf-8")
    print(f"\n  data.js updated — {len(records)} segment records written.")

# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    print("Extracting Tesla segment revenue from all 10-Q/10-K filings...\n")
    records = extract_all()

    if not records:
        print("No records extracted.")
        return

    print(f"\n{len(records)} total records. Sample (newest 5):")
    for r in records[:5]:
        rev   = r.get("total_revenues")
        gp    = r.get("gross_profit")
        auto  = r.get("total_automotive_rev")
        energy= r.get("energy_rev")
        if all(v is not None for v in [rev, gp, auto, energy]):
            print(f"  {r['quarter']:<8}  Rev=${rev/1e9:.2f}B  GP=${gp/1e9:.2f}B  "
                  f"Auto=${auto/1e9:.2f}B  Energy=${energy/1e9:.2f}B  [{r['source']}]")
        elif rev and gp:
            print(f"  {r['quarter']:<8}  Rev=${rev/1e9:.2f}B  GP=${gp/1e9:.2f}B  [{r['source']}]")
        else:
            print(f"  {r['quarter']:<8}  Rev={rev}  [{r['source']}]")

    update_data_js(records)
    print("Done.")


if __name__ == "__main__":
    main()
