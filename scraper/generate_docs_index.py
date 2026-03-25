"""
Scans company_docs/ and writes docs_index.js (window.TESLA_DOCS).
Run whenever new documents are added to any folder.
"""

import json, re
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
COMPANY_DOCS = SCRIPT_DIR.parent / "company_docs"
OUTPUT_FILE  = SCRIPT_DIR.parent / "docs_index.js"

FOLDERS = ["quarterly_updates", "earnings_releases", "sec_filings", "others"]


def classify(filename: str, folder: str) -> dict:
    meta = dict(display_name=filename, doc_type="other", date=None, quarter=None, year=None)

    # Quarterly update: TSLA-Q1-2024-Update.pdf
    m = re.match(r'TSLA-(Q\d)-(\d{4})-Update\.(pdf|htm)$', filename, re.I)
    if m:
        q, yr = m.group(1), m.group(2)
        meta.update(display_name=f"{q} {yr} Quarterly Update", doc_type="quarterly_update",
                    quarter=f"{q}-{yr}", date=yr, year=int(yr))
        return meta

    # Earnings release: TSLA-Q1-2024-Earnings-Release.htm
    m = re.match(r'TSLA-(Q\d)-(\d{4})-Earnings-Release\.(pdf|htm)$', filename, re.I)
    if m:
        q, yr = m.group(1), m.group(2)
        meta.update(display_name=f"{q} {yr} Earnings Release", doc_type="earnings_release",
                    quarter=f"{q}-{yr}", date=yr, year=int(yr))
        return meta

    # 10-K: TSLA-10-K-2024.htm
    m = re.match(r'TSLA-10-K-(\d{4})\.(pdf|htm)$', filename, re.I)
    if m:
        yr = m.group(1)
        meta.update(display_name=f"Annual Report 10-K ({yr})", doc_type="sec_10k",
                    date=yr, year=int(yr))
        return meta

    # 10-Q: TSLA-10-Q-2024-03-31.htm
    m = re.match(r'TSLA-10-Q-(\d{4}-\d{2}-\d{2})\.(pdf|htm)$', filename, re.I)
    if m:
        d = m.group(1)
        meta.update(display_name=f"Quarterly Report 10-Q ({d})", doc_type="sec_10q",
                    date=d, year=int(d[:4]))
        return meta

    # 8-K: TSLA-8-K-2024-01-26.htm
    m = re.match(r'TSLA-8-K-(\d{4}-\d{2}-\d{2})\.(pdf|htm)$', filename, re.I)
    if m:
        d = m.group(1)
        meta.update(display_name=f"SEC Filing 8-K ({d})", doc_type="sec_8k",
                    date=d, year=int(d[:4]))
        return meta

    # DEF 14A: TSLA-DEF14A-2024.htm
    m = re.match(r'TSLA-DEF14A-(\d{4})\.(pdf|htm)$', filename, re.I)
    if m:
        yr = m.group(1)
        meta.update(display_name=f"Proxy Statement DEF 14A ({yr})", doc_type="sec_proxy",
                    date=yr, year=int(yr))
        return meta

    # Delivery / Reg FD: TSLA-DELIVERY-2024-01-02.htm
    m = re.match(r'TSLA-DELIVERY-(\d{4}-\d{2}-\d{2})\.(pdf|htm)$', filename, re.I)
    if m:
        d = m.group(1)
        meta.update(display_name=f"Delivery Report ({d})", doc_type="delivery_report",
                    date=d, year=int(d[:4]))
        return meta

    # Press release: TSLA-PR-2024-01-26.htm
    m = re.match(r'TSLA-PR-(\d{4}-\d{2}-\d{2})\.(pdf|htm)$', filename, re.I)
    if m:
        d = m.group(1)
        meta.update(display_name=f"Press Release ({d})", doc_type="press_release",
                    date=d, year=int(d[:4]))
        return meta

    # Other 8-K material event: TSLA-8K-2024-01-26.htm
    m = re.match(r'TSLA-8K-(\d{4}-\d{2}-\d{2})\.(pdf|htm)$', filename, re.I)
    if m:
        d = m.group(1)
        meta.update(display_name=f"SEC 8-K Material Event ({d})", doc_type="sec_8k_other",
                    date=d, year=int(d[:4]))
        return meta

    # Impact report: TSLA-Impact-Report-2023.pdf
    m = re.match(r'TSLA-Impact-Report-(\d{4})\.(pdf|htm)$', filename, re.I)
    if m:
        yr = m.group(1)
        meta.update(display_name=f"Impact Report ({yr})", doc_type="impact_report",
                    date=yr, year=int(yr))
        return meta

    # Freeform files in others/ (user-named)
    if folder == "others":
        # Try to pull a year from the filename
        ym = re.search(r'(\d{4})', filename)
        if ym:
            meta["year"] = int(ym.group(1))
            meta["date"] = ym.group(1)
        # Clean up display name: replace hyphens/underscores, strip extension
        stem = re.sub(r'\.(pdf|htm|html)$', '', filename, flags=re.I)
        meta["display_name"] = re.sub(r'[-_]+', ' ', stem).title()
        meta["doc_type"] = "other"

    return meta


docs = []
for folder in FOLDERS:
    folder_path = COMPANY_DOCS / folder
    if not folder_path.exists():
        continue
    for file in sorted(folder_path.iterdir()):
        if file.name.startswith(".") or file.suffix.lower() not in (".pdf", ".htm", ".html"):
            continue
        meta = classify(file.name, folder)
        docs.append({
            "id":           re.sub(r'[^a-z0-9]', '_', file.name.lower()),
            "filename":     file.name,
            "path":         f"company_docs/{folder}/{file.name}",
            "folder":       folder,
            "format":       file.suffix.lstrip(".").upper(),
            "size_kb":      file.stat().st_size // 1024,
            **meta,
        })

# Sort: folder order preserved, then within each folder newest → oldest
FOLDER_IDX = {f: i for i, f in enumerate(FOLDERS)}

def sort_key(d):
    fi = FOLDER_IDX.get(d["folder"], 99)
    date_raw = d.get("date") or "0000"
    # Pad to YYYYMMDD for consistent reverse sort
    date_padded = date_raw.replace("-", "").ljust(8, "0")
    return (fi, -int(date_padded))

docs.sort(key=sort_key)

js = "// Auto-generated by scraper/generate_docs_index.py — do not edit manually\n"
js += f"window.TESLA_DOCS = {json.dumps(docs, indent=2)};\n"

OUTPUT_FILE.write_text(js, encoding="utf-8")
print(f"Written: {OUTPUT_FILE.name}  ({len(docs)} documents)")

from collections import Counter
counts = Counter(d["doc_type"] for d in docs)
for t, n in sorted(counts.items(), key=lambda x: -x[1]):
    print(f"  {n:>4}  {t}")
