# CPO Competitiveness Monitor

A monthly automated data pipeline that tracks crude palm oil (CPO) price competitiveness across biodiesel economics and substitute vegetable oils. Build as a data engineering portfolio project

**Live dashboard:** _[coming soon]_

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                             │
│                                                                 │
│  World Bank       yfinance          USDA FAS          FAO       │
│  Pink Sheet       (daily)           PSD Oilseeds      FFPI      │
│  (monthly)                          (annual)          (monthly) │
└──────┬──────────────┬───────────────────┬──────────────┬────────┘
       │              │                   │              │
       ▼              ▼                   ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    EXTRACT  (src/extract/)                      │
│   extract_worldbank.py  extract_yfinance.py  extract_usda.py    │
│   extract_fao.py                                                │
└─────────────────────────────┬───────────────────────────────────┘
                              │  4 DataFrames
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  LOAD  (src/load.py)                            │
│   Upsert into Supabase PostgreSQL — raw schema                  │
│                                                                 │
│   raw.wb_prices        raw.yfinance_daily                       │
│   raw.usda_indonesia   raw.fao_ffpi                             │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                 TRANSFORM  (src/transform/)                     │
│                                                                 │
│   transform_prices.py    — resample futures daily → monthly     │
│   transform_currency.py  — invert FX, build competitiveness idx │
│   transform_usda.py      — forward-fill annual → monthly        │
│   transform_spreads.py   — POGO spread, z-score, sub. spreads   │
│                                                                 │
│   Writes to Supabase — clean schema                             │
│   clean.commodity_prices   clean.currency_rates                 │
│   clean.indonesia_supply   clean.all_spreads                    │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DBT  (dbt/models/)                           │
│                                                                 │
│   staging/  — thin type-cast wrappers over clean tables         │
│   mart/     — panel-specific tables for the dashboard           │
│                                                                 │
│   mart.mart_indonesia_policy_tracker                            │
│   mart.mart_biodiesel_demand_signal                             │
│   mart.mart_oil_substitution_spreads                            │
│   mart.mart_cpo_competitiveness  (master summary)               │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              DASHBOARD  (dashboard/)                            │
│   Streamlit — reads from mart tables                            │
│   Panel 1: Indonesia Biodiesel Policy Tracker                   │
│   Panel 2: Biodiesel Demand Signal & Price Cycle                │
│   Panel 3: Oil Substitution Spreads                             │
└─────────────────────────────────────────────────────────────────┘

