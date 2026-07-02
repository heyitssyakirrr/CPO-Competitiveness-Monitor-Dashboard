"""
extract_usda.py — USDA FAS PSD Indonesia palm oil supply/demand extractor.

Source: USDA Foreign Agricultural Service, Production, Supply & Distribution (PSD)
        Bulk CSV download — oilseeds-only file (3.8 MB, validated in NB04).
        Full all-data file (~50 MB) also contains these rows but takes ~13× longer
        to download — not worth it for a monthly GitHub Actions run.

URL:    https://apps.fas.usda.gov/psdonline/downloads/psd_oilseeds_csv.zip
        No authentication required. Updates monthly alongside WASDE releases.

USDA API status (as of June 2026): HTTP 500 on all endpoints including /countries
and /commodities. Bulk CSV is the only working path.

Validated against: nb04_usda_indonesia_monthly.csv (133 rows × 6 cols, 2015-10 → 2026-10).

Marketing year convention:
    USDA palm oil marketing year runs October 1 → September 30.
    Market_Year 2024 = October 2024 through September 2025.
    Forward-filling to monthly is handled in transform_usda.py, not here.
    This extractor returns one row per marketing year (annual grain).
"""

import io
import zipfile

import pandas as pd
import requests

from src.utils import get_logger

logger = get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

# Oilseeds-only file (3.8 MB) — validated in NB04.
# Prefer this over psd_alldata_csv.zip (~50 MB) for monthly pipeline runs.
USDA_BULK_URL = "https://apps.fas.usda.gov/psdonline/downloads/psd_oilseeds_csv.zip"

# Commodity_Code 4243000 = "Oil, Palm" — confirmed from NB04.
# Distinct from 4244000 "Oil, Palm Kernel" (PKO — not used here).
PALM_OIL_CODE = 4243000

# Country_Code "ID" = Indonesia — confirmed from NB04.
INDONESIA_CODE = "ID"

# Attribute_Description strings as they appear in the USDA CSV.
# ⚠️  KEY DETAIL: use "Industrial Dom. Cons." (Attribute_ID 140), NOT
#     "Domestic Consumption" (Attribute_ID 125).
#
#     Attribute_ID 125 = total domestic consumption (food + biodiesel + other) — wrong.
#     Attribute_ID 140 = industrial domestic consumption — for Indonesia palm oil,
#     this is overwhelmingly biodiesel. This is the number that steps up at every
#     mandate increase (B20 → B30 → B35 → B40).
#
# If a future USDA CSV schema change causes a KeyError on pivot, print:
#     df[df["Country_Code"] == "ID"]["Attribute_Description"].unique()
# and update the keys below to match the new strings exactly.
ATTRIBUTES = {
    "Production":            "production_1000mt",          # Attribute_ID 28
    "Industrial Dom. Cons.": "industrial_consumption_1000mt",  # Attribute_ID 140 (= biodiesel)
    "Exports":               "exports_1000mt",             # Attribute_ID 88
    "Ending Stocks":         "ending_stocks_1000mt",       # Attribute_ID 176
}

# aggfunc="last" in the pivot takes the most-recently-revised annual estimate.
# USDA revises these multiple times per year — "last" gives the most accurate figure.
PIVOT_AGGFUNC = "last"

REQUEST_TIMEOUT_SECONDS = 120  # File is ~3.8 MB; increase on slow connections.


# ── Extractor ─────────────────────────────────────────────────────────────────

