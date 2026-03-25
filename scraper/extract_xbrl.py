"""
Tesla XBRL Financial Extractor
Pulls all reported financial figures from SEC EDGAR's XBRL companyfacts API.
Data is certified by Tesla — 100% accuracy, no PDF parsing needed.

Extracts quarterly records and writes to:
  tesla-dashboard/data.js  (updates window.TSLA.financials array)

Run after new 10-Q or 10-K is filed (i.e. each quarter).
"""

import requests
import json
import re
from pathlib import Path
from datetime import date, datetime
from collections import defaultdict

# ── Config ────────────────────────────────────────────────────────────────────

TESLA_CIK  = "CIK0001318605"
XBRL_URL   = f"https://data.sec.gov/api/xbrl/companyfacts/{TESLA_CIK}.json"
HEADERS    = {"User-Agent": "Tesla Dashboard personal-research saumi.personal@gmail.com"}

SCRIPT_DIR = Path(__file__).parent
DATA_JS    = SCRIPT_DIR.parent / "data.js"

# ── Concept map: XBRL concept → our field name ────────────────────────────────

# Flow statement concepts (have start + end dates)
FLOW_CONCEPTS = {
    "Revenues":                                    "revenue_total",
    "GrossProfit":                                 "gross_profit",
    "OperatingIncomeLoss":                         "op_income",
    "NetIncomeLoss":                               "net_income",
    "ResearchAndDevelopmentExpense":               "r_and_d",
    "PaymentsToAcquirePropertyPlantAndEquipment":  "capex",
    "NetCashProvidedByUsedInOperatingActivities":  "operating_cash_flow",
    "CostOfRevenue":                               "cogs",
}

# Balance sheet concepts (instantaneous — end date only)
INSTANT_CONCEPTS = {
    "CashAndCashEquivalentsAtCarryingValue":                          "cash_end",
    "CashCashEquivalentsAndShortTermInvestments":                     "cash_investments_end",
    "RestrictedCashAndCashEquivalents":                               "restricted_cash",
}

