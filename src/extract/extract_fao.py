import pandas as pd
import requests
from src.utils import get_logger

logger = get_logger()

FAO_URL = (
    "https://www.fao.org/media/docs/worldfoodsituationlibraries/"
    "default-document-library/food_price_indices_data.csv"
    "?sfvrsn=523ebd2a_80&download=true"
)

def extract_fao(config: dict) -> pd.DataFrame:
    try:
        logger.info("fao: pulling vegetable oil index...")

        response = requests.get(FAO_URL, timeout=30)
        response.raise_for_status()

        from io import StringIO
        df = pd.read_csv(
            StringIO(response.text),
            skiprows=3,
            usecols=[0, 1, 2, 3, 4, 5]
        )

        # Rename columns to lowercase, strip whitespace
        df.columns = [c.strip().lower() for c in df.columns]

        # The date column is the first one — rename it
        date_col = df.columns[0]
        df = df.rename(columns={date_col: "month_date"})

        # Keep only the oils column
        df = df[["month_date", "oils"]]
        df = df.rename(columns={"oils": "fao_veg_oil_index"})

        # Parse date — format is "1990-01"
        df["month_date"] = pd.to_datetime(df["month_date"], format="%Y-%m", errors="coerce")

        # Drop nulls
        df = df.dropna(subset=["month_date", "fao_veg_oil_index"])

        # Filter to start date
        start_date = pd.Timestamp(config["pipeline"]["start_date"])
        df = df[df["month_date"] >= start_date]

        df = df.sort_values("month_date").reset_index(drop=True)

        logger.info(f"fao: {len(df)} rows extracted, {df['month_date'].min()} → {df['month_date'].max()}")
        return df

    except Exception as e:
        logger.error(f"fao extraction failed: {e}")
        return pd.DataFrame()