## Notebook 02 — Findings & Decisions

**Source:** yfinance 1.3.0 \
**Tickers confirmed:** INRUSD=X, CNYUSD=X, ZS=F, BZ=F \
**Date range:** 2015-01-01 → 2026-05-01 \
**Shape:** 137 rows × 5 columns (after monthly resample) \
**Null values:** None

**Columns for pipeline:**
- month_date (datetime, first of month)
- usd_inr (monthly mean, INR per 1 USD)
- usd_cny (monthly mean, CNY per 1 USD)
- soybean_futures_usd (month-end last, USD/bushel)
- brent_crude_usd (month-end last, USD/barrel)

**FX direction:** Pulled as INRUSD=X and CNYUSD=X (USD per foreign unit),
flipped to USD per local currency so rising = weakening local currency.

**Resampling decisions:**
- FX rates → monthly mean (smooth daily noise)
- Futures → monthly last (standard market convention, month-end settlement)

**Key observations:**
- INR weakened ~48% vs USD from 2015–2026 (64 → 95)
- CNY more range-bound (6.2–7.4), reflects managed float policy
- Soybean futures confirm 2022 spike seen in World Bank data ✓
- Brent crude COVID crash (2020) and war spike (2022) clearly visible
- Recent Brent spike (~$115, 2026) = stronger biodiesel demand signal for CPO