"""
build_map_with_eu.py

Generates the startup map HTML with an EU comparison infopanel on the right.
Reads the Eurostat bd_size TSV (gzipped) for ICT enterprise birth rate data.

USAGE:
  python build_map_with_eu.py \
      --candidates candidates_geocoded.csv \
      --eurostat estat_bd_size_tsv.gz \
      --out startup_map.html
"""

import argparse
import gzip
import json
import math
import re
import sys
import pandas as pd

DELIM = "^"

CATEGORY_COLORS = {
    "product_publishing":      "#a855f7",
    "programming_consultancy": "#3b82f6",
    "data_infrastructure":     "#14b8a6",
}
CATEGORY_LABELS = {
    "product_publishing":      "Software publishing",
    "programming_consultancy": "Programming & consultancy",
    "data_infrastructure":     "Data & web infrastructure",
}

COUNTRY_NAMES = {
    'AT':'Austria','BE':'Belgium','BG':'Bulgaria','CY':'Cyprus','CZ':'Czechia',
    'DE':'Germany','DK':'Denmark','EE':'Estonia','EL':'Greece','ES':'Spain',
    'FI':'Finland','FR':'France','HR':'Croatia','HU':'Hungary','IE':'Ireland',
    'IT':'Italy','LT':'Lithuania','LU':'Luxembourg','LV':'Latvia','MT':'Malta',
    'NL':'Netherlands','PL':'Poland','PT':'Portugal','RO':'Romania',
    'SE':'Sweden','SI':'Slovenia','SK':'Slovakia'
}
EU27 = set(COUNTRY_NAMES.keys())


