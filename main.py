"""
main.py — CPO Competitiveness Monitor ETL pipeline orchestrator.

Execution order:
    1. Extract  — all four sources in parallel (independent, each isolated in try/except)
    2. Load raw — upsert all four DataFrames into raw schema
    3. Transform — sequential (each step reads from the DB, not from memory,
                   so a partial raw load still produces the best possible clean output)
    4. Summary  — print a run report so GitHub Actions logs are easy to read

Usage:
    python main.py                        # full pipeline run
    python main.py --extract-only         # stop after raw load (useful for debugging)
    python main.py --transform-only       # skip extraction, re-transform from existing raw

Environment:
    DATABASE_URL must be set (see .env / GitHub Actions secrets / Streamlit Cloud secrets).
    Copy .env.example → .env and fill in DATABASE_URL before first local run.

GitHub Actions:
    Scheduled monthly on the 5th at 06:00 UTC (see .github/workflows/etl.yml).
    DATABASE_URL is injected as a repository secret — never committed.
"""

import argparse
import sys
import time
from datetime import datetime, timezone

import yaml
from dotenv import load_dotenv

from src.extract.extract_fao import extract_fao
from src.extract.extract_usda import extract_usda
from src.extract.extract_worldbank import extract_worldbank
from src.extract.extract_yfinance import extract_yfinance
from src.load import load_raw, _get_engine
from src.transform.transform_currency import transform_currency
from src.transform.transform_prices import transform_prices
from src.transform.transform_spreads import transform_spreads
from src.transform.transform_usda import transform_usda
from src.utils import get_logger

load_dotenv()
logger = get_logger(__name__)


# ── Config loader ─────────────────────────────────────────────────────────────

def _load_config(path: str = "config.yml") -> dict:
    """
    Load the pipeline config from config.yml.
    All extractor/transform parameters (start_date, POGO factor, thresholds)
    live in config.yml — not hard-coded in the modules themselves.
    """
    with open(path) as f:
        config = yaml.safe_load(f)
    logger.info("main: config loaded from %s", path)
    return config


# ── Extract phase ──────────────────────────────────────────────────────────────

def run_extract(config: dict) -> dict:
    """
    Run all four extractors independently. A failure in one source does NOT
    block the others — each extractor returns an empty DataFrame on failure,
    and the load layer skips empty DataFrames gracefully.

    Returns:
        dict of {source_name: DataFrame}
    """
    logger.info("═" * 60)
    logger.info("main: EXTRACT phase starting")

    extractors = {
        "wb_prices":      (extract_worldbank, config),
        "yfinance_daily": (extract_yfinance,  config),
        "usda_indonesia": (extract_usda,       config),
        "fao_ffpi":       (extract_fao,        config),
    }

    results = {}
    for name, (fn, cfg) in extractors.items():
        t0 = time.time()
        try:
            df = fn(cfg)
            elapsed = time.time() - t0
            status = "✅" if not df.empty else "⚠️  empty"
            logger.info(
                "main: %s %s — %d rows in %.1fs",
                status, name, len(df), elapsed,
            )
        except Exception as exc:
            elapsed = time.time() - t0
            logger.error(
                "main: ❌ %s — unhandled exception after %.1fs: %s",
                name, elapsed, exc, exc_info=True,
            )
            import pandas as pd
            df = pd.DataFrame()
        results[name] = df

    n_ok = sum(1 for df in results.values() if not df.empty)
    logger.info("main: extract complete — %d/%d sources succeeded", n_ok, len(results))
    return results


# ── Load phase ────────────────────────────────────────────────────────────────

def run_load(frames: dict, engine) -> dict:
    """
    Upsert all four raw DataFrames into the Supabase raw schema.

    Args:
        frames: Output from run_extract — {source_name: DataFrame}.
        engine: Active SQLAlchemy engine.

    Returns:
        dict of {table_name: rows_upserted} from load_raw.
    """
    logger.info("═" * 60)
    logger.info("main: LOAD (raw) phase starting")

    results = load_raw(
        wb_prices      = frames.get("wb_prices",      __import__("pandas").DataFrame()),
        yfinance_daily = frames.get("yfinance_daily", __import__("pandas").DataFrame()),
        usda_indonesia = frames.get("usda_indonesia", __import__("pandas").DataFrame()),
        fao_ffpi       = frames.get("fao_ffpi",       __import__("pandas").DataFrame()),
        engine         = engine,
    )

    total = sum(results.values())
    logger.info("main: raw load complete — %d total rows upserted", total)
    return results


# ── Transform phase ────────────────────────────────────────────────────────────

