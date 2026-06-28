import wbgapi as wb
import pandas as pd
from src.utils import get_logger

logger = get_logger()

INDICATORS = {
    "PPOIL_T_USD": "cpo_price",
    "PSOYB_T_USD": "soyoil_price",
    "PSUNO_T_USD": "sunflower_price",
    "PRAPE_T_USD": "rapeseed_price",
}

def extract_worldbank(config:dict) -> pd.DataFrame:
    try:
        start_year = int(config["pipeline"]["start_date"][:4])
        end_year = int(config["pipeline"]["end_date"][:4]) if config["pipeline"]["end_date"] != "today" else 2026

        logger.info("worldbank: pulling commodity prices...")

        df = wb.data.DataFrame(
            list(INDICATORS.keys()),
            time=range(start_year, end_year + 1),
            db=6
        )

        df = df.reset_index()

        # rename the time column to month date
        df = df.rename(columns={"time": "month_date"})

        # convert "YR2015M001" style to proper datetime
        df["month_date"] = pd.to_datetime(df["month_date"], format="%YM%m", errors="coerce")

        # drop rows where date parsing failed or all prices are null
        df = df.dropna(subset=["month_date"])
        df = df.dropna(subset=list(INDICATORS.values()), how="all")

        # filter to start_date
        start_date = pd.Timetamp(config["pipeline"]["start_date"])
        df = df[df["month_date"] >= start_date]

        # sort
        df = df.sort_values("month_date").reset_index(drop=True)

        logger.info(f"worldbank: {len(df)} rows extracted, {df["month_date"].min()} to {df["month_date"].max()}")
        return df
    
    except Exception as e:
        logger.error(f"worldbank extraction failed: {e}")
        return pd.DataFrame