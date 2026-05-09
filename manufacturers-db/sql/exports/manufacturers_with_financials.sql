-- Latest financial snapshot per entity.
SELECT
    e.id            AS entity_id,
    e.canonical_name,
    e.country,
    f.period_end,
    f.currency,
    f.revenue,
    f.net_income,
    f.assets,
    f.employees,
    f.source
FROM entities e
JOIN LATERAL (
    SELECT *
      FROM entity_financials f
     WHERE f.entity_id = e.id
     ORDER BY f.period_end DESC NULLS LAST
     LIMIT 1
) f ON TRUE
ORDER BY f.revenue DESC NULLS LAST;
