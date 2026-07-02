"""
transform_spreads.py — master join and all derived metric calculations.

Reads from:   clean.commodity_prices    (monthly — CPO, soy oil, sunflower, rapeseed,
                                         Brent crude, soybean futures)
              clean.currency_rates      (monthly — FX rates, MYR/IDR indices)
              clean.indonesia_supply    (monthly — USDA forward-filled)
              raw.fao_ffpi              (monthly — FAO vegetable oil index)

Writes to:    clean.fao_ffpi            (raw → clean passthrough, date standardised)
              clean.all_spreads         (the master 24-column dataset — NB06 equivalent)

This is the final transform layer. Its output (clean.all_spreads) is what the dbt
staging/mart models read from, and ultimately what the Streamlit dashboard consumes.

Derived metrics (all confirmed in NB06 — authoritative notebook):

    POGO spread:
        gasoil_usd_per_tonne = brent_crude_usd × BRENT_TO_TONNE_FACTOR   (= 7.3)
        pogo_spread          = cpo_price − gasoil_usd_per_tonne
        pogo_zone            = "PROFITABLE" if < 0 else "MARGINAL" if < 150 else "COSTLY"
        ⚠️  Factor MUST be 7.3 (config.yml and NB06). NB03 used 7.33 transiently
            but NB06 explicitly overrode this. Never change without updating config.yml.

    CPO z-score (36-month rolling):
        cpo_rolling_mean     = cpo_price.rolling(36).mean()
        cpo_rolling_std      = cpo_price.rolling(36).std()
        cpo_zscore           = (cpo_price − mean) / std
        price_cycle_position = "EXPENSIVE" if z > 1
                             | "CHEAP"     if z < -1
                             | "FAIR"      if −1 ≤ z ≤ 1
                             | "INSUFFICIENT DATA" if z is NaN  (first 35 months)
        35 NaN rows expected (burn-in). "INSUFFICIENT DATA" is used as the string
        so the categorical column never has nulls.

    Substitution spreads:
        cpo_vs_soy_spread       = cpo_price − soyoil_price
        cpo_vs_sunflower_spread = cpo_price − sunflower_price
        cpo_vs_rapeseed_spread  = cpo_price − rapeseed_price

    Substitution risk (based ONLY on soy spread — NB06 confirmed):
        HIGH     if cpo_vs_soy_spread > −50   (CPO close to or above soy → buyers switch)
        MODERATE if cpo_vs_soy_spread > −100
        LOW      if cpo_vs_soy_spread ≤ −100  (CPO much cheaper → buyers stick with CPO)

Output schema (clean.all_spreads) — 24 columns, matching nb06_all_spreads.csv exactly:
    month_date, cpo_price, soyoil_price, sunflower_price, rapeseed_price,
    brent_crude_usd, usd_myr, usd_idr, usd_inr, usd_cny, myr_indexed, idr_indexed,
    pogo_spread, pogo_zone, cpo_zscore, price_cycle_position,
    cpo_vs_soy_spread, cpo_vs_sunflower_spread, cpo_vs_rapeseed_spread, substitution_risk,
    industrial_consumption_1000mt, exports_1000mt, biodiesel_share_pct,
    fao_veg_oil_index

Intermediate columns (NOT stored):
    gasoil_usd_per_tonne, soybean_futures_usd, cpo_rolling_mean, cpo_rolling_std
"""

import pandas as pd
from sqlalchemy.engine import Engine

from src.utils import get_logger

logger = get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

# Authoritative Brent barrel → metric tonne conversion factor.
# Source: NB06 (overrides NB03's transient 7.33) and config.yml.
# Do NOT change without also updating config.yml. The 7.3 vs 7.33 difference
# produces a max discrepancy of ~3.7 USD/tonne at high Brent prices — small
# but enough to make the pipeline inconsistent with NB06's reference output.
BRENT_TO_TONNE_FACTOR = 7.3

# Rolling window for CPO z-score (months). 36 confirmed in NB03 — captures
# full price cycles while remaining responsive to recent trends.
ZSCORE_WINDOW = 36

# POGO zone thresholds (USD/tonne) — confirmed NB06.
POGO_MARGINAL_THRESHOLD = 150    # below this: MARGINAL; above: COSTLY

# Substitution risk thresholds (cpo_vs_soy_spread, USD/tonne) — confirmed NB06.
# Negative values: CPO is cheaper than soy (typical state for most of history).
SUB_RISK_HIGH_THRESHOLD     = -50    # spread > -50 → HIGH risk
SUB_RISK_MODERATE_THRESHOLD = -100   # spread > -100 → MODERATE risk; else LOW

# Final 24 columns in the order they appear in nb06_all_spreads.csv.
FINAL_COLS = [
    "month_date",
    "cpo_price", "soyoil_price", "sunflower_price", "rapeseed_price",
    "brent_crude_usd",
    "usd_myr", "usd_idr", "usd_inr", "usd_cny",
    "myr_indexed", "idr_indexed",
    "pogo_spread", "pogo_zone",
    "cpo_zscore", "price_cycle_position",
    "cpo_vs_soy_spread", "cpo_vs_sunflower_spread", "cpo_vs_rapeseed_spread",
    "substitution_risk",
    "industrial_consumption_1000mt", "exports_1000mt", "biodiesel_share_pct",
    "fao_veg_oil_index",
]


