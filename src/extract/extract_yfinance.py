import yfinance as yf
import pandas as pd
from src.utils import get_logger

logger = get_logger(__name__)


def extract_yfinance(config: dict) -> pd.DataFrame:
    """
    Download daily FX rates and futures prices from yfinance.

    Tickers from config:
        currencies: MYRUSD=X, IDRUSD=X, INRUSD=X, CNYUSD=X
        futures:    BZ=F (Brent crude), ZS=F (soybean)

    Note on FX direction: yfinance returns MYRUSD=X as USD-per-MYR (~0.22).
    We store the raw values here — inversion to MYR-per-USD happens in
    transform_currency.py to keep this extractor simple and testable.
    """
    try:
        start_date = pd.Timestamp(config["pipeline"]["start_date"])
        tickers = config["currencies"] + config["futures"]

        logger.info("yfinance: pulling %d tickers from %s...", len(tickers), start_date.date())

        df = yf.download(
            tickers,
            start=start_date,
            auto_adjust=True,
            progress=False,
        )

        # Keep Close prices only
        df = df["Close"]

        # Flatten MultiIndex columns (yfinance returns MultiIndex when >1 ticker)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(0)

        # Rename to pipeline-standard names
        rename_map = {
            "MYRUSD=X": "usd_myr",
            "IDRUSD=X": "usd_idr",
            "INRUSD=X": "usd_inr",
            "CNYUSD=X": "usd_cny",
            "BZ=F":     "brent_crude_usd",
            "ZS=F":     "soybean_futures_raw",
        }
        df = df.rename(columns=rename_map)

        # Convert soybean futures: yfinance returns US cents/bushel → USD/bushel
        df["soybean_futures_usd"] = df["soybean_futures_raw"] / 100
        df = df.drop(columns=["soybean_futures_raw"])

        # Reset index so date becomes a plain column
        df = df.reset_index()
        df = df.rename(columns={"Date": "date", "Datetime": "date"})

        # Drop rows where ALL price columns are null (weekends / market holidays)
        price_cols = [c for c in df.columns if c != "date"]
        df = df.dropna(how="all", subset=price_cols)

        df = df.sort_values("date").reset_index(drop=True)

        logger.info(
            "yfinance: %d daily rows | %s → %s | nulls per col: %s",
            len(df),
            df["date"].min().date(),
            df["date"].max().date(),
            {col: int(df[col].isna().sum()) for col in price_cols},
        )
        return df

    except Exception as exc:
        logger.error("yfinance: unexpected failure — %s", exc, exc_info=True)
        return pd.DataFrame()