def process_eurostat(path: str) -> dict:
    """Extract ICT enterprise birth rate data from Eurostat TSV.gz file."""
    print("Processing Eurostat data...", file=sys.stderr)

    opener = gzip.open if path.endswith('.gz') else open
    results = []
    year_idx = {}

    with opener(path, 'rt', encoding='utf-8', errors='replace') as f:
        for i, line in enumerate(f):
            line = line.rstrip('\r\n')
            if i == 0:
                first, *cols = line.split('\t')
                year_idx = {y.strip(): idx for idx, y in enumerate(cols)}
                continue
            parts = line.split('\t')
            dim_str = parts[0]
            values = parts[1:]
            dim_parts = dim_str.split(',')
            if len(dim_parts) < 6:
                continue
            indic = dim_parts[3]
            nace = dim_parts[4]
            geo = dim_parts[5].replace('\\', '').strip()
            if indic != 'ENT_BRTHR_PC':
                continue
            if nace not in {'J', 'J62', 'J63'}:
                continue
            if geo not in EU27:
                continue
            row = {'nace': nace, 'geo': geo}
            for yr in ['2021', '2022', '2023']:
                if yr in year_idx and year_idx[yr] < len(values):
                    val_raw = values[year_idx[yr]].strip()
                    val_clean = re.sub(r'[^0-9.]', '', val_raw)
                    row[yr] = float(val_clean) if val_clean else None
                else:
                    row[yr] = None
            results.append(row)

    # Build summary for NACE J (full ICT sector)
    birth_rate_j = {
        r['geo']: {'2021': r['2021'], '2022': r['2022'], '2023': r['2023']}
        for r in results if r['nace'] == 'J'
    }

    # Rank by 2023 value
    ranked_2023 = sorted(
        [(geo, d['2023']) for geo, d in birth_rate_j.items() if d['2023'] is not None],
        key=lambda x: x[1]
    )

    vals_2023 = [v for _, v in ranked_2023]
    n = len(vals_2023)
    median = vals_2023[n // 2] if n % 2 else (vals_2023[n//2-1] + vals_2023[n//2]) / 2
    avg = sum(vals_2023) / n

    ro_rank_from_top = n - next(i for i, (g, _) in enumerate(ranked_2023) if g == 'RO')
    ro_data = birth_rate_j.get('RO', {})

    print(f"  -> {n} EU countries with 2023 ICT birth rate data", file=sys.stderr)
    print(f"  -> Romania: {ro_data.get('2023', 'N/A')}% (rank {ro_rank_from_top}/{n} from top)", file=sys.stderr)
    print(f"  -> EU median: {median:.2f}%, avg: {avg:.2f}%", file=sys.stderr)

    return {
        'ranked': [
            {
                'geo': geo,
                'country': COUNTRY_NAMES.get(geo, geo),
                'value': val,
                'is_ro': geo == 'RO'
            }
            for geo, val in reversed(ranked_2023)  # highest first
        ],
        'ro': {
            'value_2023': ro_data.get('2023'),
            'value_2022': ro_data.get('2022'),
            'value_2021': ro_data.get('2021'),
            'rank_from_top': ro_rank_from_top,
            'total_countries': n,
        },
        'eu_median': round(median, 2),
        'eu_avg': round(avg, 2),
    }


def safe(val):
    if val is None:
        return ""
    try:
        if math.isnan(float(val)):
            return ""
    except (ValueError, TypeError):
        pass
    return str(val).strip()


def fmt_number(val):
    try:
        n = int(float(val))
        return f"{n:,}".replace(",", ".")
    except (ValueError, TypeError):
        return str(val)


def build_features(df: pd.DataFrame) -> list:
    features = []
    for _, row in df.iterrows():
        try:
            lat = float(row.get("LAT", "") or "")
            lon = float(row.get("LON", "") or "")
        except (ValueError, TypeError):
            continue
        category = safe(row.get("CAEN_CATEGORY", "")) or "uncategorised"
        color = CATEGORY_COLORS.get(category, "#94a3b8")
        name = safe(row.get("DENUMIRE", ""))
        cui = safe(row.get("CUI", ""))
        judet = safe(row.get("ADR_JUDET", ""))
        localitate = safe(row.get("ADR_LOCALITATE", ""))
        strada = safe(row.get("ADR_DEN_STRADA", ""))
        nr = safe(row.get("ADR_NR_STRADA", ""))
        data_inreg = safe(row.get("DATA_INMATRICULARE", ""))[:10]
        salariati = safe(row.get("NR_SALARIATI", ""))
        cifra = safe(row.get("CIFRA_AFACERI", ""))
        profit = safe(row.get("PROFIT_NET", ""))
        geo_precision = safe(row.get("GEO_PRECISION", ""))
        enrichment = safe(row.get("ENRICHMENT_STATUS", "unmatched"))

        address_parts = [p for p in [strada, nr, localitate, judet] if p]
        address = ", ".join(address_parts)

        enr_icons = {
            "verified": "✓", "unmatched": "~", "below_threshold": "✗"
        }
        popup_rows = [
            f"<b style='font-size:14px'>{name}</b>",
            f"<span style='color:#64748b;font-size:11px'>CUI: {cui}</span>",
            f"<span style='background:{color};color:white;padding:2px 7px;"
            f"border-radius:4px;font-size:11px'>"
            f"{CATEGORY_LABELS.get(category, category)}</span>",
        ]
        if data_inreg:
            popup_rows.append(f"📅 {data_inreg}")
        if address:
            popup_rows.append(f"📍 {address}")
        if salariati:
            popup_rows.append(f"👥 {salariati} angajați (2024)")
        if cifra:
            popup_rows.append(f"💰 CA: {fmt_number(cifra)} RON")
        if profit:
            try:
                pval = int(float(profit))
                icon = "📈" if pval >= 0 else "📉"
                popup_rows.append(f"{icon} Profit net: {fmt_number(profit)} RON")
            except (ValueError, TypeError):
                pass
        if geo_precision:
            popup_rows.append(
                f"<span style='color:#94a3b8;font-size:10px'>Precizie: {geo_precision}</span>")

        # Parse year and month from registration date
        year = None
        month = None
        if data_inreg and len(data_inreg) >= 7:
            try:
                parts_d = data_inreg.split("/")
                if len(parts_d) == 3:
                    year = int(parts_d[2][:4])
                    month = int(parts_d[1])
                else:
                    parts_d = data_inreg.split("-")
                    if len(parts_d) == 3:
                        year = int(parts_d[0])
                        month = int(parts_d[1])
            except (ValueError, IndexError):
                pass

        # Normalize county name for display
        judet_norm = judet.replace("MUNICIPIUL ", "").replace("Municipiul ", "").strip()

        features.append({
            "lat": lat, "lon": lon, "color": color,
            "category": category, "enrichment": enrichment,
            "popup": "<br>".join(popup_rows),
            "name": name, "judet": judet, "judet_norm": judet_norm,
            "year": year, "month": month,
        })
    return features


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ro">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Harta Startup-urilor Tech România 2024–2026</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.css"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/MarkerCluster.Default.css"/>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/leaflet.markercluster.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.heat/0.2.0/leaflet-heat.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         display: flex; height: 100vh; overflow: hidden; background: #f8fafc; }

  #map-container { flex: 1; position: relative; min-width: 0; display: flex; flex-direction: column; }
  #map { flex: 1; }

  /* TIMELINE BAR (bottom of map) */
  #timeline {
    background: white; border-top: 1px solid #e2e8f0;
    padding: 10px 16px; display: flex; align-items: center; gap: 12px;
    flex-shrink: 0; z-index: 500;
  }
  #timeline label { font-size: 11px; font-weight: 600; color: #475569; white-space: nowrap; }
  .year-btns { display: flex; gap: 4px; }
  .yr-btn {
    padding: 4px 10px; border-radius: 20px; border: 1px solid #e2e8f0;
    font-size: 11px; font-weight: 600; cursor: pointer; background: white;
    color: #475569; transition: all 0.15s;
  }
  .yr-btn:hover { border-color: #3b82f6; color: #3b82f6; }
  .yr-btn.active { background: #3b82f6; color: white; border-color: #3b82f6; }
  #timeline-count {
    font-size: 11px; color: #94a3b8; margin-left: auto; white-space: nowrap;
  }

  /* LEFT MAP PANEL */
  #map-panel {
    position: absolute; top: 12px; left: 12px; z-index: 1000;
    background: white; border-radius: 12px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.12);
    padding: 14px; width: 236px;
  }
  #map-panel h2 { font-size: 13px; font-weight: 700; color: #1e293b; margin-bottom: 2px; }
  .mp-sub { font-size: 10px; color: #94a3b8; margin-bottom: 10px; }
  .sec-title {
    font-size: 9px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.06em; color: #94a3b8; margin: 10px 0 5px;
  }
  .leg-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 4px 4px; cursor: pointer; border-radius: 6px;
  }
  .leg-row:hover { background: #f8fafc; }
  .leg-left { display: flex; align-items: center; gap: 7px; }
  .dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
  .leg-label { font-size: 11px; color: #334155; }
  .leg-count {
    font-size: 11px; font-weight: 600; color: #1e293b;
    background: #f1f5f9; padding: 1px 6px; border-radius: 8px;
  }
  .total-row {
    display: flex; justify-content: space-between; align-items: center;
    padding-top: 8px; margin-top: 4px; border-top: 1px solid #e2e8f0;
  }
  .total-label { font-size: 11px; font-weight: 600; color: #475569; }
  .total-count { font-size: 13px; font-weight: 700; color: #1e293b; }

  /* County filter */
  #county-search {
    width: 100%; padding: 6px 8px; border: 1px solid #e2e8f0;
    border-radius: 7px; font-size: 11px; outline: none; color: #334155;
    margin-bottom: 4px;
  }
  #county-search:focus { border-color: #3b82f6; }
  #county-list {
    max-height: 110px; overflow-y: auto; border: 1px solid #e2e8f0;
    border-radius: 7px; font-size: 11px;
  }
  .county-item {
    padding: 4px 8px; cursor: pointer; color: #334155;
    border-bottom: 1px solid #f8fafc;
  }
  .county-item:last-child { border-bottom: none; }
  .county-item:hover { background: #eff6ff; }
  .county-item.selected { background: #dbeafe; color: #1d4ed8; font-weight: 600; }
  #county-clear {
    font-size: 10px; color: #94a3b8; cursor: pointer; margin-top: 3px;
    display: none; text-align: right;
  }
  #county-clear:hover { color: #ef4444; }

  /* Heatmap toggle */
  #heatmap-btn {
    width: 100%; padding: 6px; border-radius: 8px;
    border: 1px solid #e2e8f0; background: white;
    font-size: 11px; font-weight: 600; color: #475569;
    cursor: pointer; display: flex; align-items: center;
    justify-content: center; gap: 6px; transition: all 0.15s;
    margin-top: 2px;
  }
  #heatmap-btn:hover { border-color: #f97316; color: #f97316; }
  #heatmap-btn.active { background: #fff7ed; border-color: #f97316; color: #f97316; }

  /* Company search */
  #search-input {
    width: 100%; padding: 6px 8px; border: 1px solid #e2e8f0;
    border-radius: 7px; font-size: 11px; outline: none; color: #334155;
    margin-top: 2px;
  }
  #search-input:focus { border-color: #3b82f6; }
  #search-results { margin-top: 3px; max-height: 100px; overflow-y: auto; }
  .sr-item { padding: 4px 7px; cursor: pointer; border-radius: 5px; font-size: 11px; color: #334155; }
  .sr-item:hover { background: #f1f5f9; }
  .sr-sub { font-size: 10px; color: #94a3b8; }

  /* EU PANEL */
  #eu-panel {
    width: 340px; flex-shrink: 0; background: white;
    border-left: 1px solid #e2e8f0; overflow-y: auto;
    padding: 20px 16px; display: flex; flex-direction: column; gap: 16px;
  }
  .eu-header h1 { font-size: 14px; font-weight: 700; color: #1e293b; margin-bottom: 3px; }
  .eu-header p { font-size: 11px; color: #64748b; line-height: 1.4; }
  .stat-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .stat-card {
    background: #f8fafc; border-radius: 10px; padding: 10px 12px;
    border: 1px solid #e2e8f0;
  }
  .stat-card.highlight { background: #eff6ff; border-color: #bfdbfe; }
  .stat-value { font-size: 22px; font-weight: 800; color: #1e293b; line-height: 1; }
  .stat-value.blue { color: #2563eb; }
  .stat-value.green { color: #16a34a; }
  .stat-label { font-size: 10px; color: #64748b; margin-top: 3px; line-height: 1.3; }
  .trend-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 6px 0; border-bottom: 1px solid #f1f5f9;
  }
  .trend-row:last-child { border-bottom: none; }
  .trend-year { font-size: 11px; color: #64748b; width: 36px; flex-shrink: 0; }
  .trend-bar-wrap { flex: 1; margin: 0 8px; height: 8px; background: #f1f5f9; border-radius: 4px; overflow: hidden; }
  .trend-bar { height: 100%; border-radius: 4px; background: #3b82f6; }
  .trend-val { font-size: 11px; font-weight: 600; color: #2563eb; width: 42px; text-align: right; flex-shrink: 0; }
  .section-label {
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.06em; color: #94a3b8; margin-bottom: 8px;
  }
  .bar-chart { display: flex; flex-direction: column; gap: 3px; }
  .bar-row { display: flex; align-items: center; gap: 6px; }
  .bar-country { font-size: 10px; color: #475569; width: 68px; flex-shrink: 0; text-align: right; }
  .bar-country.ro { color: #2563eb; font-weight: 700; }
  .bar-wrap { flex: 1; height: 14px; background: #f1f5f9; border-radius: 3px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 3px; background: #cbd5e1; }
  .bar-fill.ro { background: #3b82f6; }
  .bar-val { font-size: 10px; color: #64748b; width: 36px; flex-shrink: 0; }
  .bar-val.ro { color: #2563eb; font-weight: 700; }
  .median-line-label { font-size: 10px; color: #d97706; margin-top: 6px; display: flex; align-items: center; gap: 4px; }
  .source-note { font-size: 9px; color: #94a3b8; line-height: 1.4; padding-top: 8px; border-top: 1px solid #f1f5f9; }
  .leaflet-popup-content { min-width: 220px; font-size: 13px; line-height: 1.7; }
  .leaflet-popup-content b { display: block; margin-bottom: 4px; }
</style>
</head>
<body>

<!-- MAP SIDE -->
<div id="map-container">
  <div id="map"></div>

  <!-- TIMELINE (bottom) -->
  <div id="timeline">
    <label>📅 An înregistrare:</label>
    <div class="year-btns">
      <button class="yr-btn active" onclick="setYear(null)">Toți</button>
      <button class="yr-btn" onclick="setYear(2024)">2024</button>
      <button class="yr-btn" onclick="setYear(2025)">2025</button>
      <button class="yr-btn" onclick="setYear(2026)">2026</button>
    </div>
    <span id="timeline-count"></span>
  </div>

  <!-- LEFT PANEL -->
  <div id="map-panel">
    <h2>🗺️ Startup-uri Tech România</h2>
    <div class="mp-sub">SRL/SA înregistrate 2024–2026 • ONRC + MFP</div>

    <div class="sec-title">Categorie CAEN</div>
    <div class="leg-row" onclick="toggleCat('product_publishing')">
      <div class="leg-left">
        <div class="dot" style="background:#a855f7" id="dot-product_publishing"></div>
        <div class="leg-label">Software publishing</div>
      </div>
      <div class="leg-count" id="cnt-product_publishing">—</div>
    </div>
    <div class="leg-row" onclick="toggleCat('programming_consultancy')">
      <div class="leg-left">
        <div class="dot" style="background:#3b82f6" id="dot-programming_consultancy"></div>
        <div class="leg-label">Programming &amp; consultancy</div>
      </div>
      <div class="leg-count" id="cnt-programming_consultancy">—</div>
    </div>
    <div class="leg-row" onclick="toggleCat('data_infrastructure')">
      <div class="leg-left">
        <div class="dot" style="background:#14b8a6" id="dot-data_infrastructure"></div>
        <div class="leg-label">Data &amp; web infra</div>
      </div>
      <div class="leg-count" id="cnt-data_infrastructure">—</div>
    </div>
    <div class="total-row">
      <span class="total-label">Total afișat</span>
      <span class="total-count" id="cnt-total">—</span>
    </div>

    <div class="sec-title">Filtru județ</div>
    <input type="text" id="county-search" placeholder="Caută județ...">
    <div id="county-list"></div>
    <div id="county-clear" onclick="clearCounty()">✕ Elimină filtru județ</div>

    <div class="sec-title">Vizualizare</div>
    <button id="heatmap-btn" onclick="toggleHeatmap()">🌡️ Heatmap densitate</button>

    <div class="sec-title">Caută companie</div>
    <input type="text" id="search-input" placeholder="Nume sau județ...">
    <div id="search-results"></div>
  </div>
</div>

<!-- EU PANEL -->
<div id="eu-panel">
  <div class="eu-header">
    <h1>📊 Context European</h1>
    <p>Rata de înregistrare a noilor companii ICT (NACE J) față de celelalte state membre UE — 2023</p>
  </div>
  <div>
    <div class="section-label">România în cifre</div>
    <div class="stat-cards" id="stat-cards"></div>
  </div>
  <div>
    <div class="section-label">Tendință România (NACE J)</div>
    <div id="trend-chart"></div>
  </div>
  <div>
    <div class="section-label">Clasament UE27 — Rata naștere companii ICT 2023</div>
    <div class="bar-chart" id="bar-chart"></div>
    <div class="median-line-label">
      <span style="display:inline-block;width:12px;height:3px;background:#fbbf24;border-radius:2px"></span>
      Mediana UE27
    </div>
  </div>
  <div class="source-note">
    Sursa date EU: Eurostat, Business demography by size class and NACE Rev.2 (bd_size), 2023.<br>
    Indicatorul ENT_BRTHR_PC = rata naștere întreprinderi (noi firme / firme active × 100).<br>
    Sursa date harta: ONRC + MFP via data.gov.ro.
  </div>
</div>

<script>
const MAP_DATA = __MAP_DATA__;
const EU_DATA  = __EU_DATA__;
const COUNTIES = __COUNTIES__;

// ── STATE ─────────────────────────────────────────────────────
const state = {
  catVisible: { product_publishing:true, programming_consultancy:true, data_infrastructure:true },
  selectedCounty: null,
  selectedYear: null,
  heatmapOn: false,
};

// ── MAP SETUP ─────────────────────────────────────────────────
const map = L.map('map', { preferCanvas: true }).setView([45.9432, 24.9668], 7);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  maxZoom: 19,
}).addTo(map);

const COLORS = {
  product_publishing: '#a855f7',
  programming_consultancy: '#3b82f6',
  data_infrastructure: '#14b8a6',
  uncategorised: '#94a3b8',
};

function makeIcon(color) {
  return L.divIcon({
    className: '',
    html: `<div style="width:9px;height:9px;border-radius:50%;background:${color};
           border:1.5px solid rgba(255,255,255,0.9);
           box-shadow:0 1px 4px rgba(0,0,0,0.35)"></div>`,
    iconSize:[9,9], iconAnchor:[4,4],
  });
}

// Build cluster groups per category
const clusterGroups = {};
Object.keys(COLORS).forEach(cat => {
  clusterGroups[cat] = L.markerClusterGroup({
    maxClusterRadius: 50,
    iconCreateFunction(cluster) {
      const c = COLORS[cat]||'#94a3b8';
      const n = cluster.getChildCount();
      const s = n>100?42:n>30?34:26;
      return L.divIcon({
        html: `<div style="width:${s}px;height:${s}px;border-radius:50%;background:${c};
               color:white;display:flex;align-items:center;justify-content:center;
               font-size:${s>34?13:11}px;font-weight:700;border:2px solid white;
               box-shadow:0 2px 8px rgba(0,0,0,0.25)">${n}</div>`,
        className:'', iconSize:[s,s], iconAnchor:[s/2,s/2],
      });
    }
  });
});

// Build marker objects (don't add to map yet)
const allMarkers = MAP_DATA.map(d => {
  const cat = d.category||'uncategorised';
  const marker = L.marker([d.lat, d.lon], {icon: makeIcon(COLORS[cat]||'#94a3b8')})
    .bindPopup(d.popup, {maxWidth:300});
  marker._data = d;
  return marker;
});

// Heatmap layer
let heatLayer = null;

// ── FILTER & RENDER ───────────────────────────────────────────
function getVisible() {
  return allMarkers.filter(m => {
    const d = m._data;
    if (!state.catVisible[d.category]) return false;
    if (state.selectedCounty && d.judet_norm !== state.selectedCounty) return false;
    if (state.selectedYear && d.year !== state.selectedYear) return false;
    return true;
  });
}

function applyFilters() {
  const visible = getVisible();

  // Clear all cluster groups
  Object.values(clusterGroups).forEach(cl => {
    if (map.hasLayer(cl)) map.removeLayer(cl);
    cl.clearLayers();
  });

  // Repopulate with visible markers
  visible.forEach(m => {
    const cat = m._data.category || 'uncategorised';
    if (clusterGroups[cat]) clusterGroups[cat].addLayer(m);
  });

  // Add visible cluster groups back to map
  const cats = Object.keys(state.catVisible);
  cats.forEach(cat => {
    if (state.catVisible[cat] && clusterGroups[cat].getLayers().length > 0) {
      map.addLayer(clusterGroups[cat]);
    }
  });

  // Update heatmap
  if (state.heatmapOn) {
    if (heatLayer) map.removeLayer(heatLayer);
    const pts = visible.map(m => [m._data.lat, m._data.lon, 0.6]);
    heatLayer = L.heatLayer(pts, {radius:25, blur:15, maxZoom:14}).addTo(map);
  }

  updateCounts(visible);
}

function updateCounts(visible) {
  const catCounts = {};
  visible.forEach(m => {
    const cat = m._data.category||'uncategorised';
    catCounts[cat] = (catCounts[cat]||0) + 1;
  });

  let total = 0;
  ['product_publishing','programming_consultancy','data_infrastructure'].forEach(cat => {
    const n = catCounts[cat]||0;
    const el = document.getElementById('cnt-'+cat);
    const dot = document.getElementById('dot-'+cat);
    if (el) el.textContent = n.toLocaleString('ro');
    const vis = state.catVisible[cat];
    if (el) el.style.opacity = vis?'1':'0.3';
    if (dot) dot.style.opacity = vis?'1':'0.3';
    if (vis) total += n;
  });
  document.getElementById('cnt-total').textContent = total.toLocaleString('ro');
  document.getElementById('timeline-count').textContent =
    `${visible.length.toLocaleString('ro')} companii`;
}

// ── CATEGORY TOGGLE ───────────────────────────────────────────
function toggleCat(cat) {
  state.catVisible[cat] = !state.catVisible[cat];
  applyFilters();
}

// ── TIMELINE ──────────────────────────────────────────────────
function setYear(yr) {
  state.selectedYear = yr;
  document.querySelectorAll('.yr-btn').forEach(b => b.classList.remove('active'));
  const btns = document.querySelectorAll('.yr-btn');
  const idx = yr === null ? 0 : yr - 2023;
  if (btns[idx]) btns[idx].classList.add('active');
  applyFilters();
}

// ── COUNTY FILTER ─────────────────────────────────────────────
function renderCountyList(filter) {
  const list = document.getElementById('county-list');
  const q = (filter||'').toLowerCase();
  const shown = COUNTIES.filter(c => !q || c.toLowerCase().includes(q));
  list.innerHTML = shown.map(c =>
    `<div class="county-item${state.selectedCounty===c?' selected':''}"
          onclick="selectCounty('${c.replace(/'/g,"\\'")}')">
       ${c}
     </div>`
  ).join('');
}

function selectCounty(name) {
  if (state.selectedCounty === name) {
    state.selectedCounty = null;
  } else {
    state.selectedCounty = name;
  }
  const clearEl = document.getElementById('county-clear');
  clearEl.style.display = state.selectedCounty ? 'block' : 'none';
  renderCountyList(document.getElementById('county-search').value);
  applyFilters();
}

function clearCounty() {
  state.selectedCounty = null;
  document.getElementById('county-clear').style.display = 'none';
  document.getElementById('county-search').value = '';
  renderCountyList('');
  applyFilters();
}

document.getElementById('county-search').addEventListener('input', function() {
  renderCountyList(this.value);
});

// ── HEATMAP TOGGLE ────────────────────────────────────────────
function toggleHeatmap() {
  state.heatmapOn = !state.heatmapOn;
  const btn = document.getElementById('heatmap-btn');
  btn.classList.toggle('active', state.heatmapOn);

  if (!state.heatmapOn && heatLayer) {
    map.removeLayer(heatLayer);
    heatLayer = null;
  }
  applyFilters();
}

// ── COMPANY SEARCH ────────────────────────────────────────────
document.getElementById('search-input').addEventListener('input', function() {
  const q = this.value.toLowerCase().trim();
  const res = document.getElementById('search-results');
  res.innerHTML = '';
  if (q.length < 2) return;
  const hits = allMarkers
    .filter(m => m._data.name.toLowerCase().includes(q) || m._data.judet.toLowerCase().includes(q))
    .slice(0,10);
  if (!hits.length) {
    res.innerHTML = '<div class="sr-item" style="color:#94a3b8">Niciun rezultat</div>';
    return;
  }
  hits.forEach(m => {
    const el = document.createElement('div');
    el.className = 'sr-item';
    el.innerHTML = `${m._data.name}<div class="sr-sub">${m._data.judet_norm||m._data.judet}</div>`;
    el.onclick = () => {
      map.setView(m.getLatLng(), 16); m.openPopup();
      res.innerHTML = ''; document.getElementById('search-input').value = '';
    };
    res.appendChild(el);
  });
});

// ── EU PANEL ──────────────────────────────────────────────────
const ro = EU_DATA.ro;
const median = EU_DATA.eu_median;
const ranked = EU_DATA.ranked;

document.getElementById('stat-cards').innerHTML = `
  <div class="stat-card highlight">
    <div class="stat-value blue">${ro.value_2023}%</div>
    <div class="stat-label">Rata naștere ICT<br>România 2023</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">${median}%</div>
    <div class="stat-label">Mediana UE27<br>2023</div>
  </div>
  <div class="stat-card highlight">
    <div class="stat-value green">${ro.rank_from_top}</div>
    <div class="stat-label">Locul din ${ro.total_countries}<br>state membre UE</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">${((ro.value_2023/median-1)*100).toFixed(0)}%</div>
    <div class="stat-label">Peste mediana<br>UE27</div>
  </div>
`;

const years = [
  {yr:'2021', val:ro.value_2021},
  {yr:'2022', val:ro.value_2022},
  {yr:'2023', val:ro.value_2023},
];
const maxTrend = Math.max(...years.map(y=>y.val||0));
document.getElementById('trend-chart').innerHTML = years.map(y=>`
  <div class="trend-row">
    <span class="trend-year">${y.yr}</span>
    <div class="trend-bar-wrap">
      <div class="trend-bar" style="width:${(y.val/maxTrend*100).toFixed(1)}%"></div>
    </div>
    <span class="trend-val">${y.val?y.val.toFixed(2)+'%':'N/A'}</span>
  </div>
`).join('');

const maxBar = Math.max(...ranked.map(r=>r.value||0));
document.getElementById('bar-chart').innerHTML = ranked.map(r=>`
  <div class="bar-row">
    <span class="bar-country${r.is_ro?' ro':''}">${r.country}</span>
    <div class="bar-wrap">
      <div class="bar-fill${r.is_ro?' ro':''}" style="width:${(r.value/maxBar*100).toFixed(1)}%"></div>
    </div>
    <span class="bar-val${r.is_ro?' ro':''}">${r.value?r.value.toFixed(1)+'%':'N/A'}</span>
  </div>
`).join('');

// ── INIT ──────────────────────────────────────────────────────
renderCountyList('');
applyFilters();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--eurostat", required=True, help="estat_bd_size_tsv.gz")
    ap.add_argument("--out", default="startup_map.html")
    args = ap.parse_args()

    print("Loading geocoded candidates...", file=sys.stderr)
    df = pd.read_csv(
        args.candidates, sep=DELIM, dtype=str,
        encoding="utf-8", keep_default_na=False,
        engine="python", on_bad_lines="warn",
    )
    df.columns = [c.strip() for c in df.columns]
    print(f"  -> {len(df):,} rows", file=sys.stderr)

    features = build_features(df)
    print(f"  -> {len(features):,} map markers", file=sys.stderr)
    for cat, label in CATEGORY_LABELS.items():
        n = sum(1 for f in features if f["category"] == cat)
        print(f"     {label}: {n:,}", file=sys.stderr)

    eu_data = process_eurostat(args.eurostat)

    # Build sorted county list for filter
    counties = sorted(set(
        f["judet_norm"] for f in features if f.get("judet_norm")
    ))

    html = HTML_TEMPLATE
    html = html.replace("__MAP_DATA__", json.dumps(features, ensure_ascii=False))
    html = html.replace("__EU_DATA__", json.dumps(eu_data, ensure_ascii=False))
    html = html.replace("__COUNTIES__", json.dumps(counties, ensure_ascii=False))

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  -> written to {args.out}", file=sys.stderr)
    print(f"Open {args.out} in your browser!", file=sys.stderr)


if __name__ == "__main__":
    main()
