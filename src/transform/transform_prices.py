"""
transform_prices.py — commodity prices transform (World Bank + yfinance futures).

Reads from:   raw.wb_prices       (monthly  — CPO, soy oil, sunflower, rapeseed)
              raw.yfinance_daily   (daily    — Brent crude, soybean futures)

Writes to:    clean.commodity_prices

Responsibility:
    1. Resample Brent and soybean futures from daily → monthly (method: LAST,
       month-end settlement convention — confirmed NB02).
    2. Standardise all dates to month-start (period → timestamp).
    3. Join on month_date (World Bank is the spine — left join everything onto it).
    4. Invert raw yfinance FX direction for Brent only where needed (FX inversion
       is handled in transform_currency.py — only futures columns live here).

Output schema (clean.commodity_prices):
    month_date              datetime   PK
    cpo_price               float      USD/tonne  (World Bank)
    soyoil_price            float      USD/tonne  (World Bank)
    sunflower_price         float      USD/tonne  (World Bank)
    rapeseed_price          float      USD/tonne  (World Bank)
    brent_crude_usd         float      USD/barrel (yfinance BZ=F, month-end last)
    soybean_futures_usd     float      USD/bushel (yfinance ZS=F ÷ 100, month-end last)

Note: POGO and substitution spreads are calculated in transform_spreads.py, not here.
      This module only assembles the price inputs those calculations need.
"""

import pandas as pd
from sqlalchemy.engine import Engine

from src.utils import get_logger

logger = get_logger(__name__)

# Futures columns resampled using month-end LAST (settlement convention — NB02).
FUTURES_COLS = ["brent_crude_usd", "soybean_futures_usd"]

# World Bank price columns (already monthly — no resampling needed).
WB_PRICE_COLS = ["cpo_price", "soyoil_price", "sunflower_price", "rapeseed_price"]

CLEAN_TABLE = "clean.commodity_prices"
PK_COL = "month_date"


def transform_prices(engine: Engine) -> pd.DataFrame:
    """
    Build clean.commodity_prices from raw.wb_prices and raw.yfinance_daily.

    Args:
        engine: Active SQLAlchemy engine pointing at the Supabase database.

    Returns:
        pd.DataFrame with the clean commodity prices schema described in the
        module docstring. Writes to clean.commodity_prices and returns the same
        DataFrame for use in downstream transforms in the same pipeline run
        (avoids a redundant re-read from the DB).
        Returns an empty DataFrame on failure.
    """
    try:
        # ── 1. Load raw World Bank prices ─────────────────────────────────────
        df_wb = pd.read_sql(
            "SELECT month_date, cpo_price, soyoil_price, sunflower_price, rapeseed_price "
            "FROM raw.wb_prices ORDER BY month_date",
            engine,
            parse_dates=["month_date"],
        )
        logger.info("transform_prices: wb_prices loaded — %d rows", len(df_wb))

        # ── 2. Load raw yfinance daily — futures only ─────────────────────────
        df_yf = pd.read_sql(
            "SELECT date, brent_crude_usd, soybean_futures_usd "
            "FROM raw.yfinance_daily ORDER BY date",
            engine,
            parse_dates=["date"],
        )
        logger.info("transform_prices: yfinance_daily loaded — %d rows", len(df_yf))

        # ── 3. Resample futures: daily → monthly LAST ─────────────────────────
        # "MS" = month-start frequency. Using last() matches month-end settlement
        # convention confirmed in NB02 — do NOT use mean() for futures.
        df_yf = df_yf.set_index("date")
        df_futures_monthly = (
            df_yf[FUTURES_COLS]
            .resample("MS")
            .last()
            .reset_index()
            .rename(columns={"date": "month_date"})
        )
        logger.info(
            "transform_prices: futures resampled — %d monthly rows", len(df_futures_monthly)
        )

        # ── 4. Standardise both date columns to month-start ───────────────────
        # Converts e.g. 2015-01-15 → 2015-01-01 so the join is clean.
        for df, col in [(df_wb, "month_date"), (df_futures_monthly, "month_date")]:
            df[col] = df[col].dt.to_period("M").dt.to_timestamp()

        # ── 5. Join: World Bank is the spine ──────────────────────────────────
        # Left join so we keep all World Bank rows even if yfinance has a gap.
        df = df_wb.merge(df_futures_monthly, on="month_date", how="left")

        logger.info(
            "transform_prices: joined — %d rows | %s → %s | nulls: %s",
            len(df),
            df["month_date"].min().strftime("%Y-%m"),
            df["month_date"].max().strftime("%Y-%m"),
            {col: int(df[col].isna().sum()) for col in FUTURES_COLS},
        )

        # ── 6. Write to clean schema ───────────────────────────────────────────
        _write_clean(df, "commodity_prices", PK_COL, engine)
        return df

    except Exception as exc:
        logger.error("transform_prices: failed — %s", exc, exc_info=True)
        return pd.DataFrame()


def _write_clean(df: pd.DataFrame, table: str, pk_col: str, engine: Engine) -> None:
    """Upsert a clean DataFrame into the clean schema."""
    from src.load import _upsert  # local import avoids circular dependency at module level
    n = _upsert(df, "clean", table, pk_col, engine)
    logger.info("transform_prices: %d rows upserted → clean.%s", n, table)