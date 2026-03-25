"""
Tesla Segment Revenue & COGS Extractor
Parses 10-Q and 10-K HTML filings to extract quarterly revenue and COGS
broken down by segment: Automotive, Energy, Services.

Writes to tesla-dashboard/data.js  (updates window.TSLA.segments array)
"""

import re
import json
from pathlib import Path
from bs4 import BeautifulSoup
from datetime import date

SCRIPT_DIR = Path(__file__).parent
FILINGS_DIR = SCRIPT_DIR.parent / "company_docs" / "sec_filings"
DATA_JS    = SCRIPT_DIR.parent / "data.js"

# ── Quarter mapping ───────────────────────────────────────────────────────────

def filename_to_quarter(fname: str) -> tuple[str, str] | None:
    """
    Returns (quarter_label, period_end) from filename.
    e.g. TSLA-10-Q-2025-07-24.htm → ('Q2-2025', '2025-06-30')
         TSLA-10-K-2024.htm        → ('FY-2024', '2024-12-31')
    """
    fname = fname.lower()

    # 10-Q: TSLA-10-Q-YYYY-MM-DD.htm
    m = re.match(r"tsla-10-q-(\d{4})-(\d{2})-\d{2}", fname)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        # Filing month → quarter end
        # Q1 ends Mar 31, filed Apr-May; Q2 ends Jun 30, filed Jul-Aug; Q3 ends Sep 30, filed Oct-Nov
        if mo in (4, 5):
            return f"Q1-{y}", f"{y}-03-31"
        elif mo in (7, 8):
            return f"Q2-{y}", f"{y}-06-30"
        elif mo in (10, 11):
            return f"Q3-{y}", f"{y}-09-30"
        # Some early filings have unusual months
        return None

    # 10-K: TSLA-10-K-YYYY.htm
    # Filename year = filing year (filed Jan/Feb YYYY for fiscal year YYYY-1)
    # e.g. TSLA-10-K-2025.htm filed Feb 2025 → covers FY2024
    m = re.match(r"tsla-10-k-(\d{4})", fname)
    if m:
        filing_year = int(m.group(1))
        fy = filing_year - 1  # fiscal year is one behind filing year
        return f"FY-{fy}", f"{fy}-12-31"

    return None

# ── Table parser ──────────────────────────────────────────────────────────────

def detect_unit_multiplier(soup: BeautifulSoup) -> int:
    """Return 1000 if filing is in thousands, 1_000_000 if in millions."""
    text = soup.get_text(" ")
    # Check for explicit accounting labels — must be a standalone 'in' (word boundary)
    # to avoid matching "contain thousands" / "contain millions"
    if re.search(r"\bin\s+millions", text, re.I):
        return 1_000_000
    if re.search(r"\bin\s+thousands", text, re.I):
        return 1_000
    return 1_000_000  # default for modern filings


