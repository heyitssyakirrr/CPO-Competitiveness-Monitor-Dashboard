/*
mart_biodiesel_demand_signal — Panel 2 data.

Business question:
    How strong is the biodiesel incentive right now, and where is CPO
    in its historical price cycle?

Used by dashboard Panel 2:
    KPI cards: CPO price, Brent crude, POGO spread, price cycle position
    Chart 1:   Brent crude vs CPO price (dual-axis line)
    Chart 2:   CPO z-score with CHEAP / FAIR / EXPENSIVE bands
    Chart 3:   MYR vs IDR competitiveness index (indexed to 100 at Jan 2015)

Note on z-score NULLs:
    First 35 rows (Jan 2015 – Nov 2017) have NULL cpo_zscore because the
    36-month rolling window hasn't filled yet. price_cycle_position is
    'INSUFFICIENT DATA' for those rows — never NULL. This is by design.

Note on currency context:
    When MYR weakens (usd_myr rises, myr_indexed > 100), CPO revenue in
    USD is worth more in Ringgit — benefits SD Guthrie's Malaysian operations.
    Same logic applies to IDR and Indonesian operations.
*/

with prices as (
    select * from {{ ref('stg_commodity_prices') }}
),

fx as (
    select * from {{ ref('stg_currency_rates') }}
),

-- Pull all_spreads for the pre-calculated z-score and POGO
-- (these are calculated in transform_spreads.py — we trust those numbers
--  rather than recalculating in SQL to avoid floating-point drift)
all_spreads as (
    select
        month_date,
        cpo_zscore,
        price_cycle_position,
        pogo_spread,
        pogo_zone,
        fao_veg_oil_index
    from {{ source('clean', 'all_spreads') }}
),

joined as (
    select
        p.month_date,

        -- Price inputs
        p.cpo_price,
        p.brent_crude_usd,
        round(p.brent_crude_usd * 7.3, 2) as gasoil_equiv_usd_per_tonne,

        -- POGO signal (from pre-calculated all_spreads — same values as policy tracker)
        s.pogo_spread,
        s.pogo_zone,

        -- Price cycle position
        s.cpo_zscore,
        s.price_cycle_position,

        -- FAO vegetable oil index (global basket context)
        s.fao_veg_oil_index,

        -- Currency competitiveness
        f.usd_myr,
        f.usd_idr,
        f.myr_indexed,
        f.idr_indexed

    from prices p
    left join all_spreads s on p.month_date = s.month_date
    left join fx f          on p.month_date = f.month_date
)

select * from joined
order by month_date