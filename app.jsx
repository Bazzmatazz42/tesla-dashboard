const { useState, useMemo, useCallback } = React;
const {
  AreaChart, Area, BarChart, Bar, LineChart, Line,
  ComposedChart,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine
} = Recharts;

const C = window.COLORS;
const DATA = window.TSLA || {};
const DOCS = window.TESLA_DOCS || [];

// ── Formatters ────────────────────────────────────────────────────────────────

const fmt = {
  usd: (v, decimals = 1) => {
    if (v == null) return "—";
    // values stored in raw dollars from XBRL
    const abs = Math.abs(v);
    const sign = v < 0 ? "-" : "";
    if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(decimals)}B`;
    if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(decimals)}M`;
    if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(decimals)}K`;
    return `${sign}$${abs.toFixed(0)}`;
  },
  pct: (v, decimals = 1) => v == null ? "—" : `${v.toFixed(decimals)}%`,
  num: (v) => v == null ? "—" : v.toLocaleString(),
  k:   (v) => v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(1)}k` : v.toString(),
  eps: (v) => v == null ? "—" : `$${v.toFixed(2)}`,
  date:(s) => s ? s.slice(0, 10) : "—",
};

function delta(curr, prev, pct = false) {
  if (curr == null || prev == null || prev === 0) return null;
  const d = pct ? curr - prev : ((curr - prev) / Math.abs(prev)) * 100;
  return d;
}

// ── Reusable UI ───────────────────────────────────────────────────────────────

function Badge({ label, color = C.textDim, bg = C.surface2 }) {
  return (
    <span style={{
      display: "inline-block",
      fontSize: 10, fontWeight: 700, letterSpacing: "0.05em",
      textTransform: "uppercase", padding: "2px 7px", borderRadius: 4,
      color, background: bg, whiteSpace: "nowrap",
    }}>
      {label}
    </span>
  );
}

function Card({ children, style = {} }) {
  return (
    <div style={{
      background: C.surface, border: `1px solid ${C.border}`,
      borderRadius: 10, padding: "20px 24px", ...style,
    }}>
      {children}
    </div>
  );
}

function SectionTitle({ children }) {
  return (
    <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "0.1em",
      textTransform: "uppercase", color: C.textDim, marginBottom: 16 }}>
      {children}
    </div>
  );
}

function EmptyState({ icon = "◎", title, subtitle }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", padding: "60px 24px", color: C.textDim, textAlign: "center",
    }}>
      <div style={{ fontSize: 36, marginBottom: 16, opacity: 0.4 }}>{icon}</div>
      <div style={{ fontSize: 15, fontWeight: 600, color: C.textMuted, marginBottom: 8 }}>{title}</div>
      {subtitle && <div style={{ fontSize: 13, maxWidth: 380 }}>{subtitle}</div>}
    </div>
  );
}

function KpiCard({ label, value, sub, change, accent = false }) {
  const changeColor = change == null ? C.textDim : change >= 0 ? C.positive : C.negative;
  const changeSign  = change == null ? "" : change >= 0 ? "+" : "";
  return (
    <Card style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 160 }}>
      <div style={{ fontSize: 11, fontWeight: 600, letterSpacing: "0.08em",
        textTransform: "uppercase", color: C.textDim }}>
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700,
        color: accent ? C.accent : C.text, lineHeight: 1.1 }}>
        {value ?? "—"}
      </div>
      {sub && <div style={{ fontSize: 12, color: C.textMuted }}>{sub}</div>}
      {change != null && (
        <div style={{ fontSize: 12, color: changeColor, fontWeight: 600 }}>
          {changeSign}{change.toFixed(1)}% QoQ
        </div>
      )}
    </Card>
  );
}

function FilterChip({ label, count, active, onClick }) {
  return (
    <button onClick={onClick} style={{
      padding: "5px 12px", borderRadius: 20,
      border: active ? `1px solid ${C.accent}` : `1px solid ${C.border}`,
      background: active ? C.accentSoft : "transparent",
      color: active ? C.accent : C.textMuted,
      fontSize: 12, fontWeight: active ? 700 : 500,
      cursor: "pointer", whiteSpace: "nowrap", transition: "all 0.15s",
    }}>
      {label}{count != null ? ` (${count})` : ""}
    </button>
  );
}

function SearchBox({ value, onChange, placeholder }) {
  return (
    <input
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      style={{
        background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8,
        color: C.text, padding: "8px 14px", fontSize: 13, outline: "none", width: 280,
      }}
    />
  );
}

// ── Chart Tooltip ─────────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label, prefix = "" }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: C.surface2, border: `1px solid ${C.border}`,
      borderRadius: 8, padding: "10px 14px", fontSize: 12,
    }}>
      <div style={{ color: C.textMuted, marginBottom: 6, fontWeight: 600 }}>{label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color, marginBottom: 2 }}>
          {p.name}: {prefix}{typeof p.value === "number" ? p.value.toLocaleString() : p.value}
        </div>
      ))}
    </div>
  );
}

// ── Doc type metadata ─────────────────────────────────────────────────────────

const DOC_TYPE_META = {
  quarterly_update:  { label: "Quarterly Update",  color: "#3B82F6", bg: "rgba(59,130,246,0.15)" },
  earnings_release:  { label: "Earnings Release",  color: C.accent,  bg: C.accentSoft },
  sec_10k:           { label: "10-K Annual",        color: "#22C55E", bg: "rgba(34,197,94,0.15)" },
  sec_10q:           { label: "10-Q Quarterly",     color: "#10B981", bg: "rgba(16,185,129,0.15)" },
  sec_8k:            { label: "8-K Current",        color: "#8B5CF6", bg: "rgba(139,92,246,0.15)" },
  sec_8k_other:      { label: "8-K Event",          color: "#7C3AED", bg: "rgba(124,58,237,0.15)" },
  sec_proxy:         { label: "Proxy DEF 14A",      color: "#F59E0B", bg: "rgba(245,158,11,0.15)" },
  delivery_report:   { label: "Delivery Report",    color: "#EC4899", bg: "rgba(236,72,153,0.15)" },
  press_release:     { label: "Press Release",      color: "#14B8A6", bg: "rgba(20,184,166,0.15)" },
  impact_report:     { label: "Impact Report",      color: "#22C55E", bg: "rgba(34,197,94,0.15)" },
  other:             { label: "Other",              color: C.textDim, bg: C.surface2 },
};

function DocTypeBadge({ type }) {
  const m = DOC_TYPE_META[type] || DOC_TYPE_META.other;
  return <Badge label={m.label} color={m.color} bg={m.bg} />;
}

// ════════════════════════════════════════════════════════════════════════════
// TAB: Overview
// ════════════════════════════════════════════════════════════════════════════

