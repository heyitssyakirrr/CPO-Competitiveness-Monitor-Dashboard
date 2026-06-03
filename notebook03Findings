## Notebook 03 — Findings & Decisions

**Source:** UN Comtrade API  
**Library:** `comtradeapicall` + direct `requests` to comtradeapi.un.org  
**Commodity:** HS 1511 (all palm oil — crude + refined)  
**Flow:** Malaysia (reporter) → India + China (partners), Exports only  
**Frequency:** Annual only — Malaysia does not submit monthly data to Comtrade  

---

### Country Codes — Always Verify, Never Assume

| Country | Code | Note |
|---|---|---|
| Malaysia (reporter) | 458 | Confirmed ✓ |
| India (partner) | 699 | NOT 356 — code 356 = "India (...1974)", expired |
| China (partner) | 156 | Confirmed ✓ |

Codes verified directly from official Comtrade reference files:
- https://comtradeapi.un.org/files/v1/app/reference/Reporters.json
- https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json

---

### Commodity Code Decision

Initially queried HS `151110` (crude palm oil only).  
China volumes returned near-zero — not reflective of real trade.  
Root cause: Malaysia exports mostly **refined** palm oil to China, not crude. India buys both crude and refined.

**Decision:** Broadened to HS `1511` (all palm oil) for both countries so India and China are compared on the same basis.

---

### Data Quality Issues Found and Fixed

**Issue 1 — Duplicate and aggregate records per year**  
Comtrade returns multiple rows per year representing:
- Sub-records (individual shipment classifications)
- An aggregate row that already sums the sub-records

Verified for 2019 China:
- Row A: 8,500 kg (small sub-record)
- Row B: 1,722,560,000 kg (main volume)
- Row C: 1,722,568,000 kg = Row A + Row B (the aggregate — correct total)

For 2022 China: two rows are fully identical true duplicates.

**Fix:** Sort descending by qty, then `drop_duplicates()` keeping the maximum row per year.  
Do NOT sum rows — the aggregate already includes everything.

**Issue 2 — Phantom near-zero values**  
Before fix, 2019 and 2025 China showed near-zero volumes because the phantom sub-record appeared before the real aggregate row. Fixed by sort-then-deduplicate approach above.

---

### Data Reliability — Important Caveats

Comtrade trade data should be treated as **directional indicators, not precise volumes.**  
Known sources of discrepancy vs other datasets:

- **Mirror statistics:** Malaysia records exports at FOB value. Destination countries record the same shipment at CIF value (includes freight/insurance). Difference is typically 10–15%.
- **Re-exports via Singapore:** Some Malaysia → China shipments transit Singapore and appear as Malaysia → Singapore → China in Comtrade, understating direct bilateral flows.
- **Estimation:** Most China records show `isReported=False`, `isAggregate=True` — Comtrade estimated these figures, Malaysia did not directly submit them.
- **Reporting lag:** Malaysia submits data late. Recent years (2024, 2025) may be incomplete or revised later.
- **HS code mapping differences:** Countries sometimes classify the same product under slightly different subcodes.

Cross-validation against MPOB total export data recommended in Notebook 07.  
Use Comtrade data for **trend analysis only.**

---

### Final Dataset

**Shape:** 22 rows (11 years × 2 countries)  
**Date range:** 2015–2025  
**Null values:** None  

**Columns for pipeline:**

| Column | Type | Description |
|---|---|---|
| year | int | Calendar year |
| destination | str | "India" or "China" |
| export_qty_tonnes | float | Palm oil export volume in tonnes |
| export_value_usd | float | FOB export value in USD |
| is_reliable | bool | False if volume below 500,000 tonnes threshold |

---

### Key Observations

- India is consistently the largest buyer: 2–4 million tonnes annually, roughly 2–3x China volumes every year
- India volumes dropped sharply 2016–2017, recovered from 2019 — likely correlated with India's import duty changes on Malaysian palm oil
- China volumes more stable: 0.75–1.84 million tonnes, less policy-driven
- 2025 China data present (~679,000 tonnes) but likely incomplete — treat as directional only
- Both countries peaked around 2015 and 2019–2021 — aligns with periods of low CPO prices (buyers stock up when prices are attractive)

---

**Next:** Notebook 04 — USDA FAS (Indonesia Supply/Demand)