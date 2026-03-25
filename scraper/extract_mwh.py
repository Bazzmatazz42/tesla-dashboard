"""
Extract MWh capacity data from Saumil's worksheet (MWhPrice sheet).
Outputs window.TSLA.mwh_capacity array into data.js.

Data covers Q3-2019 through Q4-2025 (26 quarters).
MWh capacity = vehicle capacity (units) × battery size per vehicle,
plus energy storage MWh, giving a unified battery-output lens across products.
"""

import re
import json
from pathlib import Path
import openpyxl

SCRIPT_DIR  = Path(__file__).parent
XLSX        = SCRIPT_DIR.parent / "company_docs" / "Saumil Uploads" / "US Watchlist - Tesla.xlsx"
DATA_JS     = SCRIPT_DIR.parent / "data.js"

# ── Row map within the MWh section (1-indexed, matches spreadsheet) ───────────
MWH_ROWS = {
    "header_quarter": 37,
    "model_sx":         39,   # Model S/X (Fremont)
    "model3_fremont":   40,   # Model 3 (Fremont)
    "modely_fremont":   41,   # Model Y (Fremont) — mostly null
    "model3_shanghai":  42,   # Model 3 (Shanghai)
    "modely_shanghai":  43,   # Model Y (Shanghai) — mostly null
    "modely_berlin":    44,   # Model Y (Berlin)
    "modely_texas":     46,   # Model Y (Texas)
    "cybertruck":       47,   # Cybertruck (Texas)
    "energy_storage":   56,   # Energy Storage (Global, MWh/yr capacity)
    "tsla_price":       71,
    "total_mwh":        72,
    "qoq_capacity_growth": 73,
    "qoq_price_growth": 74,
    "mwh_price_ratio":  75,
}

# ── Quarter label normalizer: "Q4 25" → "Q4-2025" ────────────────────────────
def normalise_quarter(label: str) -> str | None:
    m = re.match(r"Q([1-4])\s+(\d{2})", str(label).strip())
    if not m:
        return None
    q, yr = m.group(1), int(m.group(2))
    year = 2000 + yr
    return f"Q{q}-{year}"

def quarter_period_end(q_label: str) -> str:
    q, yr = q_label.split("-")
    ends = {"Q1": "03-31", "Q2": "06-30", "Q3": "09-30", "Q4": "12-31"}
    return f"{yr}-{ends[q]}"

# ── Numeric coercion ──────────────────────────────────────────────────────────
def to_num(v) -> float | None:
    if v is None or v == "" or v == "-":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    # String like "Construction" → None
    return None


def extract() -> list[dict]:
    wb = openpyxl.load_workbook(str(XLSX), data_only=True)
    ws = wb["MWhPrice"]

    # Load all rows we care about into memory (row_index → list of cell values)
    needed = set(MWH_ROWS.values())
    rows = {}
    for i, row in enumerate(ws.iter_rows(values_only=True), 1):
        if i in needed:
            rows[i] = list(row)

    # Quarter labels from header row (cols C onward = index 2+)
    header = rows[MWH_ROWS["header_quarter"]]
    quarters = []
    for col_idx in range(2, len(header)):
        raw = header[col_idx]
        if raw is None:
            break
        q = normalise_quarter(raw)
        if q:
            quarters.append((col_idx, q))

    records = []
    for col_idx, q_label in quarters:
        def get(row_key):
            return to_num(rows[MWH_ROWS[row_key]][col_idx])

        model_sx       = get("model_sx")
        model3_f       = get("model3_fremont")
        modely_f       = get("modely_fremont")
        model3_sh      = get("model3_shanghai")
        modely_sh      = get("modely_shanghai")
        modely_b       = get("modely_berlin")
        modely_tx      = get("modely_texas")
        cybertruck     = get("cybertruck")
        energy_storage = get("energy_storage")

        # Aggregates
        model3 = (model3_f or 0) + (model3_sh or 0) or None
        modely = (modely_f or 0) + (modely_sh or 0) + (modely_b or 0) + (modely_tx or 0) or None
        auto_total = sum(v for v in [model_sx, model3_f, modely_f, model3_sh,
                                     modely_sh, modely_b, modely_tx, cybertruck]
                         if v is not None) or None

        rec = {
            "quarter":             q_label,
            "period_end":          quarter_period_end(q_label),
            # Summary metrics
            "tsla_price":          get("tsla_price"),
            "total_mwh":           get("total_mwh"),
            "mwh_price_ratio":     get("mwh_price_ratio"),
            "qoq_capacity_growth": get("qoq_capacity_growth"),
            "qoq_price_growth":    get("qoq_price_growth"),
            # Per-product MWh (annual capacity, MWh/yr)
            "model_sx_mwh":        model_sx,
            "model3_mwh":          model3,
            "modely_mwh":          modely,
            "cybertruck_mwh":      cybertruck,
            "auto_mwh":            auto_total,
            "energy_storage_mwh":  energy_storage,
        }
        records.append(rec)
        print(f"  {q_label}  total_mwh={rec['total_mwh']}  price={rec['tsla_price']}  ratio={rec['mwh_price_ratio'] and round(rec['mwh_price_ratio'],1)}")

    # Sort newest first
    def sort_key(r):
        m = re.match(r"Q(\d)-(\d{4})", r["quarter"])
        return (int(m.group(2)), int(m.group(1))) if m else (0, 0)
    records.sort(key=sort_key, reverse=True)

    return records


def update_data_js(records: list):
    text = DATA_JS.read_text(encoding="utf-8")
    json_str = json.dumps(records, indent=4)
    new_block = f"mwh_capacity: {json_str},"

    # If mwh_capacity already exists, replace it
    pattern = r"mwh_capacity:\s*\[.*?\],"
    new_text = re.sub(pattern, new_block, text, flags=re.DOTALL, count=1)

    if new_text == text:
        # Not present yet — insert before the closing }; of the TSLA object
        # Find the last field in the object and add after it
        insert_before = "  // ── Key People"
        if insert_before in new_text:
            new_text = new_text.replace(
                insert_before,
                f"  {new_block}\n\n  {insert_before.strip()}"
            )
        else:
            print("WARNING: could not find insert point — writing fallback JSON")
            out = SCRIPT_DIR.parent / "extracted_mwh.json"
            out.write_text(json.dumps(records, indent=2))
            print(f"Written to {out}")
            return

    DATA_JS.write_text(new_text, encoding="utf-8")
    print(f"\n  data.js updated — {len(records)} MWh records written.")


def main():
    print("Extracting MWh capacity data from worksheet...\n")
    records = extract()
    print(f"\n{len(records)} quarters extracted.")
    update_data_js(records)
    print("Done.")


if __name__ == "__main__":
    main()