function TabOverview() {
  const fin  = DATA.financials  || [];
  const segs = DATA.segments    || [];
  const rawDel = DATA.deliveries || [];

  // Build derived delivery rows (Q4 standalone)
  const delRows = useMemo(() => buildDeliveryRows(rawDel), [rawDel]);
  // Non-annual quarterly rows only
  const delQ = delRows.filter(r => !r.is_annual_total || r._derived);

  const latest    = fin[0]  || null;
  const prev      = fin[1]  || null;
  const latestDel = delQ[0] || null;
  const prevDel   = delQ[1] || null;
  const latestSeg = segs[0] || null;

  const hasFinData = fin.length > 0;
  const hasDelData = delQ.length > 0;

  // TTM revenue from financials (XBRL)
  const ttmRevenue = fin.slice(0, 4).reduce((s, q) => s + (q.revenue_total || 0), 0) || null;

  // Merge segment data onto financial quarters for chart
  const segByQ = Object.fromEntries(segs.map(s => [s.quarter, s]));
  const revChartData = [...fin].reverse().slice(-12).map(q => ({
    quarter: q.quarter,
    auto:    segByQ[q.quarter]?.total_automotive_rev ?? null,
    energy:  segByQ[q.quarter]?.energy_rev ?? null,
    services: segByQ[q.quarter]?.services_rev ?? null,
    total:   q.revenue_total,
  }));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>

      {/* KPI Row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 14 }}>
        <KpiCard
          label={`Deliveries (${latestDel?.quarter ?? "—"})`}
          value={hasDelData ? fmt.num(latestDel.total_delivered) : "—"}
          sub="vehicles delivered"
          change={hasDelData && prevDel ? delta(latestDel.total_delivered, prevDel.total_delivered) : null}
        />
        <KpiCard
          label="Revenue TTM"
          value={hasFinData && ttmRevenue ? fmt.usd(ttmRevenue, 1) : "—"}
          sub="trailing 12 months"
          accent
        />
        <KpiCard
          label="Gross Margin"
          value={hasFinData ? fmt.pct(latest?.gross_margin_pct) : "—"}
          sub={hasFinData ? latest?.quarter : "Awaiting data"}
          change={hasFinData ? delta(latest?.gross_margin_pct, prev?.gross_margin_pct, true) : null}
        />
        <KpiCard
          label="Operating Margin"
          value={hasFinData ? fmt.pct(latest?.op_margin_pct) : "—"}
          sub={hasFinData ? latest?.quarter : "Awaiting data"}
          change={hasFinData ? delta(latest?.op_margin_pct, prev?.op_margin_pct, true) : null}
        />
        <KpiCard
          label="Free Cash Flow"
          value={hasFinData ? fmt.usd(latest?.free_cash_flow) : "—"}
          sub={hasFinData ? latest?.quarter : "Awaiting data"}
          change={hasFinData ? delta(latest?.free_cash_flow, prev?.free_cash_flow) : null}
        />
        <KpiCard
          label="Cash on Hand"
          value={hasFinData ? fmt.usd(latest?.cash_end) : "—"}
          sub={hasFinData ? latest?.quarter : "Awaiting data"}
        />
      </div>

      {/* Charts */}
      {hasFinData ? (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
          {/* Deliveries trend */}
          <Card>
            <SectionTitle>Quarterly Deliveries (12Q)</SectionTitle>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={delQ.slice(0, 12).reverse()}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                <XAxis dataKey="quarter" tick={{ fill: C.textDim, fontSize: 10 }} />
                <YAxis tick={{ fill: C.textDim, fontSize: 10 }} tickFormatter={v => `${(v/1000).toFixed(0)}k`} />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null;
                    return (
                      <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 14px", fontSize: 12 }}>
                        <div style={{ color: C.textMuted, marginBottom: 4, fontWeight: 600 }}>{label}</div>
                        <div style={{ color: C.accent }}>{(payload[0]?.value || 0).toLocaleString()} delivered</div>
                      </div>
                    );
                  }}
                />
                <Area type="monotone" dataKey="total_delivered" name="Deliveries"
                  stroke={C.accent} fill={C.accentSoft} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </Card>

          {/* Revenue by segment */}
          <Card>
            <SectionTitle>Revenue by Segment (12Q)</SectionTitle>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={revChartData}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
                <XAxis dataKey="quarter" tick={{ fill: C.textDim, fontSize: 10 }} />
                <YAxis tick={{ fill: C.textDim, fontSize: 10 }} tickFormatter={v => `$${(v/1e9).toFixed(0)}B`} />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (!active || !payload?.length) return null;
                    return (
                      <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 14px", fontSize: 12 }}>
                        <div style={{ color: C.textMuted, marginBottom: 6, fontWeight: 600 }}>{label}</div>
                        {payload.map((p, i) => p.value ? (
                          <div key={i} style={{ color: p.fill, marginBottom: 2 }}>
                            {p.name}: ${(p.value/1e9).toFixed(2)}B
                          </div>
                        ) : null)}
                      </div>
                    );
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 11, color: C.textMuted }} />
                <Bar dataKey="auto"     name="Automotive" fill={C.chart[0]} stackId="a" />
                <Bar dataKey="energy"   name="Energy"     fill={C.chart[1]} stackId="a" />
                <Bar dataKey="services" name="Services"   fill={C.chart[2]} stackId="a" />
                {/* Fallback total bar when no segment data */}
                {segs.length === 0 && <Bar dataKey="total" name="Total Revenue" fill={C.chart[0]} />}
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </div>
      ) : (
        <Card>
          <EmptyState
            icon="◈"
            title="No financial data yet"
            subtitle="Run the extraction pipeline to populate KPIs and charts."
          />
        </Card>
      )}

      {/* Document count summary */}
      <Card>
        <SectionTitle>Document Corpus</SectionTitle>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 10 }}>
          {[
            ["Quarterly Updates", DOCS.filter(d => d.doc_type === "quarterly_update").length],
            ["Earnings Releases", DOCS.filter(d => d.doc_type === "earnings_release").length],
            ["Annual Reports (10-K)", DOCS.filter(d => d.doc_type === "sec_10k").length],
            ["Quarterly Reports (10-Q)", DOCS.filter(d => d.doc_type === "sec_10q").length],
            ["Current Reports (8-K)", DOCS.filter(d => ["sec_8k","sec_8k_other"].includes(d.doc_type)).length],
            ["Proxy Statements", DOCS.filter(d => d.doc_type === "sec_proxy").length],
            ["Press Releases", DOCS.filter(d => d.doc_type === "press_release").length],
            ["Total Documents", DOCS.length],
          ].map(([label, count]) => (
            <div key={label} style={{ background: C.surface2, borderRadius: 8,
              padding: "12px 16px", border: `1px solid ${C.border}` }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: label === "Total Documents" ? C.accent : C.text }}>
                {count}
              </div>
              <div style={{ fontSize: 11, color: C.textDim, marginTop: 2 }}>{label}</div>
            </div>
          ))}
        </div>
      </Card>

    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// TAB: Financials — metric registry, helpers, components
// ════════════════════════════════════════════════════════════════════════════

const FIN_METRICS = [
  // Revenue
  { id: "revenue_total",         label: "Total Revenue",         cat: "Revenue",       field: "revenue_total",         fmt: "usd", axis: "L", color: "#E31937" },
  { id: "revenue_auto",          label: "Automotive Revenue",    cat: "Revenue",       field: "revenue_auto",          fmt: "usd", axis: "L", color: "#3B82F6" },
  { id: "revenue_energy",        label: "Energy Gen & Storage",  cat: "Revenue",       field: "revenue_energy",        fmt: "usd", axis: "L", color: "#22C55E" },
  { id: "revenue_services",      label: "Services & Other",      cat: "Revenue",       field: "revenue_services",      fmt: "usd", axis: "L", color: "#F59E0B" },
  // Profitability
  { id: "gross_profit",          label: "Gross Profit",          cat: "Profitability", field: "gross_profit",          fmt: "usd", axis: "L", color: "#8B5CF6" },
  { id: "gross_profit_auto",     label: "Auto Gross Profit",     cat: "Profitability", field: "gross_profit_auto",     fmt: "usd", axis: "L", color: "#7C3AED" },
  { id: "op_income",             label: "Operating Income",      cat: "Profitability", field: "op_income",             fmt: "usd", axis: "L", color: "#EC4899" },
  { id: "net_income",            label: "Net Income",            cat: "Profitability", field: "net_income",            fmt: "usd", axis: "L", color: "#14B8A6" },
  { id: "r_and_d",               label: "R&D Expense",           cat: "Profitability", field: "r_and_d",               fmt: "usd", axis: "L", color: "#F97316" },
  { id: "cogs",                  label: "Cost of Revenue",       cat: "Profitability", field: "cogs",                  fmt: "usd", axis: "L", color: "#6B7280" },
  // Margins
  { id: "gross_margin_pct",      label: "Gross Margin %",        cat: "Margins",       field: "gross_margin_pct",      fmt: "pct", axis: "R", color: "#3B82F6" },
  { id: "gross_margin_auto_pct", label: "Auto Gross Margin %",   cat: "Margins",       field: "gross_margin_auto_pct", fmt: "pct", axis: "R", color: "#E31937" },
  { id: "op_margin_pct",         label: "Operating Margin %",    cat: "Margins",       field: "op_margin_pct",         fmt: "pct", axis: "R", color: "#22C55E" },
  { id: "net_margin_pct",        label: "Net Margin %",          cat: "Margins",       field: "net_margin_pct",        fmt: "pct", axis: "R", color: "#F59E0B" },
  // Cash Flow
  { id: "operating_cash_flow",   label: "Operating Cash Flow",   cat: "Cash Flow",     field: "operating_cash_flow",   fmt: "usd", axis: "L", color: "#22C55E" },
  { id: "capex",                 label: "Capital Expenditure",   cat: "Cash Flow",     field: "capex",                 fmt: "usd", axis: "L", color: "#EF4444" },
  { id: "free_cash_flow",        label: "Free Cash Flow",        cat: "Cash Flow",     field: "free_cash_flow",        fmt: "usd", axis: "L", color: "#14B8A6" },
  { id: "cash_end",              label: "Cash & Equivalents",    cat: "Cash Flow",     field: "cash_end",              fmt: "usd", axis: "L", color: "#8B5CF6" },
  // Per Share
  { id: "eps_diluted",           label: "EPS Diluted",           cat: "Per Share",     field: "eps_diluted",           fmt: "eps", axis: "R", color: "#F97316" },
  { id: "eps_basic",             label: "EPS Basic",             cat: "Per Share",     field: "eps_basic",             fmt: "eps", axis: "R", color: "#EC4899" },
];

