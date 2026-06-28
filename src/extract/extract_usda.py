import pandas as pd
import requests
import zipfile
import io
from src.utils import get_logger

logger = get_logger()

USDA_BULK_URL = "https://apps.fas.usda.gov/psdonline/downloads/psd_alldata_csv.zip"

# Palm oil commodity code in USDA PSD
PALM_OIL_CODE = 4243000

# Indonesia country code
INDONESIA_CODE = "ID"

# Attribute names we need from the PSD data
ATTRIBUTES = {
    "Production":             "production_1000mt",
    "Domestic Consumption":   "industrial_consumption_1000mt",
    "Exports":                "exports_1000mt",
    "Ending Stocks":          "ending_stocks_1000mt",
}

def extract_usda(config: dict) -> pd.DataFrame:
    try:
        logger.info("usda: downloading bulk PSD zip...")

        response = requests.get(USDA_BULK_URL, timeout=120)
        response.raise_for_status()

        # Open zip in memory
        z = zipfile.ZipFile(io.BytesIO(response.content))

        # Find the CSV file inside the zip
        csv_files = [f for f in z.namelist() if f.endswith(".csv")]
        logger.info(f"usda: files in zip: {csv_files}")

        df = pd.read_csv(z.open(csv_files[0]))

        logger.info(f"usda: raw shape {df.shape}, columns: {df.columns.tolist()}")

        # Standardise column names
        df.columns = [c.strip() for c in df.columns]

        # Filter to Indonesia palm oil only
        df = df[
            (df["Country_Code"] == INDONESIA_CODE) &
            (df["Commodity_Code"] == PALM_OIL_CODE)
        ]

        logger.info(f"usda: after Indonesia palm oil filter: {df.shape}")

        # Keep only the attributes we need
        df = df[df["Attribute_Description"].isin(ATTRIBUTES.keys())]

        # Keep relevant columns
        df = df[["Marketing_Year", "Attribute_Description", "Value"]]

        # Pivot so each attribute becomes a column
        df = df.pivot_table(
            index="Marketing_Year",
            columns="Attribute_Description",
            values="Value",
            aggfunc="last"
        ).reset_index()

        # Flatten column names
        df.columns.name = None
        df = df.rename(columns=ATTRIBUTES)
        df = df.rename(columns={"Marketing_Year": "marketing_year"})

        # Calculate biodiesel share
        df["biodiesel_share_pct"] = (
            df["industrial_consumption_1000mt"] / df["production_1000mt"] * 100
        ).round(2)

        df = df.sort_values("marketing_year").reset_index(drop=True)

        logger.info(f"usda: {len(df)} marketing years extracted")
        return df

    except Exception as e:
        logger.error(f"usda extraction failed: {e}")
        return pd.DataFrame()