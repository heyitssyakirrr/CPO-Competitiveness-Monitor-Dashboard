"""
transform_usda.py — USDA Indonesia supply/demand transform.

Reads from:   raw.usda_indonesia   (annual — one row per marketing year)
              raw.wb_prices        (monthly — used as the date spine for ffill)

Writes to:    clean.indonesia_supply

Responsibility:
    Forward-fill annual USDA marketing-year values to a monthly grain, anchored
    to the World Bank date spine. The USDA data is annual (one figure per marketing
    year, Oct → Sep) but everything else in the pipeline is monthly — this transform
    bridges that gap.

Marketing year convention (critical):
    USDA palm oil marketing year runs October 1 → September 30.
    Market_Year 2024 covers October 2024 through September 2025.
    So marketing_year 2024's value is first assigned to month 2024-10-01 and then
    forward-filled through 2025-09-01.

Forward-fill strategy:
    1. Assign each marketing_year → its start month (Oct 1 of that year).
    2. Reindex onto the full monthly date spine from raw.wb_prices.
    3. Forward-fill (ffill) — each year's value propagates until the next year starts.
    This is confirmed NB04 and is the standard approach for annual-to-monthly expansion.

Expected nulls (documented, not a bug):
    9 rows (Jan 2015 – Sep 2015) will be NaN — the World Bank spine starts Jan 2015
    but the first USDA marketing year starts Oct 2015. These NaNs are known and
    intentional (NB06 confirmed them as expected).

Output schema (clean.indonesia_supply):
    month_date                      datetime   PK
    marketing_year                  int        (e.g. 2024 = Oct 2024 – Sep 2025)
    production_1000mt               float
    industrial_consumption_1000mt   float      (= biodiesel — Attribute_ID 140)
    exports_1000mt                  float
    ending_stocks_1000mt            float
    biodiesel_share_pct             float
"""

import pandas as pd
from sqlalchemy.engine import Engine

from src.utils import get_logger

logger = get_logger(__name__)

USDA_COLS = [
    "marketing_year",
    "production_1000mt",
    "industrial_consumption_1000mt",
    "exports_1000mt",
    "ending_stocks_1000mt",
    "biodiesel_share_pct",
]

CLEAN_TABLE = "indonesia_supply"
PK_COL = "month_date"


def transform_usda(engine: Engine) -> pd.DataFrame:
    """
    Forward-fill USDA annual data onto the World Bank monthly date spine.

    Args:
        engine: Active SQLAlchemy engine.

    Returns:
        pd.DataFrame with the clean indonesia_supply schema. Also writes to
        clean.indonesia_supply. Returns an empty DataFrame on failure.
    """
    try:
        # ── 1. Load annual USDA data ──────────────────────────────────────────
        df_usda = pd.read_sql(
            f"SELECT {', '.join(USDA_COLS)} FROM raw.usda_indonesia ORDER BY marketing_year",
            engine,
        )
        logger.info("transform_usda: usda_indonesia loaded — %d marketing years", len(df_usda))

        # ── 2. Load World Bank monthly spine ──────────────────────────────────
        df_spine = pd.read_sql(
            "SELECT month_date FROM raw.wb_prices ORDER BY month_date",
            engine,
            parse_dates=["month_date"],
        )
        df_spine["month_date"] = df_spine["month_date"].dt.to_period("M").dt.to_timestamp()
        logger.info("transform_usda: wb_prices spine loaded — %d months", len(df_spine))

        # ── 3. Map each marketing year → its October 1 start date ────────────
        # Marketing year 2024 starts 2024-10-01.
        df_usda["month_date"] = pd.to_datetime(
            df_usda["marketing_year"].astype(str) + "-10-01"
        )

        # ── 4. Set month_date as index and reindex onto the full monthly spine ─
        # Any months not in the annual data (i.e. every month except October) get NaN.
        df_usda = df_usda.set_index("month_date")
        spine_index = pd.DatetimeIndex(df_spine["month_date"])
        df_expanded = df_usda.reindex(spine_index)

        # ── 5. Forward-fill: propagate each year's values through the year ────
        # ffill() copies the Oct value forward through Nov, Dec, Jan … Sep.
        # limit=None means we fill all the way to the next marketing year start.
        df_expanded = df_expanded.ffill()

        # ── 6. Restore month_date as a column and cast marketing_year to int ──
        df_expanded = df_expanded.reset_index().rename(columns={"index": "month_date"})
        df_expanded["month_date"] = pd.to_datetime(df_expanded["month_date"])

        # marketing_year may have been coerced to float by reindex; restore to int
        # but only where not NaN (the 9 pre-Oct-2015 rows are intentionally NaN)
        df_expanded["marketing_year"] = (
            df_expanded["marketing_year"]
            .where(df_expanded["marketing_year"].notna())
            .astype("Int64")  # pandas nullable integer — supports NaN without float coercion
        )

        # ── 7. Validate expected nulls ────────────────────────────────────────
        # Jan 2015 – Sep 2015 (9 months) should be NaN for all USDA value columns.
        # Anything else is unexpected and warrants investigation.
        value_cols = [c for c in USDA_COLS if c != "marketing_year"]
        null_counts = {col: int(df_expanded[col].isna().sum()) for col in value_cols}
        expected_nulls = 9

        for col, n_null in null_counts.items():
            if n_null != expected_nulls:
                logger.warning(
                    "transform_usda: %s has %d nulls (expected %d) — "
                    "investigate if this is not the Jan–Sep 2015 burn-in",
                    col, n_null, expected_nulls,
                )
            else:
                logger.info("transform_usda: %s — %d nulls (expected ✅)", col, n_null)

        logger.info(
            "transform_usda: complete — %d rows | %s → %s",
            len(df_expanded),
            df_expanded["month_date"].min().strftime("%Y-%m"),
            df_expanded["month_date"].max().strftime("%Y-%m"),
        )

        # ── 8. Write to clean schema ───────────────────────────────────────────
        _write_clean(df_expanded, CLEAN_TABLE, PK_COL, engine)
        return df_expanded

    except Exception as exc:
        logger.error("transform_usda: failed — %s", exc, exc_info=True)
        return pd.DataFrame()


def _write_clean(df: pd.DataFrame, table: str, pk_col: str, engine: Engine) -> None:
    from src.load import _upsert
    n = _upsert(df, "clean", table, pk_col, engine)
    logger.info("transform_usda: %d rows upserted → clean.%s", n, table)