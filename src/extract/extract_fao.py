import pandas as pd
import requests
from io import StringIO
from src.utils import get_logger

logger = get_logger(__name__)

FAO_URL = (
    "https://www.fao.org/media/docs/worldfoodsituationlibraries/"
    "default-document-library/food_price_indices_data.csv"
    "?sfvrsn=523ebd2a_80&download=true"
)

REQUEST_TIMEOUT_SECONDS = 30


def extract_fao(config: dict) -> pd.DataFrame:
    """
    Download the FAO Food Price Index CSV and return the vegetable oils sub-index.

    Parsing approach confirmed from NB05:
      - skiprows=3 (skip title, base period, and blank rows)
      - names= assigned explicitly — do NOT rely on the CSV header row
        because FAO uses comma-padded headers that parse unreliably
      - Column 5 (index 5) = Oils sub-index, always regardless of header text
    """
    try:
        start_date = pd.Timestamp(config["pipeline"]["start_date"])

        logger.info("fao: downloading food price index CSV...")
        response = requests.get(FAO_URL, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        logger.info("fao: download complete (%.1f KB)", len(response.content) / 1024)

        # ── Parse exactly as NB05 confirmed ──────────────────────────────────
        # skiprows=3: skip "FAO Food Price Index", "2014-2016=100", and the
        #             blank row that follows. Row 3 is the actual header row
        #             but we ignore it by explicitly assigning names= and header=0.
        # names=: assign our own column names directly — immune to FAO renaming.
        # usecols=[0..5]: the CSV has many trailing empty comma columns; take only 6.
        df = pd.read_csv(
            StringIO(response.text),
            skiprows=3,
            usecols=[0, 1, 2, 3, 4, 5],
            names=["date_str", "food_price_index", "meat", "dairy", "cereals", "oils"],
            header=0,   # treat row 0 (after skiprows) as header, then override with names=
        )

        # ── Parse dates ───────────────────────────────────────────────────────
        # Format confirmed NB05: "1990-01"
        df["month_date"] = pd.to_datetime(df["date_str"], format="%Y-%m", errors="coerce")
        df["month_date"] = df["month_date"].dt.to_period("M").dt.to_timestamp()

        # ── Keep only the columns we need ─────────────────────────────────────
        df = df[["month_date", "oils"]].rename(columns={"oils": "fao_veg_oil_index"})

        # ── Clean ─────────────────────────────────────────────────────────────
        df["fao_veg_oil_index"] = pd.to_numeric(df["fao_veg_oil_index"], errors="coerce")
        df = df.dropna(subset=["month_date", "fao_veg_oil_index"])

        # ── Filter to pipeline start date ─────────────────────────────────────
        df = df[df["month_date"] >= start_date]
        df = df.sort_values("month_date").reset_index(drop=True)

        logger.info(
            "fao: %d rows extracted | %s → %s",
            len(df),
            df["month_date"].min().strftime("%Y-%m"),
            df["month_date"].max().strftime("%Y-%m"),
        )
        return df

    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        logger.error("fao: HTTP %s — %s", status, exc)
        return _empty_df()

    except Exception as exc:
        logger.error("fao: unexpected failure — %s", exc, exc_info=True)
        return _empty_df()


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["month_date", "fao_veg_oil_index"])