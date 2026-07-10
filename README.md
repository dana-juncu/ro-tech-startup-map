# StartUpMap Romania 🗺️

An interactive map of newly registered tech companies in Romania (2024–2026), built from official open government data, with EU benchmarking context.

![Map preview showing tech company distribution across Romania with EU comparison panel](preview.png)

---

## What this shows

Romania ranks **6th out of 27 EU member states** for ICT enterprise birth rate (17.28% in 2023, against an EU median of 12.23%). This project makes that story visible at street level — mapping every newly registered software, programming, and data company in Romania across 2024–2026, sourced entirely from public government datasets.

The map lets you explore:
- Where tech companies are being founded across Romania's counties and cities
- How the distribution breaks down by activity type (software publishing, programming & consultancy, data & web infrastructure)
- How Romania's startup formation rate compares to every other EU country
- Year-by-year registration trends (2024 / 2025 / 2026)

---

## Data sources

All data is open and freely available under Romanian and EU open data licenses.

| Source | Dataset | Used for |
|--------|---------|----------|
| [ONRC via data.gov.ro](https://data.gov.ro/organization/onrc) | `OD_FIRME.csv`, `OD_STARE_FIRMA.csv`, `OD_CAEN_AUTORIZAT.csv` | Company registry: name, address, legal form, registration date, activity codes |
| [MFP via data.gov.ro](https://data.gov.ro/organization/mfp) | `WEB_BL_BS_SL_AN2024.txt` | 2024 annual financial statements: employee count, revenue, profit |
| [Eurostat](https://ec.europa.eu/eurostat/databrowser/view/BD_SIZE) | `bd_size` (ENT_BRTHR_PC, NACE J) | ICT enterprise birth rates across EU27, 2021–2023 |
| [OpenStreetMap / Nominatim](https://nominatim.openstreetmap.org/) | — | Street-level geocoding of company addresses |

---

## Filtering methodology

Starting from the full ONRC registry (~688MB), companies are filtered through four sequential criteria:

**1. Legal form** — SRL (private limited) and SA (joint-stock) only. Excludes sole traders (PF, PFA, II), family enterprises (IF), and other non-company forms that dominate the "noise" in raw registration data.

**2. CAEN activity codes** — Only companies whose registered primary or secondary activity falls in:

| Category | CAEN Rev.3 codes | CAEN Rev.2 equivalents |
|----------|-----------------|----------------------|
| Software publishing | 5821, 5829 | 7221, 7222 |
| Programming & consultancy | 6201, 6202, 6203, 6209 | 7210, 7220, 7260 |
| Data & web infrastructure | 6311, 6312 | 7230, 7240 |

Both CAEN revisions are matched since the national registry mixes them depending on when a company last updated its filing.

**3. Active status** — Companies with any terminal status event (dissolved, bankrupt, struck off, in liquidation) in their ONRC history are excluded.

**4. Registration window** — 2024-01-01 to 2026-06-30.

**Financial enrichment** — Candidates are joined against MFP 2024 financial statements by CUI (tax ID). Where a match exists, employee count, revenue, and net profit are added. Companies with ≥3 employees in 2024 are marked `verified`; unmatched companies (typically 2025–2026 registrations, too new to have filed) are marked `unmatched`; matched but below threshold are `below_threshold`.

---

## Pipeline

```
od_firme.csv ──────────────────────────────────┐
od_stare_firma.csv ─── filter_romania_startups.py ──► candidates_2024plus.csv
od_caen_autorizat.csv ─────────────────────────┘
                                                           │
WEB_BL_BS_SL_AN2024.txt ── enrich_with_financials.py ────► candidates_enriched.csv
                                                           │
Nominatim ────────────────── geocode_candidates.py ────────► candidates_geocoded.csv
                                                           │
estat_bd_size.tsv.gz ───── build_map_with_eu.py ──────────► startup_map.html
```

---

## Running it yourself

**Requirements**
```
Python 3.10+
pip install pandas requests
```

**Step 1 — Download the source data**

From [data.gov.ro/organization/onrc](https://data.gov.ro/organization/onrc), download the most recent snapshot:
- `OD_FIRME.CSV`
- `OD_STARE_FIRMA.CSV`
- `OD_CAEN_AUTORIZAT.CSV`
- The CAEN nomenclature file (rename to `n_caen.csv`)

From [data.gov.ro/organization/mfp](https://data.gov.ro/organization/mfp), under "Situatii financiare 2024 actualizat":
- `WEB_BL_BS_SL_AN2024.txt`

From [Eurostat bd_size](https://ec.europa.eu/eurostat/databrowser/view/BD_SIZE):
- Download as TSV (compressed) → `estat_bd_size.tsv.gz`

**Step 2 — Filter**
```bash
python filter_romania_startups.py \
  --firme OD_FIRME.csv \
  --stare OD_STARE_FIRMA.csv \
  --caen_autorizat OD_CAEN_AUTORIZAT.csv \
  --from-date 2024-01-01 \
  --to-date 2026-06-30 \
  --out candidates_2024plus.csv
```

**Step 3 — Enrich with financials**
```bash
python enrich_with_financials.py \
  --candidates candidates_2024plus.csv \
  --financials WEB_BL_BS_SL_AN2024.txt \
  --min-employees 3 \
  --out candidates_enriched.csv
```

**Step 4 — Geocode** *(takes ~60–90 min for full dataset; resumes from cache if interrupted)*
```bash
python geocode_candidates.py \
  --candidates candidates_enriched.csv \
  --out candidates_geocoded.csv
```

**Step 5 — Build the map**
```bash
python build_map_with_eu.py \
  --candidates candidates_geocoded.csv \
  --eurostat estat_bd_size.tsv.gz \
  --out startup_map.html
```

Open `startup_map.html` in any browser. No server required.

---

## Map features

- **Category filter** — toggle Software publishing, Programming & consultancy, Data & web infrastructure independently
- **County filter** — searchable list of all județe; click to filter map to a single county
- **Year timeline** — filter by registration year (2024 / 2025 / 2026)
- **Heatmap toggle** — switch between individual company pins and a density heatmap
- **Company search** — search by company name or county
- **EU comparison panel** — Romania's ICT enterprise birth rate ranked against all 27 EU member states (Eurostat 2023 data), with 2021–2023 trend

---

## Caveats

- **Address accuracy varies.** ~59% of companies are geocoded to street level; ~11% fall back to postal code; ~16% to city/locality. A small number of Bucharest addresses use sector centroids when street-level resolution fails.
- **CAEN codes are self-declared** at registration. A company can register under a tech CAEN code and operate in an unrelated field, and vice versa. The CAEN filter is a necessary approximation, not a guarantee of actual activity.
- **Financial data coverage is incomplete for 2025–2026 registrations.** Companies registered after mid-2024 won't have filed 2024 annual statements yet. The `ENRICHMENT_STATUS` column distinguishes verified, unmatched, and below-threshold companies.
- **The ONRC snapshot is point-in-time.** Companies that changed status after the snapshot date may appear active when they are not.

---

## Author

Built by [Dana Juncu](https://github.com/dana-juncu) — Senior Product Manager at Diconium, working at the intersection of data, product, and the Romanian tech ecosystem.

Data sourced from ONRC, MFP, and Eurostat under open data licenses. Map tiles © OpenStreetMap contributors.
