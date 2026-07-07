/*
mart_cpo_competitiveness — full joined summary table.

This is the master mart table. It joins every signal from all three panels
into one row per month. The Streamlit dashboard can read this single table
for the headline KPI cards and any cross-panel analysis.

Each panel also has its own focused mart table (mart_indonesia_policy_tracker,
mart_biodiesel_demand_signal, mart_oil_substitution_spreads) — the dashboard
should prefer those for panel-specific charts to avoid selecting unused columns.
Use this table for: headline KPIs, summary exports, cross-panel overlays.

Row count: same as clean.all_spreads (~137 rows as of mid-2026, +1 per month).
*/

with all_spreads as (
    select * from {{ source('clean', 'all_spreads') }}
),

supply as (
    select
        month_date,
        market_year,
        biodiesel_share_pct,
        -- Convert to MMT for display
        round(industrial_consumption_1000mt / 1000.0, 3) as biodiesel_allocation_mmt,
        round(exports_1000mt                / 1000.0, 3) as exports_mmt
    from {{ ref('stg_indonesia_supply') }}
),

fx as (
    select
        month_date,
        usd_myr,
        usd_idr,
        myr_indexed,
        idr_indexed
    from {{ ref('stg_currency_rates') }}
),

final as (
    select
        -- Date
        s.month_date,

        -- ── Panel 1 — Indonesia policy ─────────────────────────────────────
        sup.market_year,
        sup.biodiesel_allocation_mmt,
        sup.exports_mmt,
        sup.biodiesel_share_pct,

        case
            when s.month_date >= '2024-10-01' then 'B40'
            when s.month_date >= '2023-02-01' then 'B35'
            when s.month_date >= '2020-01-01' then 'B30'
            when s.month_date >= '2016-01-01' then 'B20'
            else 'Pre-B20'
        end as active_mandate,

        -- ── Panel 2 — Demand signal & price cycle ──────────────────────────
        s.cpo_price,
        s.brent_crude_usd,
        s.pogo_spread,
        s.pogo_zone,
        s.cpo_zscore,
        s.price_cycle_position,
        s.fao_veg_oil_index,

        -- Currency
        fx.usd_myr,
        fx.usd_idr,
        fx.myr_indexed,
        fx.idr_indexed,

        -- ── Panel 3 — Substitution spreads ────────────────────────────────
        s.soyoil_price,
        s.sunflower_price,
        s.rapeseed_price,
        s.cpo_vs_soy_spread,
        s.cpo_vs_sunflower_spread,
        s.cpo_vs_rapeseed_spread,
        s.substitution_risk,

        -- ── Summary signal ─────────────────────────────────────────────────
        -- A quick one-line read of the overall CPO environment this month.
        -- Useful for the headline banner on the dashboard.
        case
            when s.pogo_zone = 'PROFITABLE' and s.substitution_risk = 'LOW'  then 'STRONG TAILWIND'
            when s.pogo_zone = 'COSTLY'     and s.substitution_risk = 'HIGH' then 'STRONG HEADWIND'
            when s.pogo_zone = 'PROFITABLE' then 'MODERATE TAILWIND'
            when s.substitution_risk = 'LOW' then 'MODERATE TAILWIND'
            when s.pogo_zone = 'COSTLY'     then 'MODERATE HEADWIND'
            when s.substitution_risk = 'HIGH' then 'MODERATE HEADWIND'
            else 'NEUTRAL'
        end as overall_signal

    from all_spreads s
    left join supply sup on s.month_date = sup.month_date
    left join fx        on s.month_date = fx.month_date
)

select * from final
order by month_date