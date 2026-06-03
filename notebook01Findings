## Notebook 01 — Findings & Decisions

**Source:** World Bank Pink Sheet (CMO-Historical-Data-Monthly.xlsx)
**Date range confirmed:** 2015-01-01 → 2026-04-01
**Shape:** 136 rows × 5 columns (after filter to 2015)
**Null values:** None
**Units:** All four oils in USD/tonne ✓

**Columns for pipeline:**
- month_date (datetime, first of month)
- cpo_price
- soyoil_price
- sunflower_price
- rapeseed_price

**Why CPO not PKO:** PKO serves personal care markets, not edible oil/biodiesel.
CPO is the correct benchmark for substitution spread analysis.

**Key observation:** Sunflower oil spiked highest in 2022 (Russia-Ukraine war
disrupted Black Sea exports). CPO spiked later and less severely — confirms
CPO's role as a substitute that absorbed demand during the crisis.

**Data lag:** ~1 month. File updated monthly, but always reflects previous month.
Example: May 2026 update contains data through April 2026.

**URL maintenance — action required once per year (~January):**
The Pink Sheet URL hash changes once per year. Same URL works all year long.
Current URL (valid entire 2026): 
https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx
To update: go to https://www.worldbank.org/en/research/commodity-markets
→ right-click CMO-Historical-Data-Monthly.xlsx → Copy link address
→ replace URL in this notebook and in src/extract_worldbank.py