const FIN_METRICS_BY_ID = Object.fromEntries(FIN_METRICS.map(m => [m.id, m]));
const FIN_METRIC_CATS = [...new Set(FIN_METRICS.map(m => m.cat))];

function enrichFinData(records) {
  return [...records].reverse().map((r, i, arr) => {
    const prev = arr[i - 1] || null;
    const netMgn = r.revenue_total && r.net_income != null
      ? +(r.net_income / r.revenue_total * 100).toFixed(2)
      : null;
    const qoq = {};
    if (prev) {
      FIN_METRICS.forEach(m => {
        const curr = m.id === "net_margin_pct"
          ? (r.revenue_total && r.net_income != null ? +(r.net_income / r.revenue_total * 100).toFixed(2) : null)
          : r[m.field];
        const pv = m.id === "net_margin_pct"
          ? (prev.revenue_total && prev.net_income != null ? +(prev.net_income / prev.revenue_total * 100).toFixed(2) : null)
          : prev[m.field];
        if (curr != null && pv != null && pv !== 0) {
          qoq[m.id] = +((curr - pv) / Math.abs(pv) * 100).toFixed(1);
        }
      });
    }
    return { ...r, net_margin_pct: netMgn, _qoq: qoq };
  }).reverse();
}

function fmtM(v, fmtType) {
  if (v == null) return "—";
  if (fmtType === "pct") return `${v.toFixed(1)}%`;
  if (fmtType === "eps") return `$${v.toFixed(2)}`;
  const abs = Math.abs(v), s = v < 0 ? "-" : "";
  if (abs >= 1e9) return `${s}$${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${s}$${(abs / 1e6).toFixed(0)}M`;
  if (abs >= 1e3) return `${s}$${(abs / 1e3).toFixed(0)}K`;
  return `${s}$${abs.toFixed(0)}`;
}

function cellColor(metricId, value) {
  if (value == null) return C.textDim;
  const marginIds = ["gross_margin_pct", "gross_margin_auto_pct", "op_margin_pct", "net_margin_pct"];
  if (marginIds.includes(metricId)) {
    if (value > 15) return C.positive;
    if (value >= 5) return C.warning;
    return C.negative;
  }
  if (["eps_diluted", "eps_basic", "free_cash_flow", "op_income", "net_income"].includes(metricId)) {
    return value >= 0 ? C.positive : C.negative;
  }
  return C.text;
}

// ── MetricPicker ─────────────────────────────────────────────────────────────

