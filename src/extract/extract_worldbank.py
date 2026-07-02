"""
extract_worldbank.py — World Bank Pink Sheet commodity price extractor.

Source: World Bank Commodity Markets ("Pink Sheet") monthly Excel file.
Sheet:  "Monthly Prices"
Confirmed columns: Palm oil, Soybean oil, Sunflower oil, Rapeseed oil (all USD/tonne).
Validated against: nb01_wb_prices_clean.csv (137 rows × 5 cols, 2015-01 → 2026-05).

URL maintenance:
    The URL hash (the long hex string) changes roughly once per year when the World Bank
    updates their document management system. If this extractor raises a 404:
      1. Go to https://www.worldbank.org/en/research/commodity-markets
      2. Right-click "CMO-Historical-Data-Monthly.xlsx" → Copy link address
      3. Update PINK_SHEET_URL below and commit the change.
    The hash has been stable for all of 2026 — expect it to rotate around Jan 2027.
"""

import io

import pandas as pd
import requests

from src.utils import get_logger

logger = get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

# Update this URL when the World Bank rotates the document hash (~once per year).
# Confirmed working for all of 2026.
PINK_SHEET_URL = (
    "https://thedocs.worldbank.org/en/doc/"
    "74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/"
    "related/CMO-Historical-Data-Monthly.xlsx"
)

SHEET_NAME = "Monthly Prices"

# skiprows=4: skips 4 title/header rows so row 4 becomes the column header.
# After that, row 0 of the resulting DataFrame is the units row ("($/mt)" etc.)
# and must be dropped before use.
SKIPROWS = 4

# Exact column names as they appear in the Pink Sheet after skiprows parsing.
# "Unnamed: 0" is the date column (pandas names it this because the cell is blank
# in the header row). Confirmed from NB01 — do not change these keys.
COLUMN_MAP = {
    "Unnamed: 0":    "month_date",
    "Palm oil":      "cpo_price",
    "Soybean oil":   "soyoil_price",
    "Sunflower oil": "sunflower_price",
    "Rapeseed oil":  "rapeseed_price",
}

PRICE_COLUMNS = ["cpo_price", "soyoil_price", "sunflower_price", "rapeseed_price"]

# Date format confirmed from NB01: "1960M01" style (NOT "YR1960M01").
DATE_FORMAT = "%YM%m"

REQUEST_TIMEOUT_SECONDS = 60


# ── Extractor ─────────────────────────────────────────────────────────────────

