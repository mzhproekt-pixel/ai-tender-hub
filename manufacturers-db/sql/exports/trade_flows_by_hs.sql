-- Aggregate trade flows by HS code, year and reporter.
SELECT
    period,
    flow,
    reporter_iso,
    hs_code,
    SUM(trade_value_usd) AS trade_value_usd,
    SUM(net_weight_kg)   AS net_weight_kg,
    COUNT(*)             AS rows
FROM trade_flows
GROUP BY period, flow, reporter_iso, hs_code
ORDER BY period DESC, trade_value_usd DESC NULLS LAST;