Automated via GitHub Actions — runs on the 5th of every month
```

---

## Data Sources

| Source | What it provides | Granularity | Method |
|---|---|---|---|
| [World Bank Pink Sheet](https://www.worldbank.org/en/research/commodity-markets) | CPO, soybean oil, sunflower oil, rapeseed oil prices (USD/tonne) | Monthly | Direct Excel download |
| [yfinance](https://github.com/ranaroussi/yfinance) | Brent crude (BZ=F), soybean futures (ZS=F), MYR/IDR/INR/CNY FX rates | Daily → resampled monthly | yfinance API |
| [USDA FAS PSD](https://apps.fas.usda.gov/psdonline/) | Indonesia palm oil production, exports, biodiesel consumption, ending stocks | Annual → forward-filled monthly | Bulk CSV zip |
| [FAO FFPI](https://www.fao.org/worldfoodsituation/foodpricesindex/en/) | Global vegetable oils price sub-index | Monthly | CSV download |

**Date range:** January 2015 → present (updated monthly)

---

## Metrics Calculated

### POGO Spread
Measures the cost gap between CPO and its gas oil substitute in biodiesel blending.

```
gas_oil_equivalent = brent_crude_usd × 7.3   (barrels per metric tonne)
pogo_spread        = cpo_price − gas_oil_equivalent
```

| Zone | Condition | Meaning |
|---|---|---|
| PROFITABLE | spread < 0 | CPO cheaper than gas oil — biodiesel is self-funding |
| MARGINAL | 0 ≤ spread < 150 | Small subsidy burden — mandate is politically sustainable |
| COSTLY | spread ≥ 150 | Large gap — mandate requires heavy government fund coverage |

### CPO Price Cycle (36-month rolling z-score)
```
z = (cpo_price − 36-month rolling mean) / 36-month rolling std
```

| Position | Condition |
|---|---|
| EXPENSIVE | z > 1 |
| FAIR | −1 ≤ z ≤ 1 |
| CHEAP | z < −1 |
| INSUFFICIENT DATA | first 35 months (burn-in) |

### Substitution Risk
Based on CPO vs soybean oil spread only (primary global benchmark).

```
cpo_vs_soy_spread = cpo_price − soyoil_price
```

| Risk | Condition | Meaning |
|---|---|---|
| HIGH | spread > −50 | CPO close to soy price — buyers may switch |
| MODERATE | −100 < spread ≤ −50 | Moderate discount — some risk |
| LOW | spread ≤ −100 | CPO much cheaper — buyers stay with CPO |

### Currency Competitiveness Index
MYR and IDR indexed to 100 at January 2015. A value above 100 means the currency has weakened against the USD since the base period, which benefits CPO revenues when converted back to local currency.

---

## Project Structure
 
```
├── main.py                      # pipeline entry point
├── config.yml                   # all thresholds, tickers, start date
├── requirements.txt
│
├── src/
│   ├── extract/
│   │   ├── extract_worldbank.py
│   │   ├── extract_yfinance.py
│   │   ├── extract_usda.py
│   │   └── extract_fao.py
│   ├── transform/
│   │   ├── transform_prices.py    # resample futures daily → monthly
│   │   ├── transform_currency.py  # invert FX, build competitiveness index
│   │   ├── transform_usda.py      # forward-fill annual → monthly
│   │   └── transform_spreads.py   # POGO, z-score, substitution spreads
│   ├── load.py
│   └── utils.py
│
├── dbt/
│   └── models/
│       ├── staging/               # type-cast wrappers over clean tables
│       └── mart/                  # panel-specific tables
│           ├── mart_indonesia_policy_tracker.sql
│           ├── mart_biodiesel_demand_signal.sql
│           ├── mart_oil_substitution_spreads.sql
│           └── mart_cpo_competitiveness.sql
│
├── dashboard/app.py
├── notebooks/                     # exploratory analysis (NB01–NB07)
└── .github/workflows/pipeline.yml
```

---

## Database Schema

All data lives in a single Supabase (PostgreSQL) database across three schemas.

```
postgres
├── raw/                    ← exact copies from source, never modified
│   ├── wb_prices           138 rows  (monthly, 2015-01 → present)
│   ├── yfinance_daily      3000+ rows (daily, 2015-01-01 → present)
│   ├── usda_indonesia      12 rows   (annual marketing years, 2015 → present)
│   └── fao_ffpi            138 rows  (monthly, 2015-01 → present)
│
├── clean/                  ← transformed, joined, calculated
│   ├── commodity_prices    monthly — WB prices + resampled futures
│   ├── currency_rates      monthly — inverted FX + competitiveness indices
│   ├── indonesia_supply    monthly — USDA annual forward-filled to monthly
│   ├── fao_ffpi            monthly — passthrough from raw, date normalised
│   └── all_spreads         monthly — master 24-column table (all metrics)
│
└── mart/                   ← panel-specific tables built by dbt
    ├── mart_indonesia_policy_tracker    Panel 1
    ├── mart_biodiesel_demand_signal     Panel 2
    ├── mart_oil_substitution_spreads    Panel 3
    └── mart_cpo_competitiveness         headline summary
```

**Raw layer rule:** raw tables are append/upsert only. They are never truncated. If a transform fails, the pipeline can be re-run from the transform step without re-downloading source data.

---

## Pipeline Execution

### Running locally

```bash
# 1. Clone and set up environment
git clone https://github.com/heyitssyakirrr/CPO-Competitiveness-Monitor-Dashboard
cd CPO-Competitiveness-Monitor-Dashboard
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Mac/Linux
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env and set DATABASE_URL to your Supabase direct connection string

# 3. Run full pipeline
python main.py

# 4. Run dbt models
cd dbt
dbt run
dbt test
```

---

## Dashboard Panels

**Panel 1 — Indonesia Biodiesel Policy Tracker**
Stacked bar chart showing how Indonesia's CPO is allocated between biodiesel and exports each month, with CPO price overlaid and mandate milestones (B20/B30/B35/B40) annotated.

**Panel 2 — Biodiesel Demand Signal & Price Cycle**
POGO spread trend with zone shading (PROFITABLE / MARGINAL / COSTLY), CPO z-score chart showing where prices sit in their historical cycle, and MYR/IDR currency competitiveness indices.

**Panel 3 — Oil Substitution Spreads**
CPO price discount vs soybean oil, sunflower oil, and rapeseed oil over time, with substitution risk classification and the −$50 threshold line where switching becomes economically attractive.

_Dashboard screenshots to be added after deployment._

---

## Maintenance

**Annual:** The World Bank Pink Sheet URL hash rotates approximately once per year (typically January). When a 404 occurs, update `PINK_SHEET_URL` in `src/extract/extract_worldbank.py`. The new URL is at [worldbank.org/en/research/commodity-markets](https://www.worldbank.org/en/research/commodity-markets).

**As needed:** If the USDA zip file moves from `psd_oilseeds.csv` to a different filename, the extractor logs the actual zip contents on every run so the fix is visible in the logs immediately.

---

## Tech Stack
 
Python · pandas · SQLAlchemy · psycopg2 · Supabase (PostgreSQL) · dbt · Streamlit · Plotly · GitHub Actions
| Data transforms (mart layer) | dbt-core, dbt-postgres |
| Dashboard | Streamlit, Plotly |
| Orchestration | GitHub Actions |
| Configuration | PyYAML, python-dotenv |

---