def extract_worldbank(config: dict) -> pd.DataFrame:
    """
    Download the World Bank Pink Sheet Excel file and return monthly commodity
    prices for CPO, soybean oil, sunflower oil, and rapeseed oil.

    Args:
        config: Pipeline config dict loaded from config.yml. Reads:
                  config["pipeline"]["start_date"] — ISO date string, e.g. "2015-01-01"

    Returns:
        pd.DataFrame with columns:
            month_date       datetime64[ns]  — month-start dates
            cpo_price        float64         — USD/tonne
            soyoil_price     float64         — USD/tonne
            sunflower_price  float64         — USD/tonne
            rapeseed_price   float64         — USD/tonne
        Filtered to >= start_date, sorted ascending, index reset.
        Returns an empty DataFrame (same schema) on any failure.

    Notes:
        - Data lag: ~1 month. The Pink Sheet always reflects the previous month.
        - Missing values appear as "…" (U+2026 HORIZONTAL ELLIPSIS) in the Excel —
          these are coerced to NaN by pd.to_numeric(errors="coerce").
        - CPO = Palm oil (not Palm kernel oil — PKO is a different commodity).
    """
    try:
        start_date = pd.Timestamp(config["pipeline"]["start_date"])

        # ── 1. Download ───────────────────────────────────────────────────────
        logger.info("worldbank: downloading Pink Sheet from World Bank...")
        response = requests.get(PINK_SHEET_URL, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        logger.info("worldbank: download complete (%.1f KB)", len(response.content) / 1024)

        # ── 2. Parse Excel ────────────────────────────────────────────────────
        # engine="openpyxl" required for .xlsx files.
        # skiprows=4: title/subtitle rows sit above the real header.
        df = pd.read_excel(
            io.BytesIO(response.content),
            sheet_name=SHEET_NAME,
            skiprows=SKIPROWS,
            engine="openpyxl",
        )

        # ── 3. Drop the units row (row 0 after skiprows) ──────────────────────
        # After skiprows, pandas reads row 4 as the column header.
        # The next row (now index 0) contains unit strings like "($/mt)", "($/bbl)".
        # Dropping it before any numeric conversion avoids coercion errors.
        df = df.iloc[1:].reset_index(drop=True)

        # ── 4. Select and rename the columns we need ──────────────────────────
        missing_cols = [c for c in COLUMN_MAP if c not in df.columns]
        if missing_cols:
            # Column names drift when the World Bank restructures the sheet.
            # Log exactly which ones are missing so the annual update is easy to fix.
            logger.error(
                "worldbank: expected columns not found in sheet — %s. "
                "Check whether the Pink Sheet layout changed and update COLUMN_MAP.",
                missing_cols,
            )
            return _empty_df()

        df = df[list(COLUMN_MAP.keys())].rename(columns=COLUMN_MAP)

        # ── 5. Parse dates ────────────────────────────────────────────────────
        # Confirmed format: "1960M01" (year + "M" + zero-padded month).
        df["month_date"] = pd.to_datetime(
            df["month_date"], format=DATE_FORMAT, errors="coerce"
        )

        # Drop rows where date parsing failed (e.g. footer/annotation rows).
        n_before = len(df)
        df = df.dropna(subset=["month_date"])
        n_dropped = n_before - len(df)
        if n_dropped:
            logger.warning("worldbank: dropped %d rows with unparseable dates", n_dropped)

        # ── 6. Coerce price columns to float ──────────────────────────────────
        # The Pink Sheet uses "…" (U+2026) for missing/not-yet-published values.
        # pd.to_numeric(errors="coerce") converts these to NaN cleanly.
        for col in PRICE_COLUMNS:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # ── 7. Filter to pipeline start date ──────────────────────────────────
        df = df[df["month_date"] >= start_date]

        # ── 8. Drop rows that are entirely NaN across all price columns ────────
        # (e.g. a future placeholder row the Pink Sheet sometimes includes)
        df = df.dropna(subset=PRICE_COLUMNS, how="all")

        df = df.sort_values("month_date").reset_index(drop=True)

        logger.info(
            "worldbank: %d rows extracted | %s → %s | nulls per column: %s",
            len(df),
            df["month_date"].min().strftime("%Y-%m"),
            df["month_date"].max().strftime("%Y-%m"),
            {col: int(df[col].isna().sum()) for col in PRICE_COLUMNS},
        )
        return df

    except requests.exceptions.Timeout:
        logger.error(
            "worldbank: request timed out after %ds — Pink Sheet server may be slow. "
            "Try increasing REQUEST_TIMEOUT_SECONDS.",
            REQUEST_TIMEOUT_SECONDS,
        )
        return _empty_df()

    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        if status == 404:
            logger.error(
                "worldbank: 404 — Pink Sheet URL has rotated. "
                "Go to https://www.worldbank.org/en/research/commodity-markets, "
                "right-click CMO-Historical-Data-Monthly.xlsx → Copy link, "
                "then update PINK_SHEET_URL in this file."
            )
        else:
            logger.error("worldbank: HTTP %s — %s", status, exc)
        return _empty_df()

    except Exception as exc:
        logger.error("worldbank: unexpected failure — %s", exc, exc_info=True)
        return _empty_df()


def _empty_df() -> pd.DataFrame:
    """Return an empty DataFrame with the expected schema so callers can always rely on column names."""
    return pd.DataFrame(columns=["month_date"] + PRICE_COLUMNS)