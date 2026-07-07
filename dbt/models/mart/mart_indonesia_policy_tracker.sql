/*
mart_indonesia_policy_tracker — Panel 1 data.

Business question:
    Is Indonesia diverting CPO into biodiesel or releasing it to export markets?

Used by dashboard Panel 1:
    KPI cards: biodiesel allocation (MMT), exports (MMT), biodiesel share (%)
    Chart 1:   stacked bar — biodiesel vs exports — with CPO price on right axis
    Chart 2:   POGO spread with PROFITABLE / MARGINAL / COSTLY zone shading

Mandate milestones (for chart annotations):
    B20 → 2016-01-01
    B30 → 2020-01-01
    B35 → 2023-02-01
    B40 → 2024-10-01
*/

with supply as (
    select * from {{ ref('stg_indonesia_supply') }}
),

prices as (
    select
        month_date,
        cpo_price,
        brent_crude_usd
    from {{ ref('stg_commodity_prices') }}
),

joined as (
    select
        s.month_date,
        s.market_year,

        -- Supply/demand volumes (convert 1000 MT → MMT for readability on charts)
        round(s.production_1000mt          / 1000.0, 3) as production_mmt,
        round(s.industrial_consumption_1000mt / 1000.0, 3) as biodiesel_allocation_mmt,
        round(s.exports_1000mt             / 1000.0, 3) as exports_mmt,
        round(s.ending_stocks_1000mt       / 1000.0, 3) as ending_stocks_mmt,
        s.biodiesel_share_pct,

        -- CPO price and POGO for the same month
        p.cpo_price,
        p.brent_crude_usd,

        -- POGO spread (CPO price minus gas oil equivalent)
        -- Gas oil = Brent × 7.3 (industry standard barrel-to-tonne conversion)
        -- Positive POGO = CPO more expensive than gas oil = biodiesel needs subsidy
        -- Negative POGO = CPO cheaper than gas oil = biodiesel is self-funding
        round(p.cpo_price - (p.brent_crude_usd * 7.3), 2) as pogo_spread,

        case
            when p.cpo_price - (p.brent_crude_usd * 7.3) < 0   then 'PROFITABLE'
            when p.cpo_price - (p.brent_crude_usd * 7.3) < 150 then 'MARGINAL'
            else 'COSTLY'
        end as pogo_zone,

        -- Mandate milestone for chart annotations
        -- Shows which B-mandate was active in each month
        case
            when s.month_date >= '2024-10-01' then 'B40'
            when s.month_date >= '2023-02-01' then 'B35'
            when s.month_date >= '2020-01-01' then 'B30'
            when s.month_date >= '2016-01-01' then 'B20'
            else 'Pre-B20'
        end as active_mandate

    from supply s
    left join prices p on s.month_date = p.month_date
)

select * from joined
order by month_date