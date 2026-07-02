"""
load.py — raw layer loader for the CPO Competitiveness Monitor ETL pipeline.

Responsibility: write the four raw DataFrames (one per extractor) into the
Supabase PostgreSQL `raw` schema. This is the write-once replay layer.

Raw layer rule (enforced here via upsert, not truncate+insert):
    Raw tables are never deleted or overwritten — new rows are inserted and
    existing rows updated only if the values actually changed. This means a
    partial pipeline failure can be re-run without losing already-loaded data,
    and historical corrections propagate cleanly.

Tables written:
    raw.wb_prices        ← extract_worldbank   (monthly, keyed on month_date)
    raw.yfinance_daily   ← extract_yfinance    (daily,   keyed on date)
    raw.usda_indonesia   ← extract_usda        (annual,  keyed on marketing_year)
    raw.fao_ffpi         ← extract_fao         (monthly, keyed on month_date)

Connection:
    Reads DATABASE_URL from the environment (set in .env locally,
    Streamlit Cloud secrets / GitHub Actions secrets in CI).
    Never hard-coded here.

Dependencies:
    pip install sqlalchemy psycopg2-binary python-dotenv
"""

import os
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.utils import get_logger

logger = get_logger(__name__)

# Load .env when running locally (no-op in CI where env vars are injected directly)
load_dotenv()

# ── Table definitions ─────────────────────────────────────────────────────────
# Each entry: (schema, table, primary_key_column)
# primary_key_column is used to determine the ON CONFLICT target for upserts.
RAW_TABLES = {
    "wb_prices":      ("raw", "wb_prices",      "month_date"),
    "yfinance_daily": ("raw", "yfinance_daily",  "date"),
    "usda_indonesia": ("raw", "usda_indonesia",  "marketing_year"),
    "fao_ffpi":       ("raw", "fao_ffpi",        "month_date"),
}


# ── Engine factory ────────────────────────────────────────────────────────────

def _get_engine() -> Engine:
    """
    Build a SQLAlchemy engine from DATABASE_URL.

    Raises:
        RuntimeError: if DATABASE_URL is not set in the environment.

    The URL is read from the environment at call time (not at import time) so
    tests can patch os.environ without monkey-patching module-level state.
    """
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set. "
            "Add it to .env for local runs or to GitHub Actions / Streamlit Cloud secrets."
        )

    # pool_pre_ping=True: verify connections are alive before using them —
    # important for long-lived processes and GitHub Actions cold starts.
    return create_engine(url, pool_pre_ping=True)


# ── Schema bootstrap ──────────────────────────────────────────────────────────

def ensure_schemas(engine: Engine) -> None:
    """
    Create the `raw` and `clean` schemas if they don't already exist.
    Safe to call on every pipeline run — CREATE SCHEMA IF NOT EXISTS is idempotent.
    """
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS clean"))
    logger.info("load: schemas raw + clean verified")


# ── Upsert helper ─────────────────────────────────────────────────────────────

def _upsert(
    df: pd.DataFrame,
    schema: str,
    table: str,
    pk_col: str,
    engine: Engine,
) -> int:
    """
    Upsert a DataFrame into a PostgreSQL table using a staging-table strategy:

        1. Write df to a temp table (no constraints).
        2. INSERT … ON CONFLICT (pk_col) DO UPDATE — merges new rows and
           updates changed values in existing rows.
        3. Drop the temp table.

    This is safer than to_sql(if_exists="replace") (which truncates the table)
    and more explicit than pandas' built-in upsert options.

    Args:
        df:     DataFrame to upsert. Must not be empty.
        schema: Target schema name (e.g. "raw").
        table:  Target table name (e.g. "wb_prices").
        pk_col: Primary key column used for conflict detection.
        engine: Active SQLAlchemy engine.

    Returns:
        Number of rows upserted.
    """
    staging = f"_staging_{table}"
    full_table = f"{schema}.{table}"

    # Build the UPDATE SET clause for all non-PK columns
    update_cols = [c for c in df.columns if c != pk_col]
    if not update_cols:
        logger.warning("load: %s — no non-PK columns to update; skipping upsert", full_table)
        return 0

    set_clause = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
    col_list   = ", ".join(f'"{c}"' for c in df.columns)

    with engine.begin() as conn:
        # Step 1: write to a temporary staging table (dropped at end of transaction)
        df.to_sql(
            staging,
            conn,
            schema=schema,
            if_exists="replace",
            index=False,
        )

        # Step 2: ensure the target table exists (create from staging if first run)
        conn.execute(text(
            f"""
            CREATE TABLE IF NOT EXISTS {full_table}
            AS SELECT * FROM {schema}."{staging}" WHERE 1=0
            """
        ))

        # Step 3: upsert from staging → target
        result = conn.execute(text(
            f"""
            INSERT INTO {full_table} ({col_list})
            SELECT {col_list} FROM {schema}."{staging}"
            ON CONFLICT ("{pk_col}") DO UPDATE
            SET {set_clause}
            """
        ))

        # Step 4: drop staging table
        conn.execute(text(f'DROP TABLE IF EXISTS {schema}."{staging}"'))

    return result.rowcount


# ── Public load functions ─────────────────────────────────────────────────────

def load_raw(
    wb_prices:      pd.DataFrame,
    yfinance_daily: pd.DataFrame,
    usda_indonesia: pd.DataFrame,
    fao_ffpi:       pd.DataFrame,
    engine: Optional[Engine] = None,
) -> dict:
    """
    Load all four raw DataFrames into the Supabase `raw` schema.

    Each non-empty DataFrame is upserted into its corresponding table.
    Empty DataFrames (i.e. extractors that failed) are skipped with a warning
    so a single source failure doesn't block the others from loading.

    Args:
        wb_prices:      From extract_worldbank — monthly commodity prices.
        yfinance_daily: From extract_yfinance  — daily FX + futures.
        usda_indonesia: From extract_usda      — annual USDA supply/demand.
        fao_ffpi:       From extract_fao       — monthly FAO vegetable oil index.
        engine:         Optional pre-built engine (useful for testing). If None,
                        a new engine is built from DATABASE_URL.

    Returns:
        dict mapping table name → rows upserted (0 for skipped tables).
    """
    if engine is None:
        engine = _get_engine()

    ensure_schemas(engine)

    payloads = {
        "wb_prices":      wb_prices,
        "yfinance_daily": yfinance_daily,
        "usda_indonesia": usda_indonesia,
        "fao_ffpi":       fao_ffpi,
    }

    results = {}
    for key, df in payloads.items():
        schema, table, pk_col = RAW_TABLES[key]

        if df.empty:
            logger.warning("load: %s.%s — DataFrame is empty, skipping", schema, table)
            results[key] = 0
            continue

        try:
            n = _upsert(df, schema, table, pk_col, engine)
            logger.info("load: %s.%s — %d rows upserted", schema, table, n)
            results[key] = n
        except Exception as exc:
            logger.error(
                "load: %s.%s — upsert failed: %s", schema, table, exc, exc_info=True
            )
            results[key] = 0

    total = sum(results.values())
    logger.info("load: raw layer complete — %d total rows upserted across %d tables", total, len(results))
    return results