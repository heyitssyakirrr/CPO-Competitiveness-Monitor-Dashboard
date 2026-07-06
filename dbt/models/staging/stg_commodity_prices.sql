/*
stg_commodity_prices — staging wrapper over clean.commodity_prices.

Source:  clean.commodity_prices  (written by transform_prices.py)
Purpose: rename columns to business-friendly names and cast types.
         No calculations here — staging models are just a clean interface
         between the raw clean tables and the mart models above them.

Columns passed through:
    month_date              — month start date
    cpo_price               — CPO USD/tonne (World Bank)
    soyoil_price            — soybean oil USD/tonne (World Bank)
    sunflower_price         — sunflower oil USD/tonne (World Bank)
    rapeseed_price          — rapeseed oil USD/tonne (World Bank)
    brent_crude_usd         — Brent crude USD/barrel (yfinance, month-end last)
    soybean_futures_usd     — soybean futures USD/bushel (yfinance ÷100, month-end last)
*/

with source as (
    select * from {{ source('clean', 'commodity_prices') }}
)

select
    month_date::date                    as month_date,
    cpo_price::numeric(10, 2)           as cpo_price,
    soyoil_price::numeric(10, 2)        as soyoil_price,
    sunflower_price::numeric(10, 2)     as sunflower_price,
    rapeseed_price::numeric(10, 2)      as rapeseed_price,
    brent_crude_usd::numeric(10, 2)     as brent_crude_usd,
    soybean_futures_usd::numeric(10, 4) as soybean_futures_usd

from source