function MetricPicker({ selected, onChange, maxSelect = 6, allData = [] }) {
  const [open, setOpen] = useState(false);

  const hasData = (metricId) => {
    const m = FIN_METRICS_BY_ID[metricId];
    if (!m) return false;
    if (metricId === "net_margin_pct") {
      return allData.some(r => r.net_margin_pct != null);
    }
    return allData.some(r => r[m.field] != null);
  };

  const toggle = (id) => {
    if (selected.includes(id)) {
      onChange(selected.filter(s => s !== id));
    } else if (selected.length < maxSelect) {
      onChange([...selected, id]);
    }
  };

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          background: C.surface2, border: `1px solid ${open ? C.accent : C.border}`,
          borderRadius: 8, padding: "6px 12px", cursor: "pointer",
          color: C.text, fontSize: 13, transition: "border-color 0.15s",
        }}
      >
        <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
          {selected.slice(0, 4).map(id => {
            const m = FIN_METRICS_BY_ID[id];
            return m ? (
              <span key={id} style={{
                width: 8, height: 8, borderRadius: "50%",
                background: m.color, display: "inline-block", flexShrink: 0,
              }} />
            ) : null;
          })}
          {selected.length > 4 && (
            <span style={{ fontSize: 10, color: C.textDim }}>+{selected.length - 4}</span>
          )}
        </div>
        <span style={{ color: C.textMuted }}>{selected.length} metric{selected.length !== 1 ? "s" : ""}</span>
        <span style={{ color: C.textDim, fontSize: 10 }}>{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div
          style={{
            position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 200,
            background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10,
            padding: "10px 0", minWidth: 260, maxHeight: 380, overflowY: "auto",
            boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
          }}
        >
          <div style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: "0 14px 8px", borderBottom: `1px solid ${C.border}`, marginBottom: 6,
          }}>
            <span style={{ fontSize: 11, color: C.textDim, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.07em" }}>
              Select metrics (max {maxSelect})
            </span>
            <button
              onClick={() => onChange([])}
              style={{ fontSize: 11, color: C.textMuted, background: "none", border: "none", cursor: "pointer", padding: 0 }}
            >
              Clear all
            </button>
          </div>

          {FIN_METRIC_CATS.map(cat => (
            <div key={cat}>
              <div style={{
                fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
                textTransform: "uppercase", color: C.textDim,
                padding: "6px 14px 4px",
              }}>
                {cat}
              </div>
              {FIN_METRICS.filter(m => m.cat === cat).map(m => {
                const isSelected = selected.includes(m.id);
                const dataAvail = hasData(m.id);
                const atMax = !isSelected && selected.length >= maxSelect;
                return (
                  <div
                    key={m.id}
                    onClick={() => !atMax && toggle(m.id)}
                    style={{
                      display: "flex", alignItems: "center", gap: 10,
                      padding: "6px 14px", cursor: atMax ? "not-allowed" : "pointer",
                      opacity: atMax ? 0.45 : 1,
                      background: isSelected ? "rgba(255,255,255,0.04)" : "transparent",
                      transition: "background 0.1s",
                    }}
                    onMouseEnter={e => { if (!atMax) e.currentTarget.style.background = "rgba(255,255,255,0.06)"; }}
                    onMouseLeave={e => { e.currentTarget.style.background = isSelected ? "rgba(255,255,255,0.04)" : "transparent"; }}
                  >
                    <span style={{
                      width: 10, height: 10, borderRadius: "50%",
                      background: m.color, flexShrink: 0,
                    }} />
                    <span style={{ flex: 1, fontSize: 13, color: dataAvail ? C.text : C.textDim }}>
                      {m.label}
                      {!dataAvail && <span style={{ fontSize: 11, color: C.textDim, marginLeft: 6 }}>(no data)</span>}
                    </span>
                    <span style={{
                      width: 16, height: 16, borderRadius: 3,
                      border: `1.5px solid ${isSelected ? m.color : C.border}`,
                      background: isSelected ? m.color : "transparent",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      flexShrink: 0, transition: "all 0.1s",
                    }}>
                      {isSelected && <span style={{ fontSize: 10, color: "#fff", lineHeight: 1 }}>✓</span>}
                    </span>
                  </div>
                );
              })}
            </div>
          ))}

          <div style={{ padding: "8px 14px 0", borderTop: `1px solid ${C.border}`, marginTop: 6 }}>
            <button
              onClick={() => setOpen(false)}
              style={{
                width: "100%", padding: "7px 0", borderRadius: 6,
                background: C.surface2, border: `1px solid ${C.border}`,
                color: C.textMuted, fontSize: 12, cursor: "pointer",
              }}
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── ChartCanvas ───────────────────────────────────────────────────────────────

function ChartCanvas({ data, selectedMetrics, chartType, period }) {
  const nQ = period === "all" ? data.length : parseInt(period) || data.length;
  const sliced = data.slice(0, nQ);
  const chartData = [...sliced].reverse();

  const hasLeft  = selectedMetrics.some(id => FIN_METRICS_BY_ID[id]?.axis === "L");
  const hasRight = selectedMetrics.some(id => FIN_METRICS_BY_ID[id]?.axis === "R");

  const fmtLeft  = v => { if (v == null) return ""; const abs = Math.abs(v); const s = v < 0 ? "-" : ""; if (abs >= 1e9) return `${s}$${(abs/1e9).toFixed(0)}B`; if (abs >= 1e6) return `${s}$${(abs/1e6).toFixed(0)}M`; if (abs >= 1e3) return `${s}$${(abs/1e3).toFixed(0)}K`; return `${s}$${abs}`; };
  const fmtRight = v => v == null ? "" : `${v.toFixed(1)}%`;

  const CustomTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null;
    return (
      <div style={{
        background: C.surface2, border: `1px solid ${C.border}`,
        borderRadius: 8, padding: "10px 14px", fontSize: 12,
      }}>
        <div style={{ color: C.textMuted, marginBottom: 7, fontWeight: 600 }}>{label}</div>
        {payload.map((p, i) => {
          const m = FIN_METRICS_BY_ID[p.dataKey];
          if (!m) return null;
          return (
            <div key={i} style={{ color: m.color, marginBottom: 3, display: "flex", justifyContent: "space-between", gap: 16 }}>
              <span>{m.label}</span>
              <span style={{ fontWeight: 600 }}>{fmtM(p.value, m.fmt)}</span>
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <ResponsiveContainer width="100%" height={280}>
      <ComposedChart data={chartData} margin={{ top: 8, right: hasRight ? 60 : 8, left: 8, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={C.border} />
        <XAxis dataKey="quarter" tick={{ fill: C.textDim, fontSize: 11 }} />
        {hasLeft && (
          <YAxis
            yAxisId="L"
            orientation="left"
            tick={{ fill: C.textDim, fontSize: 11 }}
            tickFormatter={fmtLeft}
            width={68}
          />
        )}
        {hasRight && (
          <YAxis
            yAxisId="R"
            orientation="right"
            tick={{ fill: C.textDim, fontSize: 11 }}
            tickFormatter={fmtRight}
            width={48}
          />
        )}
        <Tooltip content={<CustomTooltip />} />
        <Legend wrapperStyle={{ fontSize: 12, color: C.textMuted, paddingTop: 6 }}
          formatter={(value) => {
            const m = FIN_METRICS_BY_ID[value];
            return m ? m.label : value;
          }}
        />
        {selectedMetrics.map(id => {
          const m = FIN_METRICS_BY_ID[id];
          if (!m) return null;
          const yId = m.axis;
          const commonProps = {
            key: id,
            dataKey: id,
            yAxisId: yId,
            stroke: m.color,
            fill: m.color,
            name: id,
          };
          if (chartType === "bar") {
            return <Bar {...commonProps} opacity={0.82} />;
          }
          if (chartType === "area") {
            return (
              <Area
                {...commonProps}
                type="monotone"
                fillOpacity={0.18}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            );
          }
          if (chartType === "composed") {
            if (m.axis === "L") {
              return <Bar {...commonProps} opacity={0.82} />;
            }
            return (
              <Line
                {...commonProps}
                type="monotone"
                strokeWidth={2.5}
                dot={{ r: 3, fill: m.color }}
                connectNulls
              />
            );
          }
          // default: line
          return (
            <Line
              {...commonProps}
              type="monotone"
              strokeWidth={2.5}
              dot={{ r: 3, fill: m.color }}
              connectNulls
            />
          );
        })}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

// ── TabFinancials ─────────────────────────────────────────────────────────────

function TabFinancials() {
  const [selectedMetrics, setSelectedMetrics] = useState(["revenue_total", "gross_margin_pct", "op_margin_pct"]);
  const [chartType, setChartType]             = useState("composed");
  const [period, setPeriod]                   = useState("12");
  const [tableView, setTableView]             = useState("transposed");
  const [visibleCats, setVisibleCats]         = useState(new Set(FIN_METRIC_CATS));
  const [tableSort, setTableSort]             = useState({ col: "quarter", dir: "desc" });
  const [visibleCols, setVisibleCols]         = useState([
    "quarter","revenue_total","gross_profit","gross_margin_pct",
    "op_income","op_margin_pct","net_income","eps_diluted","free_cash_flow","cash_end",
  ]);
  const [showQoQ, setShowQoQ]       = useState(true);
  const [colPickerOpen, setColPickerOpen] = useState(false);
  const [collapsedCats, setCollapsedCats] = useState(new Set());

  const enriched = useMemo(() => enrichFinData(DATA.financials || []), []);

  if (!DATA.financials || DATA.financials.length === 0) {
    return (
      <Card>
        <EmptyState
          icon="$"
          title="No financial data yet"
          subtitle="The extraction pipeline will populate this section from earnings releases and 10-Q/10-K filings."
        />
      </Card>
    );
  }

  const nQ = period === "all" ? enriched.length : parseInt(period) || enriched.length;
  const periodRows = enriched.slice(0, nQ);

  // ── Sorted rows for standard table ──
  const sortedRows = useMemo(() => {
    const rows = [...periodRows];
    rows.sort((a, b) => {
      const m = FIN_METRICS_BY_ID[tableSort.col];
      let av = m ? (tableSort.col === "net_margin_pct" ? a.net_margin_pct : a[m.field]) : a[tableSort.col];
      let bv = m ? (tableSort.col === "net_margin_pct" ? b.net_margin_pct : b[m.field]) : b[tableSort.col];
      if (av == null) av = tableSort.dir === "asc" ? Infinity : -Infinity;
      if (bv == null) bv = tableSort.dir === "asc" ? Infinity : -Infinity;
      if (typeof av === "string") return tableSort.dir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      return tableSort.dir === "asc" ? av - bv : bv - av;
    });
    return rows;
  }, [periodRows, tableSort]);

  const setSort = (col) => {
    setTableSort(s => s.col === col ? { col, dir: s.dir === "asc" ? "desc" : "asc" } : { col, dir: "desc" });
  };

  const toggleCat = (cat) => {
    setVisibleCats(prev => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat); else next.add(cat);
      return next;
    });
  };

  const toggleCollapse = (cat) => {
    setCollapsedCats(prev => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat); else next.add(cat);
      return next;
    });
  };

  const toggleVisCol = (col) => {
    setVisibleCols(prev =>
      prev.includes(col)
        ? prev.length > 1 ? prev.filter(c => c !== col) : prev
        : [...prev, col]
    );
  };

  const btnStyle = (active) => ({
    padding: "5px 12px", borderRadius: 6,
    border: `1px solid ${active ? C.accent : C.border}`,
    background: active ? C.accentSoft : "transparent",
    color: active ? C.accent : C.textMuted,
    fontSize: 12, cursor: "pointer", fontWeight: active ? 700 : 500,
    transition: "all 0.15s",
  });

  // Quarter labels for transposed table (newest first, limited by period)
  const quarterCols = periodRows.map(r => r.quarter);

  // All available metric columns for column picker (excluding "quarter")
  const allMetricCols = FIN_METRICS.map(m => m.id);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      {/* ── Chart Section ── */}
      <Card>
        {/* Controls */}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 16 }}>
          <MetricPicker
            selected={selectedMetrics}
            onChange={setSelectedMetrics}
            maxSelect={6}
            allData={enriched}
          />

          <div style={{ display: "flex", gap: 4, marginLeft: 4 }}>
            {[
              ["composed", "⊞ Composed"],
              ["line",     "— Line"],
              ["bar",      "▌ Bar"],
              ["area",     "◬ Area"],
            ].map(([v, l]) => (
              <button key={v} style={btnStyle(chartType === v)} onClick={() => setChartType(v)}>{l}</button>
            ))}
          </div>

          <div style={{ display: "flex", gap: 4, marginLeft: "auto" }}>
            {[["4","4Q"],["8","8Q"],["12","12Q"],["all","All"]].map(([v, l]) => (
              <button key={v} style={btnStyle(period === v)} onClick={() => setPeriod(v)}>{l}</button>
            ))}
          </div>
        </div>

        <ChartCanvas
          data={enriched}
          selectedMetrics={selectedMetrics}
          chartType={chartType}
          period={period}
        />
      </Card>

      {/* ── Table Section ── */}
      <Card style={{ padding: 0, overflow: "hidden" }}>
        {/* Table controls */}
        <div style={{
          display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
          padding: "14px 20px", borderBottom: `1px solid ${C.border}`,
        }}>
          {/* View toggle */}
          <div style={{ display: "flex", gap: 4 }}>
            <button style={btnStyle(tableView === "transposed")} onClick={() => setTableView("transposed")}>
              ⊞ Tesla Format
            </button>
            <button style={btnStyle(tableView === "rows")} onClick={() => setTableView("rows")}>
              ≡ Quarterly
            </button>
          </div>

          {/* Transposed: category chips */}
          {tableView === "transposed" && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {FIN_METRIC_CATS.map(cat => (
                <button
                  key={cat}
                  onClick={() => toggleCat(cat)}
                  style={{
                    padding: "3px 10px", borderRadius: 12,
                    border: `1px solid ${visibleCats.has(cat) ? C.accent : C.border}`,
                    background: visibleCats.has(cat) ? C.accentSoft : "transparent",
                    color: visibleCats.has(cat) ? C.accent : C.textDim,
                    fontSize: 11, cursor: "pointer", fontWeight: visibleCats.has(cat) ? 700 : 400,
                  }}
                >
                  {cat}
                </button>
              ))}
            </div>
          )}

          {/* Row view: column picker + QoQ toggle */}
          {tableView === "rows" && (
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginLeft: 4 }}>
              <div style={{ position: "relative" }}>
                <button
                  style={btnStyle(colPickerOpen)}
                  onClick={() => setColPickerOpen(o => !o)}
                >
                  Columns ({visibleCols.length})
                </button>
                {colPickerOpen && (
                  <div style={{
                    position: "absolute", top: "calc(100% + 6px)", left: 0, zIndex: 200,
                    background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10,
                    padding: "8px 0", minWidth: 220, maxHeight: 320, overflowY: "auto",
                    boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
                  }}>
                    {/* Quarter always visible */}
                    <div style={{ padding: "4px 14px", fontSize: 12, color: C.textDim }}>
                      <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "default" }}>
                        <input type="checkbox" checked readOnly />
                        <span>Quarter</span>
                      </label>
                    </div>
                    {allMetricCols.map(id => {
                      const m = FIN_METRICS_BY_ID[id];
                      const checked = visibleCols.includes(id);
                      return (
                        <div key={id} style={{ padding: "4px 14px" }}>
                          <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 12, color: C.text }}>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleVisCol(id)}
                            />
                            <span style={{
                              width: 8, height: 8, borderRadius: "50%",
                              background: m.color, display: "inline-block", flexShrink: 0,
                            }} />
                            <span>{m.label}</span>
                          </label>
                        </div>
                      );
                    })}
                    <div style={{ padding: "8px 14px 0", borderTop: `1px solid ${C.border}`, marginTop: 4 }}>
                      <button
                        onClick={() => setColPickerOpen(false)}
                        style={{ width: "100%", padding: "6px 0", borderRadius: 6, background: C.surface2, border: `1px solid ${C.border}`, color: C.textMuted, fontSize: 12, cursor: "pointer" }}
                      >
                        Done
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", fontSize: 12, color: C.textMuted }}>
                <input
                  type="checkbox"
                  checked={showQoQ}
                  onChange={e => setShowQoQ(e.target.checked)}
                  style={{ cursor: "pointer" }}
                />
                Show QoQ
              </label>
            </div>
          )}
        </div>

        {/* ── Transposed Table ── */}
        {tableView === "transposed" && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr>
                  <th style={{
                    position: "sticky", left: 0, zIndex: 2,
                    background: C.surface, borderBottom: `1px solid ${C.border}`,
                    padding: "8px 16px", textAlign: "left", fontSize: 11,
                    color: C.textDim, fontWeight: 700, whiteSpace: "nowrap",
                    minWidth: 180,
                  }}>
                    Metric
                  </th>
                  {quarterCols.map(q => (
                    <th key={q} style={{
                      borderBottom: `1px solid ${C.border}`,
                      padding: "8px 12px", textAlign: "right",
                      fontSize: 11, color: C.textDim, fontWeight: 700, whiteSpace: "nowrap",
                    }}>
                      {q}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {FIN_METRIC_CATS.filter(cat => visibleCats.has(cat)).map(cat => {
                  const metricsInCat = FIN_METRICS.filter(m => m.cat === cat);
                  const collapsed = collapsedCats.has(cat);
                  return (
                    <React.Fragment key={cat}>
                      {/* Category header row */}
                      <tr
                        onClick={() => toggleCollapse(cat)}
                        style={{ cursor: "pointer" }}
                      >
                        <td
                          colSpan={quarterCols.length + 1}
                          style={{
                            background: C.surface2,
                            borderTop: `1px solid ${C.border}`,
                            borderBottom: `1px solid ${C.border}`,
                            padding: "6px 16px",
                            fontSize: 10, fontWeight: 700,
                            letterSpacing: "0.09em", textTransform: "uppercase",
                            color: C.textDim, textAlign: "left",
                          }}
                        >
                          <span style={{ marginRight: 8 }}>{collapsed ? "▶" : "▼"}</span>
                          {cat}
                        </td>
                      </tr>

                      {/* Metric rows */}
                      {!collapsed && metricsInCat.map(m => (
                        <tr key={m.id} style={{ borderBottom: `1px solid ${C.border}` }}>
                          {/* Metric name cell */}
                          <td style={{
                            position: "sticky", left: 0, zIndex: 1,
                            background: C.surface,
                            padding: "7px 16px",
                            fontWeight: 600, color: C.textMuted,
                            whiteSpace: "nowrap", fontSize: 12,
                            borderBottom: `1px solid ${C.border}`,
                          }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                              <span style={{
                                width: 8, height: 8, borderRadius: "50%",
                                background: m.color, flexShrink: 0,
                              }} />
                              {m.label}
                            </div>
                          </td>
                          {/* Value cells */}
                          {periodRows.map(r => {
                            const val = m.id === "net_margin_pct" ? r.net_margin_pct : r[m.field];
                            const qoqVal = r._qoq?.[m.id];
                            const cc = cellColor(m.id, val);
                            return (
                              <td key={r.quarter} style={{
                                padding: "7px 12px", textAlign: "right",
                                borderBottom: `1px solid ${C.border}`,
                                verticalAlign: "top",
                              }}>
                                <div style={{ color: cc, fontWeight: 600, fontSize: 12 }}>
                                  {fmtM(val, m.fmt)}
                                </div>
                                {showQoQ && qoqVal != null && (
                                  <div style={{
                                    fontSize: 10, color: qoqVal >= 0 ? C.positive : C.negative,
                                    marginTop: 1, fontWeight: 500,
                                  }}>
                                    {qoqVal >= 0 ? "+" : ""}{qoqVal.toFixed(1)}%
                                  </div>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* ── Row Table ── */}
        {tableView === "rows" && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr>
                  <th
                    onClick={() => setSort("quarter")}
                    style={{
                      position: "sticky", left: 0, zIndex: 2,
                      background: C.surface, borderBottom: `1px solid ${C.border}`,
                      padding: "8px 16px", textAlign: "left",
                      fontSize: 11, color: C.textDim, fontWeight: 700,
                      cursor: "pointer", whiteSpace: "nowrap", minWidth: 90,
                    }}
                  >
                    Quarter {tableSort.col === "quarter" ? (tableSort.dir === "asc" ? "↑" : "↓") : ""}
                  </th>
                  {visibleCols.filter(c => c !== "quarter").map(colId => {
                    const m = FIN_METRICS_BY_ID[colId];
                    const label = m ? m.label : colId;
                    const isSort = tableSort.col === colId;
                    return (
                      <th
                        key={colId}
                        onClick={() => setSort(colId)}
                        style={{
                          borderBottom: `1px solid ${C.border}`,
                          padding: "8px 12px", textAlign: "right",
                          fontSize: 11, color: isSort ? C.accent : C.textDim,
                          fontWeight: 700, cursor: "pointer", whiteSpace: "nowrap",
                        }}
                      >
                        {m && <span style={{ width: 7, height: 7, borderRadius: "50%", background: m.color, display: "inline-block", marginRight: 5, verticalAlign: "middle" }} />}
                        {label} {isSort ? (tableSort.dir === "asc" ? "↑" : "↓") : ""}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {sortedRows.map(r => (
                  <tr key={r.quarter} style={{ borderBottom: `1px solid ${C.border}` }}>
                    <td style={{
                      position: "sticky", left: 0, zIndex: 1,
                      background: C.surface,
                      padding: "7px 16px", fontWeight: 700, color: C.text,
                      whiteSpace: "nowrap", borderBottom: `1px solid ${C.border}`,
                    }}>
                      {r.quarter}
                    </td>
                    {visibleCols.filter(c => c !== "quarter").map(colId => {
                      const m = FIN_METRICS_BY_ID[colId];
                      const val = colId === "net_margin_pct" ? r.net_margin_pct : (m ? r[m.field] : r[colId]);
                      const qoqVal = r._qoq?.[colId];
                      const cc = m ? cellColor(m.id, val) : C.text;
                      return (
                        <td key={colId} style={{
                          padding: "7px 12px", textAlign: "right",
                          borderBottom: `1px solid ${C.border}`,
                          verticalAlign: "top",
                        }}>
                          <div style={{ color: cc, fontWeight: 500, fontSize: 12 }}>
                            {m ? fmtM(val, m.fmt) : (val ?? "—")}
                          </div>
                          {showQoQ && qoqVal != null && (
                            <div style={{
                              fontSize: 10, color: qoqVal >= 0 ? C.positive : C.negative,
                              marginTop: 1,
                            }}>
                              {qoqVal >= 0 ? "+" : ""}{qoqVal.toFixed(1)}%
                            </div>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// TAB: Operations
// ════════════════════════════════════════════════════════════════════════════

// ── Delivery data helpers ─────────────────────────────────────────────────────

function buildDeliveryRows(rawDeliveries) {
  // Q4 filings report FY totals. Derive Q4 standalone = FY - (Q1+Q2+Q3).
  // For non-Q4 quarters, use values as-is.
  const byQ = {};
  rawDeliveries.forEach(r => { byQ[r.quarter] = r; });

  const rows = [];
  rawDeliveries.forEach(r => {
    if (!r.is_annual_total) {
      rows.push({ ...r, _derived: false });
      return;
    }
    // Q4: try to derive standalone
    const yr = r.quarter.split("-")[1];
    const q1 = byQ[`Q1-${yr}`];
    const q2 = byQ[`Q2-${yr}`];
    const q3 = byQ[`Q3-${yr}`];

    const q4del = (r.total_delivered != null && q1?.total_delivered != null && q2?.total_delivered != null && q3?.total_delivered != null)
      ? r.total_delivered - q1.total_delivered - q2.total_delivered - q3.total_delivered
      : null;
    const q4pro = (r.total_produced != null && q1?.total_produced != null && q2?.total_produced != null && q3?.total_produced != null)
      ? r.total_produced - q1.total_produced - q2.total_produced - q3.total_produced
      : null;
    const q4my3del = (r.my3_delivered != null && q1?.my3_delivered != null && q2?.my3_delivered != null && q3?.my3_delivered != null)
      ? r.my3_delivered - q1.my3_delivered - q2.my3_delivered - q3.my3_delivered
      : null;
    const q4othdel = (r.other_delivered != null && q1?.other_delivered != null && q2?.other_delivered != null && q3?.other_delivered != null)
      ? r.other_delivered - q1.other_delivered - q2.other_delivered - q3.other_delivered
      : null;

    rows.push({
      ...r,
      total_delivered:  q4del  ?? r.total_delivered,
      total_produced:   q4pro  ?? r.total_produced,
      my3_delivered:    q4my3del ?? r.my3_delivered,
      other_delivered:  q4othdel ?? r.other_delivered,
      _derived: q4del != null,
      _annual_total: r.total_delivered,
    });
  });

  // Sort newest first
  rows.sort((a, b) => {
    const [aq, ay] = a.quarter.split("-");
    const [bq, by_] = b.quarter.split("-");
    return (+by_ - +ay) || (+bq.slice(1) - +aq.slice(1));
  });
  return rows;
}

function TabOperations() {
  const rawDel = DATA.deliveries || [];
  const [showAnnual, setShowAnnual] = useState(false);
  const [periods, setPeriods] = useState(16);

  const rows = useMemo(() => buildDeliveryRows(rawDel), [rawDel]);

  if (rawDel.length === 0) {
    return (
      <Card>
        <EmptyState
          icon="◈"
          title="No operational data yet"
          subtitle="Run scraper/extract_deliveries.py to populate delivery and production data."
        />
      </Card>
    );
  }

  // Chart data: non-annual rows reversed (oldest first), limited to periods
  const chartRows = rows
    .filter(r => !r.is_annual_total || r._derived)
    .slice(0, periods)
    .reverse();

  const latest = rows.find(r => r.total_delivered);
  const prev   = rows.filter(r => r.total_delivered && r.quarter !== latest?.quarter)[0];
  const delChg = latest && prev && prev.total_delivered
    ? ((latest.total_delivered - prev.total_delivered) / prev.total_delivered) * 100
    : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      {/* KPI strip */}
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
        <KpiCard
          label={`Latest (${latest?.quarter})`}
          value={latest ? fmt.num(latest.total_delivered) : "—"}
          sub="vehicles delivered"
          change={delChg}
        />
        <KpiCard
          label="Production"
          value={latest ? fmt.num(latest.total_produced) : "—"}
          sub={`${latest?.quarter} produced`}
        />
        <KpiCard
          label="Utilization"
          value={latest?.total_delivered && latest?.total_produced
            ? `${((latest.total_delivered / latest.total_produced) * 100).toFixed(1)}%`
            : "—"}
          sub="delivered / produced"
        />
        <KpiCard
          label="Annual Record"
          value={(() => {
            const annuals = rawDel.filter(r => r.is_annual_total && r.total_delivered);
            return annuals.length ? fmt.num(Math.max(...annuals.map(r => r.total_delivered))) : "—";
          })()}
          sub="best FY total"
        />
      </div>

      {/* Chart */}
      <Card>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <SectionTitle>Deliveries & Production</SectionTitle>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {[8, 16, 24, 37].map(n => (
              <button key={n} onClick={() => setPeriods(n)} style={{
                padding: "3px 10px", borderRadius: 4, fontSize: 11,
                border: `1px solid ${periods === n ? C.accent : C.border}`,
                background: periods === n ? C.accentSoft : "transparent",
                color: periods === n ? C.accent : C.textMuted, cursor: "pointer",
              }}>{n === 37 ? "All" : `${n}Q`}</button>
            ))}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={chartRows}>
            <CartesianGrid strokeDasharray="3 3" stroke={C.border} vertical={false} />
            <XAxis dataKey="quarter" tick={{ fill: C.textDim, fontSize: 10 }} />
            <YAxis tick={{ fill: C.textDim, fontSize: 10 }} tickFormatter={v => `${(v/1000).toFixed(0)}k`} />
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                return (
                  <div style={{ background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8, padding: "10px 14px", fontSize: 12 }}>
                    <div style={{ color: C.textMuted, marginBottom: 6, fontWeight: 600 }}>{label}</div>
                    {payload.map((p, i) => (
                      <div key={i} style={{ color: p.color, marginBottom: 2 }}>
                        {p.name}: {(p.value || 0).toLocaleString()}
                      </div>
                    ))}
                  </div>
                );
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11, color: C.textMuted }} />
            <Bar dataKey="my3_delivered"  name="Model 3/Y"  fill={C.chart[0]} stackId="d" />
            <Bar dataKey="mx_delivered"   name="Model S/X"  fill={C.chart[1]} stackId="d" />
            <Bar dataKey="cybertruck_delivered" name="Cybertruck" fill={C.chart[3]} stackId="d" />
            <Bar dataKey="other_delivered" name="Other"     fill={C.chart[4]} stackId="d" />
            <Line dataKey="total_produced" name="Produced"  stroke={C.accent} strokeWidth={2} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </Card>

      {/* Table */}
      <Card style={{ padding: 0, overflow: "hidden" }}>
        <div style={{
          padding: "14px 20px 10px", borderBottom: `1px solid ${C.border}`,
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <SectionTitle>Delivery & Production by Quarter</SectionTitle>
          <button onClick={() => setShowAnnual(v => !v)} style={{
            fontSize: 11, padding: "3px 10px", borderRadius: 4, cursor: "pointer",
            border: `1px solid ${C.border}`, background: "transparent", color: C.textMuted,
          }}>
            {showAnnual ? "Hide annual rows" : "Show annual rows"}
          </button>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Quarter</th>
                <th style={{ textAlign: "right" }}>Delivered</th>
                <th style={{ textAlign: "right" }}>Model 3/Y</th>
                <th style={{ textAlign: "right" }}>Model S/X</th>
                <th style={{ textAlign: "right" }}>Cybertruck</th>
                <th style={{ textAlign: "right" }}>Other</th>
                <th style={{ textAlign: "right" }}>Produced</th>
                <th style={{ textAlign: "right" }}>Util %</th>
                <th style={{ textAlign: "right" }}>QoQ Chg</th>
              </tr>
            </thead>
            <tbody>
              {rows
                .filter(r => showAnnual ? true : !(r.is_annual_total && !r._derived))
                .map((r, i, arr) => {
                  const prev_ = arr.slice(i+1).find(x => x.total_delivered != null);
                  const chg = r.total_delivered && prev_?.total_delivered
                    ? ((r.total_delivered - prev_.total_delivered) / prev_.total_delivered) * 100
                    : null;
                  const util = r.total_delivered && r.total_produced
                    ? (r.total_delivered / r.total_produced * 100).toFixed(1) + "%"
                    : "—";
                  const isAnnual = r.is_annual_total && !r._derived;
                  return (
                    <tr key={r.quarter} style={{ opacity: isAnnual ? 0.65 : 1 }}>
                      <td style={{ fontWeight: 600, color: C.text }}>
                        {r.quarter}
                        {r._derived && <span style={{ fontSize: 10, color: C.textDim, marginLeft: 4 }}>(derived)</span>}
                        {isAnnual && <span style={{ fontSize: 10, color: C.accent, marginLeft: 4 }}>FY</span>}
                      </td>
                      <td style={{ textAlign: "right", fontWeight: 600 }}>
                        {r.total_delivered != null ? r.total_delivered.toLocaleString() : "—"}
                      </td>
                      <td style={{ textAlign: "right", color: C.textMuted }}>
                        {r.my3_delivered != null ? r.my3_delivered.toLocaleString() : "—"}
                      </td>
                      <td style={{ textAlign: "right", color: C.textMuted }}>
                        {r.mx_delivered != null ? r.mx_delivered.toLocaleString() : "—"}
                      </td>
                      <td style={{ textAlign: "right", color: C.textMuted }}>
                        {r.cybertruck_delivered != null ? r.cybertruck_delivered.toLocaleString() : "—"}
                      </td>
                      <td style={{ textAlign: "right", color: C.textMuted }}>
                        {r.other_delivered != null ? r.other_delivered.toLocaleString() : "—"}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {r.total_produced != null ? r.total_produced.toLocaleString() : "—"}
                      </td>
                      <td style={{ textAlign: "right", color: C.textMuted }}>{util}</td>
                      <td style={{ textAlign: "right",
                        color: chg == null ? C.textDim : chg >= 0 ? C.positive : C.negative }}>
                        {chg != null ? `${chg >= 0 ? "+" : ""}${chg.toFixed(1)}%` : "—"}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </Card>

    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// TAB: Products
// ════════════════════════════════════════════════════════════════════════════

const STATUS_META = {
  production:         { label: "In Production",   color: C.positive, bg: "rgba(34,197,94,0.12)" },
  limited_production: { label: "Limited Prod.",   color: C.warning,  bg: "rgba(245,158,11,0.12)" },
  development:        { label: "Development",     color: C.blue,     bg: "rgba(59,130,246,0.12)" },
  upcoming:           { label: "Upcoming",        color: C.purple,   bg: "rgba(139,92,246,0.12)" },
  active:             { label: "Active",          color: C.positive, bg: "rgba(34,197,94,0.12)" },
};

function StatusBadge({ status }) {
  const m = STATUS_META[status] || { label: status, color: C.textDim, bg: C.surface2 };
  return <Badge label={m.label} color={m.color} bg={m.bg} />;
}

function ProductCard({ item, showPrice = false }) {
  return (
    <Card style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: C.text }}>{item.name}</div>
          {item.segment && (
            <div style={{ fontSize: 11, color: C.textDim, marginTop: 2 }}>{item.segment}</div>
          )}
        </div>
        <StatusBadge status={item.status} />
      </div>
      <div style={{ fontSize: 13, color: C.textMuted, lineHeight: 1.6 }}>{item.description}</div>
      {showPrice && item.price_base_usd && (
        <div style={{ fontSize: 13, color: C.textDim }}>
          From <span style={{ color: C.text, fontWeight: 600 }}>
            ${item.price_base_usd.toLocaleString()}
          </span>
          {item.range_miles && <span> · {item.range_miles} mi range</span>}
        </div>
      )}
      {item.launched && (
        <div style={{ fontSize: 11, color: C.textDim }}>
          Launched {item.launched}{item.refresh ? ` · Refreshed ${item.refresh}` : ""}
        </div>
      )}
    </Card>
  );
}

function TabProducts() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>

      {/* Vehicles */}
      <div>
        <SectionTitle>Vehicle Lineup</SectionTitle>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 14 }}>
          {(DATA.vehicles || []).map(v => <ProductCard key={v.id} item={v} showPrice />)}
        </div>
      </div>

      {/* Energy */}
      <div>
        <SectionTitle>Energy Products</SectionTitle>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 14 }}>
          {(DATA.energy_products || []).map(v => <ProductCard key={v.id} item={v} />)}
        </div>
      </div>

      {/* AI & Software */}
      <div>
        <SectionTitle>AI & Software</SectionTitle>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 14 }}>
          {(DATA.ai_software || []).map(v => <ProductCard key={v.id} item={v} />)}
        </div>
      </div>

    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// TAB: Docs
// ════════════════════════════════════════════════════════════════════════════

const DOC_FILTERS = [
  { key: "all",            label: "All" },
  { key: "quarterly_update", label: "Quarterly Updates" },
  { key: "earnings_release", label: "Earnings Releases" },
  { key: "sec_10k",        label: "10-K Annual" },
  { key: "sec_10q",        label: "10-Q Quarterly" },
  { key: "sec_8k",         label: "8-K Current" },
  { key: "sec_8k_other",   label: "8-K Events" },
  { key: "sec_proxy",      label: "Proxy" },
  { key: "press_release",  label: "Press Releases" },
  { key: "delivery_report",label: "Deliveries" },
  { key: "impact_report",  label: "Impact Reports" },
  { key: "other",          label: "Other" },
];

function TabDocs() {
  const [filter, setFilter]   = useState("all");
  const [search, setSearch]   = useState("");
  const [yearFilter, setYearFilter] = useState("all");
  const [page, setPage]       = useState(0);
  const PAGE_SIZE = 60;

  const years = useMemo(() => {
    const ys = [...new Set(DOCS.map(d => d.year).filter(Boolean))].sort((a, b) => b - a);
    return ys;
  }, []);

  const filtered = useMemo(() => {
    let docs = DOCS;
    if (filter !== "all")     docs = docs.filter(d => d.doc_type === filter);
    if (yearFilter !== "all") docs = docs.filter(d => d.year === parseInt(yearFilter));
    if (search.trim()) {
      const q = search.toLowerCase();
      docs = docs.filter(d =>
        d.display_name.toLowerCase().includes(q) ||
        d.filename.toLowerCase().includes(q) ||
        (d.date || "").includes(q)
      );
    }
    return docs;
  }, [filter, search, yearFilter]);

  const pages    = Math.ceil(filtered.length / PAGE_SIZE);
  const visible  = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  // Reset page when filters change
  const setFilterReset  = useCallback(v => { setFilter(v);     setPage(0); }, []);
  const setYearReset    = useCallback(v => { setYearFilter(v); setPage(0); }, []);
  const setSearchReset  = useCallback(v => { setSearch(v);     setPage(0); }, []);

  const countFor = (key) => key === "all" ? DOCS.length : DOCS.filter(d => d.doc_type === key).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* Filters */}
      <Card style={{ padding: "14px 20px" }}>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {DOC_FILTERS.map(f => (
            <FilterChip
              key={f.key}
              label={f.label}
              count={countFor(f.key)}
              active={filter === f.key}
              onClick={() => setFilterReset(f.key)}
            />
          ))}
        </div>
      </Card>

      {/* Search + Year */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <SearchBox value={search} onChange={setSearchReset} placeholder="Search documents..." />
        <select
          value={yearFilter}
          onChange={e => setYearReset(e.target.value)}
          style={{
            background: C.surface2, border: `1px solid ${C.border}`, borderRadius: 8,
            color: C.text, padding: "8px 12px", fontSize: 13, outline: "none",
          }}
        >
          <option value="all">All years</option>
          {years.map(y => <option key={y} value={y}>{y}</option>)}
        </select>
        <span style={{ fontSize: 12, color: C.textDim, marginLeft: 4 }}>
          {filtered.length} document{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Document grid */}
      {visible.length === 0 ? (
        <Card>
          <EmptyState icon="○" title="No documents match" subtitle="Try adjusting your filters or search." />
        </Card>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 10 }}>
          {visible.map(doc => (
            <a
              key={doc.id}
              href={doc.path}
              target="_blank"
              rel="noopener noreferrer"
              style={{ display: "block", textDecoration: "none" }}
            >
              <Card style={{
                padding: "14px 16px", cursor: "pointer", transition: "border-color 0.15s",
                display: "flex", flexDirection: "column", gap: 8, height: "100%",
                ":hover": { borderColor: C.accent },
              }}
                onMouseEnter={e => e.currentTarget.style.borderColor = C.accent}
                onMouseLeave={e => e.currentTarget.style.borderColor = C.border}
              >
                <div style={{ display: "flex", justifyContent: "space-between",
                  alignItems: "flex-start", gap: 8 }}>
                  <DocTypeBadge type={doc.doc_type} />
                  <Badge
                    label={doc.format}
                    color={doc.format === "PDF" ? "#F59E0B" : "#9CA3AF"}
                    bg={doc.format === "PDF" ? "rgba(245,158,11,0.1)" : C.surface2}
                  />
                </div>
                <div style={{ fontSize: 13, fontWeight: 600, color: C.text, lineHeight: 1.4 }}>
                  {doc.display_name}
                </div>
                <div style={{ fontSize: 11, color: C.textDim }}>
                  {doc.date && <span>{doc.date}</span>}
                  {doc.size_kb > 0 && <span style={{ marginLeft: 8 }}>{doc.size_kb} KB</span>}
                </div>
              </Card>
            </a>
          ))}
        </div>
      )}

      {/* Pagination */}
      {pages > 1 && (
        <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 4 }}>
          <button
            onClick={() => setPage(p => Math.max(0, p - 1))}
            disabled={page === 0}
            style={{ padding: "6px 14px", borderRadius: 6, border: `1px solid ${C.border}`,
              background: "transparent", color: page === 0 ? C.textDim : C.text,
              cursor: page === 0 ? "default" : "pointer", fontSize: 13 }}
          >
            ← Prev
          </button>
          <span style={{ padding: "6px 12px", fontSize: 13, color: C.textMuted }}>
            {page + 1} / {pages}
          </span>
          <button
            onClick={() => setPage(p => Math.min(pages - 1, p + 1))}
            disabled={page === pages - 1}
            style={{ padding: "6px 14px", borderRadius: 6, border: `1px solid ${C.border}`,
              background: "transparent", color: page === pages - 1 ? C.textDim : C.text,
              cursor: page === pages - 1 ? "default" : "pointer", fontSize: 13 }}
          >
            Next →
          </button>
        </div>
      )}

    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// TAB: Feed (placeholder)
// ════════════════════════════════════════════════════════════════════════════

function TabFeed() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Card>
        <EmptyState
          icon="⊡"
          title="Live feed not yet configured"
          subtitle="This tab will show live news, X posts, newsletter items, and analyst commentary once the scraper is configured."
        />
      </Card>
      <Card>
        <SectionTitle>Planned sources</SectionTitle>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {[
            ["X / Twitter",   "Elon Musk, Tesla, ecosystem accounts (user-defined watchlist)"],
            ["RSS / Substack","Newsletters and analyst blogs (user-defined watchlist)"],
            ["Reddit",        "r/TSLA, r/TeslaMotors, r/teslainvestorsclub"],
            ["YouTube",       "Earnings calls, investor days, analyst channels"],
            ["News",          "DuckDuckGo news queries — Tesla, FSD, Robotaxi, Optimus, Dojo"],
          ].map(([type, desc]) => (
            <div key={type} style={{ display: "flex", gap: 14, alignItems: "flex-start",
              padding: "10px 0", borderBottom: `1px solid ${C.border}` }}>
              <div style={{ minWidth: 100 }}>
                <Badge label={type} color={C.textMuted} bg={C.surface2} />
              </div>
              <div style={{ fontSize: 13, color: C.textDim }}>{desc}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// TAB: Inbox (placeholder)
// ════════════════════════════════════════════════════════════════════════════

function TabInbox() {
  return (
    <Card>
      <EmptyState
        icon="⊞"
        title="Extraction queue empty"
        subtitle="When the document extraction pipeline runs, flagged or low-confidence values will appear here for human review before being committed to data.js."
      />
    </Card>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// TAB: Sources (placeholder)
// ════════════════════════════════════════════════════════════════════════════

function TabSources() {
  const execs = DATA.executives || [];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      <Card>
        <SectionTitle>Key People — X Handles</SectionTitle>
        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
          {execs.map(e => (
            <div key={e.name} style={{ display: "flex", justifyContent: "space-between",
              alignItems: "center", padding: "10px 0", borderBottom: `1px solid ${C.border}` }}>
              <div>
                <span style={{ fontWeight: 600, color: C.text }}>{e.name}</span>
                {e.departed && (
                  <Badge label={`Departed ${e.departed}`} color={C.textDim} bg={C.surface2}
                    style={{ marginLeft: 8 }} />
                )}
                <div style={{ fontSize: 12, color: C.textDim, marginTop: 2 }}>{e.title}</div>
              </div>
              {e.x_handle
                ? <Badge label={`@${e.x_handle}`} color={C.blue} bg="rgba(59,130,246,0.12)" />
                : <Badge label="No X handle" color={C.textDim} bg={C.surface2} />
              }
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <EmptyState
          icon="◫"
          title="Full sources config coming soon"
          subtitle="X watchlist, RSS feeds, Reddit subs, YouTube channels, and podcast sources will be configured here."
        />
      </Card>

    </div>
  );
}

// ════════════════════════════════════════════════════════════════════════════
// MAIN APP
// ════════════════════════════════════════════════════════════════════════════

const TABS = [
  { id: "overview",    label: "Overview" },
  { id: "financials",  label: "Financials" },
  { id: "operations",  label: "Operations" },
  { id: "products",    label: "Products" },
  { id: "docs",        label: "Docs" },
  { id: "feed",        label: "Feed" },
  { id: "inbox",       label: "Inbox" },
  { id: "sources",     label: "Sources" },
];

function App() {
  const [tab, setTab] = useState("overview");

  const content = useMemo(() => {
    switch (tab) {
      case "overview":   return <TabOverview />;
      case "financials": return <TabFinancials />;
      case "operations": return <TabOperations />;
      case "products":   return <TabProducts />;
      case "docs":       return <TabDocs />;
      case "feed":       return <TabFeed />;
      case "inbox":      return <TabInbox />;
      case "sources":    return <TabSources />;
      default:           return null;
    }
  }, [tab]);

  return (
    <div style={{ minHeight: "100vh", background: C.bg }}>

      {/* Header */}
      <div style={{
        background: C.surface, borderBottom: `1px solid ${C.border}`,
        padding: "0 28px", position: "sticky", top: 0, zIndex: 100,
      }}>
        <div style={{ display: "flex", alignItems: "center",
          justifyContent: "space-between", height: 56 }}>

          {/* Wordmark */}
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              width: 28, height: 28, background: C.accent, borderRadius: 5,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontWeight: 900, fontSize: 13, color: "#fff", letterSpacing: "-0.5px",
            }}>T</div>
            <div>
              <div style={{ fontWeight: 700, fontSize: 15, letterSpacing: "-0.3px", color: C.text }}>
                Tesla
              </div>
              <div style={{ fontSize: 10, color: C.textDim, letterSpacing: "0.06em",
                textTransform: "uppercase", marginTop: -1 }}>
                Intelligence Dashboard
              </div>
            </div>
          </div>

          {/* Meta */}
          <div style={{ fontSize: 11, color: C.textDim }}>
            {DATA.meta?.last_updated
              ? `Updated ${DATA.meta.last_updated.slice(0, 10)}`
              : "Extraction pipeline not yet run"
            }
            <span style={{ margin: "0 8px", color: C.border }}>|</span>
            <span style={{ color: C.accent }}>{DOCS.length}</span> documents indexed
          </div>
        </div>

        {/* Tab bar */}
        <div style={{ display: "flex", gap: 0, marginTop: 0 }}>
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              style={{
                padding: "10px 18px",
                border: "none", borderBottom: tab === t.id ? `2px solid ${C.accent}` : "2px solid transparent",
                background: "transparent", color: tab === t.id ? C.text : C.textDim,
                fontWeight: tab === t.id ? 600 : 400, fontSize: 13,
                cursor: "pointer", transition: "color 0.15s", whiteSpace: "nowrap",
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div style={{ maxWidth: 1400, margin: "0 auto", padding: "28px 28px 60px" }}>
        {content}
      </div>

    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