# EPS has different units (USD/shares)
EPS_CONCEPTS = {
    "EarningsPerShareDiluted": "eps_diluted",
    "EarningsPerShareBasic":   "eps_basic",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

QUARTER_ENDS = {(3, 31), (6, 30), (9, 30), (12, 31)}

def quarter_label(end_date: date) -> str:
    q = (end_date.month - 1) // 3 + 1
    return f"Q{q}-{end_date.year}"


def is_quarter_end(d: date) -> bool:
    return (d.month, d.day) in QUARTER_ENDS


def best_per_period(entries: list) -> dict:
    """
    Given a list of XBRL entries, deduplicate by (start, end): keep the most
    recently-filed value for each period (handles restatements & amendments).
    Returns {(start, end): entry}
    """
    best = {}
    for e in entries:
        key = (e.get("start", ""), e.get("end", ""))
        if key not in best or e.get("filed", "") > best[key].get("filed", ""):
            best[key] = e
    return best


# ── Extract flow concepts (revenue, profit, cash flow, capex) ────────────────

def extract_flow_series(concept_entries: list) -> dict[str, float]:
    """
    Returns {quarter_label: value} for single-quarter periods only.
    Single-quarter = (end - start) between 85 and 95 days.
    Q4 is derived as FY value minus the Q1–Q3 YTD value.
    """
    by_period = best_per_period(concept_entries)

    standalone = {}   # quarter_label → value
    ytd_q3     = {}   # year → 9-month value
    full_year  = {}   # year → FY value

    for (start_s, end_s), e in by_period.items():
        if not start_s or not end_s:
            continue
        try:
            start = date.fromisoformat(start_s)
            end   = date.fromisoformat(end_s)
        except ValueError:
            continue

        val  = e.get("val")
        if val is None:
            continue

        days = (end - start).days

        # Full fiscal year  (Jan 1 → Dec 31, ~365 days)
        if start.month == 1 and start.day == 1 and end.month == 12 and end.day == 31 and days > 350:
            full_year[end.year] = val
            continue

        # Q1–Q3 YTD  (Jan 1 → Sep 30, ~272 days)
        if start.month == 1 and start.day == 1 and end.month == 9 and end.day == 30 and 265 <= days <= 280:
            ytd_q3[end.year] = val
            continue

        # Single quarter  (~91 days)
        if 85 <= days <= 96 and is_quarter_end(end):
            standalone[quarter_label(end)] = val

    # Derive Q4 = FY − 9-month YTD
    for year, fy_val in full_year.items():
        if year in ytd_q3:
            q4 = f"Q4-{year}"
            if q4 not in standalone:   # don't overwrite if we already have it
                standalone[q4] = fy_val - ytd_q3[year]

    return standalone


# ── Extract instant (balance sheet) concepts ─────────────────────────────────

def extract_instant_series(concept_entries: list) -> dict[str, float]:
    """
    Returns {quarter_label: value} for quarter-end dates only.
    """
    result = {}
    by_date = {}  # end_date → entry (latest filed)
    for e in concept_entries:
        end_s  = e.get("end", "")
        filed  = e.get("filed", "")
        if end_s not in by_date or filed > by_date[end_s].get("filed", ""):
            by_date[end_s] = e

    for end_s, e in by_date.items():
        try:
            end = date.fromisoformat(end_s)
        except ValueError:
            continue
        if is_quarter_end(end):
            result[quarter_label(end)] = e.get("val")

    return result


# ── Main extraction ───────────────────────────────────────────────────────────

def extract_all() -> list[dict]:
    print("Fetching Tesla XBRL companyfacts from EDGAR...")
    r = requests.get(XBRL_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    facts = r.json()["facts"]["us-gaap"]
    print(f"  Received {len(facts)} US-GAAP concepts.")

    # Build series for each metric
    series = {}

    for concept, field in FLOW_CONCEPTS.items():
        entries = facts.get(concept, {}).get("units", {}).get("USD", [])
        series[field] = extract_flow_series(entries)
        print(f"  {field}: {len(series[field])} quarters")

    for concept, field in INSTANT_CONCEPTS.items():
        entries = facts.get(concept, {}).get("units", {}).get("USD", [])
        series[field] = extract_instant_series(entries)
        print(f"  {field}: {len(series[field])} quarters")

    for concept, field in EPS_CONCEPTS.items():
        entries = facts.get(concept, {}).get("units", {}).get("USD/shares", [])
        series[field] = extract_flow_series(entries)   # EPS works same way as flow
        print(f"  {field}: {len(series[field])} quarters")

    # Collect all known quarters
    all_quarters = set()
    for s in series.values():
        all_quarters.update(s.keys())

    # Sort: newest first
    def sort_key(lbl):
        m = re.match(r"Q(\d)-(\d{4})", lbl)
        return (int(m.group(2)), int(m.group(1))) if m else (0, 0)

    all_quarters = sorted(all_quarters, key=sort_key, reverse=True)
    print(f"\n  Total quarters with data: {len(all_quarters)}")

    # Build records
    records = []
    for q in all_quarters:
        m = re.match(r"Q(\d)-(\d{4})", q)
        if not m:
            continue
        qn, yr = int(m.group(1)), int(m.group(2))

        # Quarter end date
        month_end = qn * 3
        day_end   = {3: 31, 6: 30, 9: 30, 12: 31}[month_end]
        period_end = f"{yr}-{month_end:02d}-{day_end:02d}"

        # Pull each metric
        def get(field):
            return series.get(field, {}).get(q)

        rev   = get("revenue_total")
        gp    = get("gross_profit")
        oi    = get("op_income")
        ni    = get("net_income")
        cogs  = get("cogs")
        ocf   = get("operating_cash_flow")
        capex = get("capex")

        # Derived
        gm_pct    = round(gp / rev * 100, 2) if rev and gp is not None else None
        op_mg_pct = round(oi / rev * 100, 2) if rev and oi is not None else None
        fcf       = (ocf - capex) if ocf is not None and capex is not None else None

        # Cash: prefer the combined cash+investments figure, fall back to cash only
        cash = get("cash_investments_end") or get("cash_end")

        record = {
            "quarter":                q,
            "period_end":             period_end,
            # Revenue
            "revenue_total":          rev,
            "revenue_auto":           None,       # from PDF extraction later
            "revenue_energy":         None,
            "revenue_services":       None,
            # Profitability
            "gross_profit":           gp,
            "gross_margin_pct":       gm_pct,
            "gross_profit_auto":      None,       # from PDF extraction later
            "gross_margin_auto_pct":  None,
            "op_income":              oi,
            "op_margin_pct":          op_mg_pct,
            "r_and_d":                get("r_and_d"),
            "net_income":             ni,
            "eps_diluted":            get("eps_diluted"),
            "eps_basic":              get("eps_basic"),
            # Cash flow
            "operating_cash_flow":    ocf,
            "capex":                  capex,
            "free_cash_flow":         fcf,
            # Balance sheet
            "cash_end":               cash,
            # Provenance
            "source":                 "SEC EDGAR XBRL",
            "verified":               True,        # XBRL = certified by Tesla
        }
        records.append(record)

    return records


# ── Write to data.js ──────────────────────────────────────────────────────────

def update_data_js(records: list):
    """
    Replace the financials array in data.js with the extracted records.
    Preserves everything else in the file.
    """
    text = DATA_JS.read_text(encoding="utf-8")

    # Build the replacement block
    json_str = json.dumps(records, indent=4)
    new_block = f"  financials: {json_str},"

    # Replace between "financials: [" and the next top-level "],"
    # Use a pattern that matches the existing (possibly empty) financials array
    pattern = r"(  financials:\s*\[).*?(\],)"
    replacement = new_block
    new_text = re.sub(pattern, replacement, text, flags=re.DOTALL, count=1)

    if new_text == text:
        print("  WARNING: could not locate financials array in data.js — writing raw append instead.")
        # Fallback: write a separate JSON file
        out = SCRIPT_DIR.parent / "extracted_financials.json"
        out.write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"  Written to: {out}")
        return

    DATA_JS.write_text(new_text, encoding="utf-8")
    print(f"  data.js updated — {len(records)} quarterly records written.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    records = extract_all()

    if not records:
        print("No records extracted — check EDGAR connectivity.")
        return

    # Print summary
    print(f"\nSample records (newest 6):")
    for r in records[:6]:
        rev  = f"${r['revenue_total']/1e3:.1f}B"   if r['revenue_total']  else "n/a"
        gm   = f"{r['gross_margin_pct']:.1f}%"      if r['gross_margin_pct'] else "n/a"
        ni   = f"${r['net_income']/1e3:.1f}B"       if r['net_income']     else "n/a"
        eps  = f"${r['eps_diluted']:.2f}"            if r['eps_diluted']    else "n/a"
        fcf  = f"${r['free_cash_flow']/1e3:.1f}B"   if r['free_cash_flow'] else "n/a"
        print(f"  {r['quarter']:<8}  Rev {rev:<10}  GM {gm:<7}  NI {ni:<10}  EPS {eps:<8}  FCF {fcf}")

    update_data_js(records)
    print("\nDone. Refresh the dashboard to see financial data.")


if __name__ == "__main__":
    main()
