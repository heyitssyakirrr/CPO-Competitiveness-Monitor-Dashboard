/*
stg_currency_rates — staging wrapper over clean.currency_rates.

Source:  clean.currency_rates  (written by transform_currency.py)
Purpose: type casting and clean interface for mart models.

All FX rates are local currency per 1 USD (already inverted from yfinance's
native direction in transform_currency.py).
Higher value = that currency has weakened against the dollar.

Columns:
    month_date      — month start date
    usd_myr         — Malaysian Ringgit per 1 USD  (~3.9–4.8 range)
    usd_idr         — Indonesian Rupiah per 1 USD  (~13,000–17,500+ range)
    usd_inr         — Indian Rupee per 1 USD       (~65–85 range)
    usd_cny         — Chinese Yuan per 1 USD       (~6.3–7.3 range)
    myr_indexed     — MYR indexed to 100 at Jan 2015 (>100 = MYR weaker than 2015)
    idr_indexed     — IDR indexed to 100 at Jan 2015 (>100 = IDR weaker than 2015)
*/

with source as (
    select * from {{ source('clean', 'currency_rates') }}
)

select
    month_date::date                as month_date,
    usd_myr::numeric(10, 4)        as usd_myr,
    usd_idr::numeric(12, 2)        as usd_idr,
    usd_inr::numeric(10, 4)        as usd_inr,
    usd_cny::numeric(10, 4)        as usd_cny,
    myr_indexed::numeric(10, 4)    as myr_indexed,
    idr_indexed::numeric(10, 4)    as idr_indexed

from source