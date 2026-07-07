"""
extract_usda.py — USDA FAS PSD Indonesia palm oil supply/demand extractor.

Source: USDA FAS PSD bulk CSV, oilseeds file.
URL:    https://apps.fas.usda.gov/psdonline/downloads/psd_oilseeds_csv.zip

Confirmed from NB04:
  - CSV filename inside zip: psd_oilseeds.csv
  - Column names (exact, case-sensitive): Commodity_Code, Country_Code,
    Attribute_ID, Market_Year, Value
  - Filter by Attribute_ID integers, NOT Attribute_Description strings
  - Pivot index: "Market_Year"
"""

import io
import zipfile

import pandas as pd
import requests

from src.utils import get_logger

logger = get_logger(__name__)

USDA_BULK_URL = "https://apps.fas.usda.gov/psdonline/downloads/psd_oilseeds_csv.zip"

PALM_OIL_CODE = 4243000   # "Oil, Palm" — confirmed NB04
INDONESIA_CODE = "ID"     # confirmed NB04

# Filter and rename by Attribute_ID integers — confirmed NB04.
# This is more robust than Attribute_Description strings which can change.
#   28  = Production
#   140 = Industrial Dom. Cons. (= biodiesel for Indonesia)
#   88  = Exports
#   176 = Ending Stocks
ATTRIBUTES = {
    28:  "production_1000mt",
    140: "industrial_consumption_1000mt",
    88:  "exports_1000mt",
    176: "ending_stocks_1000mt",
}

REQUEST_TIMEOUT_SECONDS = 300


def extract_usda(config: dict) -> pd.DataFrame:
    """
    Download the USDA FAS PSD oilseeds bulk CSV and return Indonesia palm oil
    supply/demand at annual (marketing year) grain.

    Returns one row per marketing year. Forward-filling to monthly is handled
    in transform_usda.py.
    """
    try:
        # ── 1. Download zip ───────────────────────────────────────────────────
        logger.info("usda: downloading PSD oilseeds bulk zip...")
        response = requests.get(USDA_BULK_URL, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        logger.info("usda: download complete (%.1f KB)", len(response.content) / 1024)

        # ── 2. Open zip and read the CSV ──────────────────────────────────────
        # Confirmed NB04: the file inside the zip is named "psd_oilseeds.csv"
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            logger.info("usda: files in zip: %s", z.namelist())
            # Use the confirmed filename, fall back to first CSV if it changes
            if "psd_oilseeds.csv" in z.namelist():
                csv_name = "psd_oilseeds.csv"
            else:
                csv_files = [f for f in z.namelist() if f.endswith(".csv")]
                if not csv_files:
                    logger.error("usda: no CSV found in zip: %s", z.namelist())
                    return _empty_df()
                csv_name = csv_files[0]
                logger.warning("usda: expected 'psd_oilseeds.csv', using '%s'", csv_name)

            df_raw = pd.read_csv(z.open(csv_name))

        logger.info("usda: raw shape %s | columns: %s", df_raw.shape, list(df_raw.columns))

        # ── 3. Filter to Indonesia palm oil ───────────────────────────────────
        # Column names confirmed from NB04 output:
        # Commodity_Code, Country_Code, Attribute_ID, Market_Year, Value
        df = df_raw[
            (df_raw["Commodity_Code"] == PALM_OIL_CODE) &
            (df_raw["Country_Code"] == INDONESIA_CODE)
        ].copy()

        logger.info("usda: %d rows after Indonesia palm oil filter", len(df))

        if df.empty:
            logger.error(
                "usda: no rows found for Commodity_Code=%d, Country_Code='%s'. "
                "Sample Commodity_Codes: %s",
                PALM_OIL_CODE, INDONESIA_CODE,
                list(df_raw["Commodity_Code"].unique()[:5]),
            )
            return _empty_df()

        # ── 4. Filter to needed attributes by Attribute_ID (integer) ─────────
        # Using IDs not description strings — immune to USDA description renaming
        df = df[df["Attribute_ID"].isin(ATTRIBUTES.keys())].copy()
        df["attribute_name"] = df["Attribute_ID"].map(ATTRIBUTES)

        # ── 5. Pivot: one column per attribute, one row per marketing year ─────
        # Confirmed NB04: index="Market_Year", aggfunc="last"
        df_pivot = df.pivot_table(
            index="Market_Year",
            columns="attribute_name",
            values="Value",
            aggfunc="last",
        ).reset_index()
        df_pivot.columns.name = None

        # Rename Market_Year → market_year (pipeline standard — lowercase)
        df_pivot = df_pivot.rename(columns={"Market_Year": "market_year"})

        # ── 6. Filter to 2015+ (aligns with other sources) ────────────────────
        df_pivot = df_pivot[df_pivot["market_year"] >= 2015].copy()

        # ── 7. Derive biodiesel share ─────────────────────────────────────────
        df_pivot["biodiesel_share_pct"] = (
            df_pivot["industrial_consumption_1000mt"]
            / df_pivot["production_1000mt"]
            * 100
        ).round(2)

        df_pivot = df_pivot.sort_values("market_year").reset_index(drop=True)

        logger.info(
            "usda: %d marketing years | %d → %d | biodiesel share %.1f%% → %.1f%%",
            len(df_pivot),
            int(df_pivot["market_year"].min()),
            int(df_pivot["market_year"].max()),
            df_pivot["biodiesel_share_pct"].min(),
            df_pivot["biodiesel_share_pct"].max(),
        )
        return df_pivot

    except requests.exceptions.Timeout:
        logger.error(
            "usda: timed out after %ds. The file may be slow today — try re-running.",
            REQUEST_TIMEOUT_SECONDS,
        )
        return _empty_df()

    except requests.exceptions.HTTPError as exc:
        logger.error("usda: HTTP error — %s", exc)
        return _empty_df()

    except Exception as exc:
        logger.error("usda: unexpected failure — %s", exc, exc_info=True)
        return _empty_df()


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "market_year", "production_1000mt", "industrial_consumption_1000mt",
        "exports_1000mt", "ending_stocks_1000mt", "biodiesel_share_pct",
    ])