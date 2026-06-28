import yfinance as yf
import pandas as pd
from src.utils import get_logger

logger = get_logger()

def extract_yfinance(config: dict) -> pd.DataFrame:
    try:
        tickers = config["currencies"] + config["futures"]
        start   = config["pipeline"]["start_date"]

        logger.info(f"yfinance: pulling {tickers}...")

        df = yf.download(
            tickers,
            start=start,
            auto_adjust=True,
            progress=False
        )

        # Keep Close prices only
        df = df["Close"]

        # Flatten column names if MultiIndex
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(0)

        # Rename columns to match notebook naming
        rename_map = {
            "INRUSD=X": "usd_inr",
            "CNYUSD=X": "usd_cny",
            "MYRUSD=X": "usd_myr",
            "IDRUSD=X": "usd_idr",
            "BZ=F":     "brent_crude_usd",
            "ZS=F":     "soybean_futures_raw",
        }
        df = df.rename(columns=rename_map)

        # Fix soybean unit — yfinance returns US cents per bushel, convert to USD
        df["soybean_futures_usd"] = df["soybean_futures_raw"] / 100
        df = df.drop(columns=["soybean_futures_raw"])

        # Reset index so date becomes a column
        df = df.reset_index()
        df = df.rename(columns={"Date": "date"})

        # Drop weekends/holidays that are all null
        df = df.dropna(how="all", subset=[c for c in df.columns if c != "date"])

        df = df.sort_values("date").reset_index(drop=True)

        logger.info(f"yfinance: {len(df)} daily rows extracted, {df['date'].min()} → {df['date'].max()}")
        return df

    except Exception as e:
        logger.error(f"yfinance extraction failed: {e}")
        return pd.DataFrame()