def extract_usda(config: dict) -> pd.DataFrame:
    """
    Download the USDA FAS PSD oilseeds bulk CSV and return Indonesia palm oil
    supply/demand data at annual (marketing year) grain.

    Args:
        config: Pipeline config dict loaded from config.yml. Not used for filtering
                here — the transform layer handles start-date filtering after
                forward-filling annual data to monthly.

    Returns:
        pd.DataFrame with columns:
            marketing_year                  int    — e.g. 2024 (= Oct 2024 – Sep 2025)
            production_1000mt               float  — thousand metric tonnes
            industrial_consumption_1000mt   float  — thousand MT (overwhelmingly biodiesel)
            exports_1000mt                  float  — thousand MT
            ending_stocks_1000mt            float  — thousand MT
            biodiesel_share_pct             float  — industrial_consumption / production × 100
        One row per marketing year, sorted ascending by marketing_year.
        Returns an empty DataFrame (same schema) on any failure.

    Notes:
        - Forward-filling to monthly grain is done in transform_usda.py, not here.
        - "Industrial Dom. Cons." (Attr_ID 140) ≠ "Domestic Consumption" (Attr_ID 125).
          The former is the biodiesel-tracking attribute; see module docstring.
        - Data lag: 1–2 months after each WASDE release.
    """
    try:
        # ── 1. Download zip in memory ─────────────────────────────────────────
        logger.info("usda: downloading PSD oilseeds bulk zip...")
        response = requests.get(USDA_BULK_URL, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        logger.info("usda: download complete (%.1f KB)", len(response.content) / 1024)

        # ── 2. Open zip and read the CSV inside ───────────────────────────────
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            csv_files = [f for f in z.namelist() if f.endswith(".csv")]
            if not csv_files:
                logger.error("usda: no CSV file found inside zip — %s", z.namelist())
                return _empty_df()

            logger.info("usda: reading '%s' from zip...", csv_files[0])
            df_raw = pd.read_csv(z.open(csv_files[0]))

        logger.info("usda: raw shape %s", df_raw.shape)

        # ── 3. Standardise column names ───────────────────────────────────────
        df_raw.columns = [c.strip() for c in df_raw.columns]

        # ── 4. Filter to Indonesia palm oil ───────────────────────────────────
        df = df_raw[
            (df_raw["Country_Code"] == INDONESIA_CODE)
            & (df_raw["Commodity_Code"] == PALM_OIL_CODE)
        ].copy()

        logger.info("usda: %d rows after Indonesia palm oil filter", len(df))

        if df.empty:
            logger.error(
                "usda: no rows for Country_Code='%s', Commodity_Code=%d. "
                "Check that the oilseeds zip contains these codes.",
                INDONESIA_CODE,
                PALM_OIL_CODE,
            )
            return _empty_df()

        # ── 5. Validate that the expected attribute strings exist ─────────────
        available_attrs = set(df["Attribute_Description"].unique())
        missing_attrs = [a for a in ATTRIBUTES if a not in available_attrs]
        if missing_attrs:
            logger.error(
                "usda: attribute(s) not found in CSV — %s. "
                "Available attributes: %s. "
                "Update the ATTRIBUTES dict if USDA renamed these fields.",
                missing_attrs,
                sorted(available_attrs),
            )
            return _empty_df()

        # ── 6. Keep only the attributes we need ───────────────────────────────
        df = df[df["Attribute_Description"].isin(ATTRIBUTES.keys())]
        df = df[["Marketing_Year", "Attribute_Description", "Value"]].copy()

        # ── 7. Pivot: one column per attribute, one row per marketing year ─────
        # aggfunc="last" picks the most-recently-revised estimate for each year.
        df_pivot = df.pivot_table(
            index="Marketing_Year",
            columns="Attribute_Description",
            values="Value",
            aggfunc=PIVOT_AGGFUNC,
        ).reset_index()

        # Remove the MultiIndex name that pivot_table adds to the columns axis.
        df_pivot.columns.name = None

        # ── 8. Rename columns to pipeline-standard names ──────────────────────
        df_pivot = df_pivot.rename(columns=ATTRIBUTES)
        df_pivot = df_pivot.rename(columns={"Marketing_Year": "marketing_year"})

        # ── 9. Derive biodiesel share ─────────────────────────────────────────
        df_pivot["biodiesel_share_pct"] = (
            df_pivot["industrial_consumption_1000mt"]
            / df_pivot["production_1000mt"]
            * 100
        ).round(2)

        df_pivot = df_pivot.sort_values("marketing_year").reset_index(drop=True)

        logger.info(
            "usda: %d marketing years extracted | %d → %d | "
            "biodiesel share range: %.1f%% → %.1f%%",
            len(df_pivot),
            int(df_pivot["marketing_year"].min()),
            int(df_pivot["marketing_year"].max()),
            df_pivot["biodiesel_share_pct"].min(),
            df_pivot["biodiesel_share_pct"].max(),
        )
        return df_pivot

    except requests.exceptions.Timeout:
        logger.error(
            "usda: request timed out after %ds. "
            "Try increasing REQUEST_TIMEOUT_SECONDS or switching to psd_alldata_csv.zip "
            "if the oilseeds file is temporarily unavailable.",
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
    """Return an empty DataFrame with the expected schema so callers can always rely on column names."""
    return pd.DataFrame(
        columns=[
            "marketing_year",
            "production_1000mt",
            "industrial_consumption_1000mt",
            "exports_1000mt",
            "ending_stocks_1000mt",
            "biodiesel_share_pct",
        ]
    )