# ── Main transform ────────────────────────────────────────────────────────────

def transform_spreads(engine: Engine) -> pd.DataFrame:
    """
    Master join and derived metric calculation — produces clean.all_spreads.

    Args:
        engine: Active SQLAlchemy engine.

    Returns:
        pd.DataFrame with 24 columns matching nb06_all_spreads.csv.
        Writes to clean.all_spreads. Returns an empty DataFrame on failure.
    """
    try:
        # ── 1. Load all clean inputs ──────────────────────────────────────────
        df_prices = pd.read_sql(
            "SELECT * FROM clean.commodity_prices ORDER BY month_date",
            engine, parse_dates=["month_date"],
        )
        df_fx = pd.read_sql(
            "SELECT * FROM clean.currency_rates ORDER BY month_date",
            engine, parse_dates=["month_date"],
        )
        df_usda = pd.read_sql(
            "SELECT month_date, industrial_consumption_1000mt, exports_1000mt, "
            "       biodiesel_share_pct "
            "FROM clean.indonesia_supply ORDER BY month_date",
            engine, parse_dates=["month_date"],
        )
        df_fao = _load_and_clean_fao(engine)

        logger.info(
            "transform_spreads: inputs loaded — prices %d, fx %d, usda %d, fao %d rows",
            len(df_prices), len(df_fx), len(df_usda), len(df_fao),
        )

        # ── 2. Standardise all dates to month-start ───────────────────────────
        for df in [df_prices, df_fx, df_usda, df_fao]:
            df["month_date"] = df["month_date"].dt.to_period("M").dt.to_timestamp()

        # ── 3. Master join — World Bank price spine, everything left-joined ───
        # This exactly mirrors NB06's join strategy. Row count stays at 137
        # (the World Bank spine is the binding constraint).
        df = df_prices.copy()
        df = df.merge(df_fx,  on="month_date", how="left")
        df = df.merge(df_usda, on="month_date", how="left")
        df = df.merge(df_fao,  on="month_date", how="left")

        logger.info(
            "transform_spreads: master join complete — %d rows × %d cols",
            len(df), len(df.columns),
        )

        # ── 4. POGO spread ────────────────────────────────────────────────────
        # gasoil_usd_per_tonne is an intermediate — not stored in final output.
        df["gasoil_usd_per_tonne"] = df["brent_crude_usd"] * BRENT_TO_TONNE_FACTOR
        df["pogo_spread"]          = df["cpo_price"] - df["gasoil_usd_per_tonne"]
        df["pogo_zone"]            = df["pogo_spread"].apply(_pogo_zone)

        # ── 5. CPO z-score (36-month rolling) ────────────────────────────────
        df["cpo_rolling_mean"] = df["cpo_price"].rolling(ZSCORE_WINDOW).mean()
        df["cpo_rolling_std"]  = df["cpo_price"].rolling(ZSCORE_WINDOW).std()
        df["cpo_zscore"]       = (
            (df["cpo_price"] - df["cpo_rolling_mean"]) / df["cpo_rolling_std"]
        ).round(4)
        df["price_cycle_position"] = df["cpo_zscore"].apply(_price_cycle)

        # ── 6. Substitution spreads ───────────────────────────────────────────
        df["cpo_vs_soy_spread"]       = (df["cpo_price"] - df["soyoil_price"]).round(4)
        df["cpo_vs_sunflower_spread"] = (df["cpo_price"] - df["sunflower_price"]).round(4)
        df["cpo_vs_rapeseed_spread"]  = (df["cpo_price"] - df["rapeseed_price"]).round(4)

        # ── 7. Substitution risk — soy spread ONLY (confirmed NB06) ──────────
        df["substitution_risk"] = df["cpo_vs_soy_spread"].apply(_substitution_risk)

        # ── 8. Validation ──────────────────────────────────────────────────────
        _validate(df)

        # ── 9. Select final columns only (drop intermediates) ─────────────────
        df_final = df[FINAL_COLS].copy()

        # ── 10. Write to clean schema ──────────────────────────────────────────
        _write_clean(df_final, "all_spreads", "month_date", engine)
        return df_final

    except Exception as exc:
        logger.error("transform_spreads: failed — %s", exc, exc_info=True)
        return pd.DataFrame()


# ── FAO passthrough ────────────────────────────────────────────────────────────

def _load_and_clean_fao(engine: Engine) -> pd.DataFrame:
    """
    Load raw.fao_ffpi, standardise dates, write to clean.fao_ffpi, return DataFrame.
    This is a thin passthrough — no calculation needed, just date normalisation.
    """
    df = pd.read_sql(
        "SELECT month_date, fao_veg_oil_index FROM raw.fao_ffpi ORDER BY month_date",
        engine,
        parse_dates=["month_date"],
    )
    df["month_date"] = df["month_date"].dt.to_period("M").dt.to_timestamp()
    _write_clean(df, "fao_ffpi", "month_date", engine)
    logger.info("transform_spreads: fao_ffpi passthrough — %d rows → clean.fao_ffpi", len(df))
    return df


