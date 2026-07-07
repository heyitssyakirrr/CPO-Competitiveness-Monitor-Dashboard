/*
mart_oil_substitution_spreads — Panel 3 data.

Business question:
    Is CPO losing price competitiveness against substitute vegetable oils?
    Are buyers likely to switch to soybean, sunflower, or rapeseed oil?

Used by dashboard Panel 3:
    KPI cards: CPO vs soy spread, CPO vs sunflower, CPO vs rapeseed, substitution risk
    Chart 1:   Three spread lines with −$50 threshold reference line
    Chart 2:   Raw prices — CPO, soy, sunflower, rapeseed (all USD/tonne)
    Chart 3:   Headline chart — POGO spread + CPO vs soy on dual axis

Substitution risk logic (applied to soy spread only — primary benchmark):
    HIGH     → cpo_vs_soy_spread > −50   (CPO close to or above soy price)
    MODERATE → cpo_vs_soy_spread > −100
    LOW      → cpo_vs_soy_spread ≤ −100  (CPO much cheaper — buyers stick with CPO)

Interpretation:
    Negative spread = CPO is cheaper than the substitute (typical state).
    The more negative the spread, the stronger CPO's price advantage.
    When the spread approaches 0 or goes positive, buyers start switching.
*/

with prices as (
    select * from {{ ref('stg_commodity_prices') }}
),

all_spreads as (
    select
        month_date,
        cpo_vs_soy_spread,
        cpo_vs_sunflower_spread,
        cpo_vs_rapeseed_spread,
        substitution_risk,
        pogo_spread,
        pogo_zone
    from {{ source('clean', 'all_spreads') }}
),

joined as (
    select
        p.month_date,

        -- Raw prices for Chart 2
        p.cpo_price,
        p.soyoil_price,
        p.sunflower_price,
        p.rapeseed_price,

        -- Substitution spreads for Chart 1 (negative = CPO cheaper)
        s.cpo_vs_soy_spread,
        s.cpo_vs_sunflower_spread,
        s.cpo_vs_rapeseed_spread,

        -- Risk classification (based on soy spread only)
        s.substitution_risk,

        -- POGO for Chart 3 (headline dual-axis)
        s.pogo_spread,
        s.pogo_zone,

        -- Average spread across all three substitutes (summary signal)
        round(
            ((s.cpo_vs_soy_spread + s.cpo_vs_sunflower_spread + s.cpo_vs_rapeseed_spread) / 3.0)::numeric,
            2
        ) as avg_substitute_spread

    from prices p
    left join all_spreads s on p.month_date = s.month_date
)

select * from joined
order by month_date