def run_transform(engine) -> dict:
    """
    Run all four transforms sequentially. Each reads from the DB (not from memory)
    so transforms work correctly even after a --transform-only re-run.

    Order matters:
        1. transform_prices  — needs raw.wb_prices + raw.yfinance_daily
        2. transform_currency — needs raw.yfinance_daily
        3. transform_usda    — needs raw.usda_indonesia + raw.wb_prices (spine)
        4. transform_spreads — needs all three clean tables above + raw.fao_ffpi

    Returns:
        dict of {transform_name: DataFrame_or_empty}
    """
    logger.info("═" * 60)
    logger.info("main: TRANSFORM phase starting")

    steps = [
        ("transform_prices",   transform_prices),
        ("transform_currency", transform_currency),
        ("transform_usda",     transform_usda),
        ("transform_spreads",  transform_spreads),
    ]

    results = {}
    for name, fn in steps:
        t0 = time.time()
        try:
            df = fn(engine)
            elapsed = time.time() - t0
            status = "✅" if not df.empty else "⚠️  empty"
            logger.info(
                "main: %s %s — %d rows in %.1fs",
                status, name, len(df), elapsed,
            )
        except Exception as exc:
            elapsed = time.time() - t0
            logger.error(
                "main: ❌ %s — failed after %.1fs: %s",
                name, elapsed, exc, exc_info=True,
            )
            import pandas as pd
            df = pd.DataFrame()
        results[name] = df

    n_ok = sum(1 for df in results.values() if not df.empty)
    logger.info("main: transform complete — %d/%d steps succeeded", n_ok, len(steps))
    return results


# ── Run summary ────────────────────────────────────────────────────────────────

def _print_summary(
    run_start: datetime,
    extract_results: dict,
    load_results: dict,
    transform_results: dict,
) -> None:
    """Print a structured run summary — makes GitHub Actions logs easy to skim."""
    elapsed = (datetime.now(timezone.utc) - run_start).total_seconds()

    logger.info("═" * 60)
    logger.info("main: PIPELINE RUN SUMMARY")
    logger.info("main: total elapsed %.1fs", elapsed)
    logger.info("main:")
    logger.info("main: EXTRACT")
    for name, df in extract_results.items():
        status = f"{len(df)} rows" if not df.empty else "FAILED / empty"
        logger.info("main:   %-22s %s", name, status)
    logger.info("main:")
    logger.info("main: LOAD (raw rows upserted)")
    for name, n in load_results.items():
        logger.info("main:   %-22s %d rows", name, n)
    logger.info("main:")
    logger.info("main: TRANSFORM")
    for name, df in transform_results.items():
        status = f"{len(df)} rows" if not df.empty else "FAILED / empty"
        logger.info("main:   %-22s %s", name, status)
    logger.info("═" * 60)

    # Exit with non-zero code if anything critical failed — lets GitHub Actions
    # flag the run as failed rather than silently succeeding with bad data.
    critical_failures = [
        name for name, df in transform_results.items() if df.empty
    ]
    if critical_failures:
        logger.error(
            "main: %d critical failures — %s — GitHub Actions run will be marked FAILED",
            len(critical_failures), critical_failures,
        )
        sys.exit(1)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CPO Competitiveness Monitor ETL pipeline"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--extract-only",
        action="store_true",
        help="Run extract + raw load only; skip transforms. Useful for debugging extractors.",
    )
    group.add_argument(
        "--transform-only",
        action="store_true",
        help="Skip extraction; re-run transforms from existing raw tables. "
             "Useful when source data is fine but transform logic changed.",
    )
    return parser.parse_args()


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    args = _parse_args()
    run_start = datetime.now(timezone.utc)

    logger.info("═" * 60)
    logger.info(
        "main: CPO Competitiveness Monitor ETL — run started %s UTC",
        run_start.strftime("%Y-%m-%d %H:%M:%S"),
    )
    if args.extract_only:
        logger.info("main: mode = EXTRACT ONLY (transforms skipped)")
    elif args.transform_only:
        logger.info("main: mode = TRANSFORM ONLY (extraction skipped)")
    else:
        logger.info("main: mode = FULL PIPELINE")

    config = _load_config()
    engine = _get_engine()

    # ── Extract + Load ────────────────────────────────────────────────────────
    extract_results = {}
    load_results    = {}

    if not args.transform_only:
        extract_results = run_extract(config)
        load_results    = run_load(extract_results, engine)

    if args.extract_only:
        _print_summary(run_start, extract_results, load_results, {})
        return

    # ── Transform ─────────────────────────────────────────────────────────────
    transform_results = run_transform(engine)

    _print_summary(run_start, extract_results, load_results, transform_results)


if __name__ == "__main__":
    main()