def parse_income_statement(soup: BeautifulSoup, quarter_label: str, target_col: int = 1) -> dict | None:
    """
    Finds the consolidated statements of operations / income statement table.
    Returns dict with segment revenue and COGS, or None if not found.
    """

    # Target rows by label
    TARGET_ROWS = {
        # Revenue
        "automotive_sales_rev":        re.compile(r"automotive\s+sales", re.I),
        "automotive_credits_rev":      re.compile(r"automotive\s+regulatory\s+credits", re.I),
        "automotive_leasing_rev":      re.compile(r"automotive\s+leasing", re.I),
        "total_automotive_rev":        re.compile(r"total\s+automotive\s+revenues?", re.I),
        "energy_rev":                  re.compile(r"energy\s+generation\s+and\s+storage", re.I),
        "services_rev":                re.compile(r"services\s+and\s+other", re.I),
        "total_revenues":              re.compile(r"^total\s+revenues?$", re.I),
        # COGS
        "automotive_sales_cogs":       re.compile(r"automotive\s+sales$", re.I),   # in COGS section
        "total_automotive_cogs":       re.compile(r"total\s+automotive\s+cost", re.I),
        "energy_cogs":                 re.compile(r"energy\s+generation\s+and\s+storage$", re.I),
        "services_cogs":               re.compile(r"services\s+and\s+other$", re.I),
        "total_cogs":                  re.compile(r"total\s+cost\s+of\s+revenues?", re.I),
        # Below the line
        "gross_profit":                re.compile(r"^(?:total\s+)?gross\s+profit$", re.I),
        "r_and_d":                     re.compile(r"research\s+and\s+development", re.I),
        "sga":                         re.compile(r"selling,?\s+general\s+and\s+admin", re.I),
        "op_income":                   re.compile(r"income\s+from\s+operations", re.I),
        "net_income":                  re.compile(r"net\s+income\s+attributable\s+to\s+common", re.I),
        "eps_diluted":                 re.compile(r"diluted$", re.I),
    }

    is_fy = quarter_label.startswith("FY-")
    unit = detect_unit_multiplier(soup)

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 5:
            continue

        # Check if this looks like a full income statement (needs revenues + COGS)
        full_text = table.get_text(" ")
        if not ("Total revenues" in full_text or "Total Revenues" in full_text):
            continue
        if "Automotive" not in full_text and "automotive" not in full_text:
            continue
        if not re.search(r"cost\s+of\s+revenues?", full_text, re.I):
            continue  # skip segment-revenue-only tables

        # Determine column structure from header rows
        # Format: [label] [Q_current] [Q_prior] [YTD_current] [YTD_prior]  (for 10-Q)
        #         [label] [FY_current] [FY_prior] [FY_prior2]                (for 10-K)
        header_texts = []
        for row in rows[:6]:
            cells = row.find_all(["td", "th"])
            cell_texts = [c.get_text(" ", strip=True) for c in cells]
            combined = " ".join(cell_texts)
            if any(k in combined for k in ["Three Months", "Six Months", "Nine Months", "Year Ended", "Fiscal Year"]):
                header_texts = cell_texts
                break

        # target_col is passed in by caller:
        #   1 = first data col (Q standalone for 10-Q; FY current for 10-K)
        #   3 = Nine Months YTD (Q3 10-Q only)
        def extract_val(cells: list, col: int) -> int | None:
            numeric_cols = [
                c for c in cells[1:]
                if re.sub(r"[^\d()\-]", "", c.get_text(strip=True))
            ]
            if col - 1 < len(numeric_cols):
                raw = numeric_cols[col - 1].get_text(strip=True)
                # Handle negatives in parens
                raw = raw.replace("(", "-").replace(")", "")
                raw = re.sub(r"[^\d.\-]", "", raw)
                try:
                    return int(float(raw) * unit) if raw and raw != "-" else None
                except ValueError:
                    return None
            return None

        # Extract values
        result = {}
        in_cogs = False
        prev_label = ""

        for row in rows:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            label = cells[0].get_text(" ", strip=True).strip()
            label_clean = re.sub(r"\s+", " ", label)

            # Track whether we're in the COGS section
            if re.search(r"cost\s+of\s+revenues?", label_clean, re.I):
                in_cogs = True

            for key, pattern in TARGET_ROWS.items():
                if pattern.search(label_clean):
                    # Disambiguate same-label rows in revenue vs COGS
                    if key in ("automotive_sales_cogs", "energy_cogs", "services_cogs"):
                        if not in_cogs:
                            continue
                    if key in ("automotive_sales_rev",):
                        if in_cogs:
                            continue

                    val = extract_val(cells, target_col)
                    if val is not None and key not in result:
                        result[key] = val

        if result.get("total_revenues"):
            return result

    return None

# ── Main extraction ───────────────────────────────────────────────────────────

def _parse_filing(fpath, quarter_label, period_end, col):
    """Parse one filing at the given column. Returns a record dict or None."""
    try:
        html = fpath.read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        print(f"READ ERROR: {e}")
        return None

    data = parse_income_statement(soup, quarter_label, target_col=col)
    if not data:
        return None

    return {
        "quarter":                 quarter_label,
        "period_end":              period_end,
        "automotive_sales_rev":    data.get("automotive_sales_rev"),
        "automotive_credits_rev":  data.get("automotive_credits_rev"),
        "automotive_leasing_rev":  data.get("automotive_leasing_rev"),
        "total_automotive_rev":    data.get("total_automotive_rev"),
        "energy_rev":              data.get("energy_rev"),
        "services_rev":            data.get("services_rev"),
        "total_revenues":          data.get("total_revenues"),
        "automotive_sales_cogs":   data.get("automotive_sales_cogs"),
        "total_automotive_cogs":   data.get("total_automotive_cogs"),
        "energy_cogs":             data.get("energy_cogs"),
        "services_cogs":           data.get("services_cogs"),
        "total_cogs":              data.get("total_cogs"),
        "gross_profit":            data.get("gross_profit"),
        "r_and_d":                 data.get("r_and_d"),
        "sga":                     data.get("sga"),
        "op_income":               data.get("op_income"),
        "net_income":              data.get("net_income"),
        "source":                  "10-Q" if "10-Q" in fpath.name else "10-K",
    }


