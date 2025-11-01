#!/bin/bash
# Quick Stats Checker for Trading Bot

DB="data/performance.db"

echo "===================="
echo "  BOT STATISTICS"
echo "===================="
echo ""

# Overall stats
echo "📊 OVERALL PERFORMANCE (Last 30 Days)"
echo "--------------------------------------"
sqlite3 -column -header "$DB" "
SELECT 
    COUNT(*) as trades,
    ROUND(SUM(pnl), 2) as total_pnl_usd,
    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
FROM trades
WHERE exit_time >= datetime('now', '-30 days');
"

echo ""
echo "🏆 TOP 5 PERFORMING PAIRS"
echo "--------------------------------------"
sqlite3 -column -header "$DB" "
SELECT 
    symbol,
    COUNT(*) as trades,
    ROUND(AVG(pnl_pct), 2) as avg_pnl,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
FROM trades
WHERE exit_time >= datetime('now', '-30 days')
GROUP BY symbol
HAVING COUNT(*) >= 3
ORDER BY avg_pnl DESC
LIMIT 5;
"

echo ""
echo "⏰ BEST TRADING HOURS"
echo "--------------------------------------"
sqlite3 -column -header "$DB" "
SELECT 
    hour_of_day as hour,
    COUNT(*) as trades,
    ROUND(AVG(pnl_pct), 2) as avg_pnl,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
FROM trades
WHERE hour_of_day IS NOT NULL
    AND exit_time >= datetime('now', '-30 days')
GROUP BY hour_of_day
HAVING COUNT(*) >= 2
ORDER BY avg_pnl DESC
LIMIT 5;
"

echo ""
echo "📈 RECENT TRADES (Last 10)"
echo "--------------------------------------"
sqlite3 -column -header "$DB" "
SELECT 
    symbol,
    ROUND(pnl_pct, 2) as pnl_pct,
    ROUND(ml_confidence * 100, 1) as conf,
    market_regime as regime,
    substr(exit_time, 12, 5) as time
FROM trades
ORDER BY exit_time DESC
LIMIT 10;
"

echo ""
echo "✅ Enhanced fields:" $(sqlite3 "$DB" "SELECT COUNT(*) FROM trades WHERE market_regime IS NOT NULL;") "trades"
echo ""