# ── Categorical classifiers ────────────────────────────────────────────────────

def _pogo_zone(spread: float) -> str:
    """
    Classify POGO spread into zone labels.
    PROFITABLE = CPO cheaper than gas oil → biodiesel is economically self-funding.
    MARGINAL   = small subsidy burden — mandate is politically sustainable.
    COSTLY     = large gap → requires heavy BPDPKS levy fund coverage.
    """
    if pd.isna(spread):
        return "UNKNOWN"
    if spread < 0:
        return "PROFITABLE"
    if spread < POGO_MARGINAL_THRESHOLD:
        return "MARGINAL"
    return "COSTLY"


def _price_cycle(z: float) -> str:
    """
    Classify CPO z-score into price cycle position.
    Returns "INSUFFICIENT DATA" for NaN (burn-in period) so this column
    never has nulls — confirmed NB03 design decision.
    """
    if pd.isna(z):
        return "INSUFFICIENT DATA"
    if z > 1:
        return "EXPENSIVE"
    if z < -1:
        return "CHEAP"
    return "FAIR"


def _substitution_risk(spread: float) -> str:
    """
    Classify CPO-vs-soy spread into substitution risk level.
    Based ONLY on the soy spread (not sunflower or rapeseed) — confirmed NB06.
    Negative spread = CPO cheaper than soy (typical); more negative = lower risk.
    """
    if pd.isna(spread):
        return "UNKNOWN"
    if spread > SUB_RISK_HIGH_THRESHOLD:
        return "HIGH"
    if spread > SUB_RISK_MODERATE_THRESHOLD:
        return "MODERATE"
    return "LOW"


# ── Validation ────────────────────────────────────────────────────────────────

def _validate(df: pd.DataFrame) -> None:
    """
    Spot-check the master DataFrame against NB07's confirmed reference values.
    Logs warnings for any mismatches — does NOT raise so the pipeline can still
    write partial results and the mismatch can be investigated separately.

    Reference values from NB07 (all confirmed against nb06_all_spreads.csv):
        May 2026 CPO price:       1139.94
        May 2026 POGO spread:      467.97
        May 2026 FAO veg oil idx:  185.00
        May 2026 soy spread:      -635.32
    """
    SPOT_CHECKS = {
        "2026-05-01": {
            "cpo_price":        1139.94,
            "pogo_spread":       467.97,
            "fao_veg_oil_index": 185.00,
            "cpo_vs_soy_spread": -635.32,
        }
    }
    TOLERANCE = 1.0  # USD/tonne — tight enough to catch conversion-factor bugs

    for date_str, expected in SPOT_CHECKS.items():
        row = df[df["month_date"] == pd.Timestamp(date_str)]
        if row.empty:
            logger.warning(
                "transform_spreads: validation — %s not found in output "
                "(pipeline may not have data this recent yet)",
                date_str,
            )
            continue

        for col, ref_val in expected.items():
            if col not in row.columns:
                continue
            actual = float(row[col].values[0])
            delta  = abs(actual - ref_val)
            if delta > TOLERANCE:
                logger.warning(
                    "transform_spreads: VALIDATION MISMATCH — %s %s: "
                    "expected %.2f, got %.2f (delta %.2f > tolerance %.2f). "
                    "Check BRENT_TO_TONNE_FACTOR (%s) and upstream data.",
                    date_str, col, ref_val, actual, delta, TOLERANCE, BRENT_TO_TONNE_FACTOR,
                )
            else:
                logger.info(
                    "transform_spreads: validation ✅ %s %s = %.2f (ref %.2f, delta %.4f)",
                    date_str, col, actual, ref_val, delta,
                )

    # Null checks — confirmed expected counts from NB07
    null_checks = {
        "cpo_zscore":                    35,   # 36-month burn-in
        "industrial_consumption_1000mt":  9,   # Jan–Sep 2015 before USDA starts
        "exports_1000mt":                 9,
        "biodiesel_share_pct":            9,
    }
    for col, expected_nulls in null_checks.items():
        if col not in df.columns:
            continue
        actual_nulls = int(df[col].isna().sum())
        if actual_nulls != expected_nulls:
            logger.warning(
                "transform_spreads: NULL CHECK — %s has %d nulls (expected %d)",
                col, actual_nulls, expected_nulls,
            )
        else:
            logger.info(
                "transform_spreads: null check ✅ %s — %d nulls as expected",
                col, actual_nulls,
            )


# ── Write helper ──────────────────────────────────────────────────────────────

def _write_clean(df: pd.DataFrame, table: str, pk_col: str, engine: Engine) -> None:
    from src.load import _upsert
    n = _upsert(df, "clean", table, pk_col, engine)
    logger.info("transform_spreads: %d rows upserted → clean.%s", n, table)