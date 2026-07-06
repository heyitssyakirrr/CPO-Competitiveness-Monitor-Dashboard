/*
stg_indonesia_supply — staging wrapper over clean.indonesia_supply.

Source:  clean.indonesia_supply  (written by transform_usda.py)
Purpose: type casting and clean interface for mart models.

Data is USDA annual figures forward-filled to monthly grain.
9 rows (Jan 2015 – Sep 2015) are intentionally NULL — the first USDA
marketing year starts Oct 2015. This is expected, not a bug.

USDA marketing year runs October 1 → September 30.
marketing_year 2024 = October 2024 through September 2025.

Columns:
    month_date                      — month start date
    marketing_year                  — e.g. 2024 (nullable for Jan–Sep 2015)
    production_1000mt               — Indonesia palm oil production (thousand MT)
    industrial_consumption_1000mt   — biodiesel use only (Attribute_ID 140)
    exports_1000mt                  — Indonesia palm oil exports (thousand MT)
    ending_stocks_1000mt            — Indonesia palm oil ending stocks (thousand MT)
    biodiesel_share_pct             — industrial_consumption / production × 100
*/

with source as (
    select * from {{ source('clean', 'indonesia_supply') }}
)

select
    month_date::date                            as month_date,
    marketing_year::integer                     as marketing_year,
    production_1000mt::numeric(10, 2)           as production_1000mt,
    industrial_consumption_1000mt::numeric(10, 2) as industrial_consumption_1000mt,
    exports_1000mt::numeric(10, 2)              as exports_1000mt,
    ending_stocks_1000mt::numeric(10, 2)        as ending_stocks_1000mt,
    biodiesel_share_pct::numeric(6, 2)          as biodiesel_share_pct

from source