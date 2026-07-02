"""
transform_currency.py — FX rates and currency indices transform.

Reads from:   raw.yfinance_daily   (daily — INRUSD=X, CNYUSD=X, MYRUSD=X, IDRUSD=X)

Writes to:    clean.currency_rates

Responsibility:
    1. Invert raw yfinance FX direction (yfinance returns USD-per-local-currency;
       we store local-currency-per-USD — confirmed NB02).
    2. Resample daily → monthly using MEAN (FX convention — confirmed NB02).
       Do NOT use last() for FX; that is only for futures (see transform_prices.py).
    3. Standardise dates to month-start.
    4. Compute MYR and IDR competitiveness indices (indexed to 100 at Jan 2015 —
       confirmed NB03). Both on the same base so they're visually comparable.

Output schema (clean.currency_rates):
    month_date      datetime   PK
    usd_myr         float      Ringgit per 1 USD  (higher = MYR weakened)
    usd_idr         float      Rupiah per 1 USD   (higher = IDR weakened)
    usd_inr         float      Rupee per 1 USD    (higher = INR weakened)
    usd_cny         float      Yuan per 1 USD     (higher = CNY weakened)
    myr_indexed     float      usd_myr / Jan-2015 baseline × 100
    idr_indexed     float      usd_idr / Jan-2015 baseline × 100

Direction note:
    yfinance returns e.g. MYRUSD=X as ~0.22 (dollars per ringgit).
    We invert → ~4.5 (ringgits per dollar). Sanity check: usd_myr should be
    ~3.9–4.1 range 2015–2019, rising to ~4.4–4.8 by 2026. usd_idr should be
    ~13,000–17,500+.
"""

import pandas as pd
from sqlalchemy.engine import Engine

from src.utils import get_logger

logger = get_logger(__name__)

# FX columns resampled using monthly MEAN (smooths daily noise — confirmed NB02).
# These are the raw column names as stored in raw.yfinance_daily by extract_yfinance.py.
# Note: yfinance stores them already with the friendly names (usd_myr etc.) but the
# values are INVERTED (USD-per-local) — inversion happens in step 3 below.
FX_COLS_RAW = ["usd_myr", "usd_idr", "usd_inr", "usd_cny"]

# Base date for the competitiveness index (confirmed NB03).
INDEX_BASE_DATE = "2015-01-01"

CLEAN_TABLE = "currency_rates"
PK_COL = "month_date"


def transform_currency(engine: Engine) -> pd.DataFrame:
    """
    Build clean.currency_rates from raw.yfinance_daily.

    Args:
        engine: Active SQLAlchemy engine.

    Returns:
        pd.DataFrame with the clean currency schema. Also writes to
        clean.currency_rates. Returns an empty DataFrame on failure.
    """
    try:
        # ── 1. Load raw yfinance FX daily data ────────────────────────────────
        cols = ", ".join(FX_COLS_RAW)
        df = pd.read_sql(
            f"SELECT date, {cols} FROM raw.yfinance_daily ORDER BY date",
            engine,
            parse_dates=["date"],
        )
        logger.info("transform_currency: yfinance_daily loaded — %d rows", len(df))

        # ── 2. Invert FX direction ────────────────────────────────────────────
        # yfinance returns MYRUSD=X as ~0.22 (how many USD per 1 MYR).
        # We need the conventional direction: how many MYR per 1 USD (~4.5).
        # Confirmed NB02: "df['usd_myr'] = 1 / df['myr_per_usd_raw']".
        # All four FX columns need this inversion.
        for col in FX_COLS_RAW:
            df[col] = 1.0 / df[col]

        # Sanity check — log means so obviously wrong inversions surface immediately
        for col in FX_COLS_RAW:
            logger.info(
                "transform_currency: %s post-inversion mean = %.4f (expected: "
                "usd_myr~4.3, usd_idr~14500, usd_inr~78, usd_cny~6.8)",
                col,
                df[col].mean(),
            )

        # ── 3. Resample daily → monthly MEAN ──────────────────────────────────
        # "MS" = month-start. Mean is the correct aggregation for FX rates —
        # it smooths daily noise and avoids the month-end spike/drop bias.
        df = df.set_index("date")
        df_monthly = (
            df[FX_COLS_RAW]
            .resample("MS")
            .mean()
            .reset_index()
            .rename(columns={"date": "month_date"})
        )
        logger.info(
            "transform_currency: resampled to %d monthly rows", len(df_monthly)
        )

        # ── 4. Standardise dates to month-start ───────────────────────────────
        df_monthly["month_date"] = (
            df_monthly["month_date"].dt.to_period("M").dt.to_timestamp()
        )

        # ── 5. Compute MYR and IDR competitiveness indices ────────────────────
        # Both indexed to 100 at Jan 2015 so they're visually comparable on the
        # same chart regardless of their very different absolute scales.
        # Confirmed NB03: base_myr = df.loc[df["month_date"] == "2015-01-01", "usd_myr"].values[0]
        base_row = df_monthly[df_monthly["month_date"] == INDEX_BASE_DATE]
        if base_row.empty:
            logger.warning(
                "transform_currency: base date %s not found in monthly data — "
                "competitiveness indices will be NaN. Check that yfinance data "
                "starts on or before this date.",
                INDEX_BASE_DATE,
            )
            df_monthly["myr_indexed"] = float("nan")
            df_monthly["idr_indexed"] = float("nan")
        else:
            base_myr = float(base_row["usd_myr"].values[0])
            base_idr = float(base_row["usd_idr"].values[0])
            df_monthly["myr_indexed"] = (df_monthly["usd_myr"] / base_myr * 100).round(4)
            df_monthly["idr_indexed"] = (df_monthly["usd_idr"] / base_idr * 100).round(4)
            logger.info(
                "transform_currency: index bases — MYR %.4f, IDR %.2f (Jan 2015)",
                base_myr, base_idr,
            )

        logger.info(
            "transform_currency: complete — %d rows | %s → %s | nulls: %s",
            len(df_monthly),
            df_monthly["month_date"].min().strftime("%Y-%m"),
            df_monthly["month_date"].max().strftime("%Y-%m"),
            {col: int(df_monthly[col].isna().sum()) for col in df_monthly.columns if col != "month_date"},
        )

        # ── 6. Write to clean schema ───────────────────────────────────────────
        _write_clean(df_monthly, CLEAN_TABLE, PK_COL, engine)
        return df_monthly

    except Exception as exc:
        logger.error("transform_currency: failed — %s", exc, exc_info=True)
        return pd.DataFrame()


def _write_clean(df: pd.DataFrame, table: str, pk_col: str, engine: Engine) -> None:
    from src.load import _upsert
    n = _upsert(df, "clean", table, pk_col, engine)
    logger.info("transform_currency: %d rows upserted → clean.%s", n, table)