def _subtract_records(fy: dict, ytd9m: dict, year: int) -> dict:
    """Derive Q4 = FY - 9M YTD for every numeric field."""
    FIELDS = [
        "automotive_sales_rev", "automotive_credits_rev", "automotive_leasing_rev",
        "total_automotive_rev", "energy_rev", "services_rev", "total_revenues",
        "automotive_sales_cogs", "total_automotive_cogs", "energy_cogs",
        "services_cogs", "total_cogs", "gross_profit", "r_and_d", "sga",
        "op_income", "net_income",
    ]
    result = {
        "quarter":    f"Q4-{year}",
        "period_end": f"{year}-12-31",
        "source":     "derived (10-K minus 9M)",
    }
    for f in FIELDS:
        a, b = fy.get(f), ytd9m.get(f)
        result[f] = (a - b) if (a is not None and b is not None) else None
    return result


def extract_all() -> list[dict]:
    # ── Step 1: Q1/Q2/Q3 from 10-Qs (2023+, col 1 = three-month standalone) ──
    q_filings = [
        f for f in sorted(FILINGS_DIR.glob("TSLA-10-Q-*.htm"))
        if int(f.name.split("-")[3]) >= 2023
    ]

    records = []
    seen = set()
    ytd9m_by_year = {}   # year → 9M YTD record (from Q3 10-Q col 3)

    for fpath in q_filings:
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

        # Q3 10-Q (Oct-Nov filing) → also grab Nine Months YTD (col 3)
        if filing_month in (10, 11) and quarter_label not in seen or filing_month in (10, 11):
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

    # ── Step 2: FY totals from 10-K (2024+ files → FY 2023+) ──────────────────
    k_filings = [
        f for f in sorted(FILINGS_DIR.glob("TSLA-10-K-*.htm"))
        if int(f.stem.split("-")[3]) >= 2024   # filing year 2024 → FY2023
    ]

    fy_by_year = {}  # fiscal year → FY record

    for fpath in k_filings:
        mapping = filename_to_quarter(fpath.name)
        if not mapping:
            continue
        fy_label, period_end = mapping   # e.g. "FY-2024"
        fy_year = int(fy_label.split("-")[1])

        print(f"  {fy_label}  ({fpath.name})", end="  ")
        rec = _parse_filing(fpath, fy_label, period_end, col=1)
        if rec:
            rev = rec.get("total_revenues")
            print(f"rev=${rev/1e6:.0f}M" if rev else "no rev")
            fy_by_year[fy_year] = rec
        else:
            print("SKIP")

    # ── Step 3: Derive Q4 = FY − 9M YTD ──────────────────────────────────────
    for year, fy_rec in fy_by_year.items():
        if year in ytd9m_by_year:
            q4_label = f"Q4-{year}"
            if q4_label not in seen:
                q4 = _subtract_records(fy_rec, ytd9m_by_year[year], year)
                rev = q4.get("total_revenues")
                print(f"  Q4-{year}  (derived)  rev=${rev/1e6:.0f}M" if rev else f"  Q4-{year} derived")
                records.append(q4)
                seen.add(q4_label)
        else:
            print(f"  Q4-{year}: skipped — no 9M YTD found")

    # ── Sort newest first ──────────────────────────────────────────────────────
    def sort_key(r):
        q = r["quarter"]
        m = re.match(r"Q(\d)-(\d{4})", q)
        return (int(m.group(2)), int(m.group(1))) if m else (0, 0)

    records.sort(key=sort_key, reverse=True)
    return records

# ── Write to data.js ──────────────────────────────────────────────────────────

def update_data_js(records: list):
    text = DATA_JS.read_text(encoding="utf-8")
    json_str = json.dumps(records, indent=4)
    new_block = f"  segments: {json_str},"

    # Match segments: [ ... ], including possibly multi-line empty array
    pattern = r"segments:\s*\[.*?\],"
    new_text = re.sub(pattern, new_block.lstrip(), text, flags=re.DOTALL, count=1)

    if new_text == text:
        print("  WARNING: segments array not found in data.js — writing fallback JSON")
        out = SCRIPT_DIR.parent / "extracted_segments.json"
        out.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"  Written to: {out}")
        return

    DATA_JS.write_text(new_text, encoding="utf-8")
    print(f"\n  data.js updated — {len(records)} segment records written.")

# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print("Extracting Tesla segment revenue from 10-Q/10-K filings...")
    records = extract_all()

    if not records:
        print("No records extracted.")
        return

    print(f"\nSample (newest 5):")
    for r in records[:5]:
        rev = r["total_revenues"]
        gp  = r["gross_profit"]
        auto = r["total_automotive_rev"]
        energy = r["energy_rev"]
        print(f"  {r['quarter']:<8}  Rev=${rev/1e9:.2f}B  GP=${gp/1e9:.2f}B  Auto=${auto/1e9:.2f}B  Energy=${energy/1e9:.2f}B"
              if all(v is not None for v in [rev, gp, auto, energy])
              else f"  {r['quarter']:<8}  Rev={rev}  GP={gp}")

    update_data_js(records)
    print("Done.")


if __name__ == "__main__":
    main()
