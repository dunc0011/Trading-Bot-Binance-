# SQL Query Guide - Bot Performance Analysis

## Database Location
All data is stored in: `data/performance.db` (SQLite)

## Quick Access

```bash
# Open SQLite CLI
sqlite3 data/performance.db

# Or use Docker
docker-compose exec trading-bot sqlite3 data/performance.db
```

---

## 📊 Core Queries

### View Database Schema
```sql
-- See all tables
.tables

-- See structure of trades table
.schema trades

-- See structure of portfolio_snapshots table
.schema portfolio_snapshots
```

### All Recent Trades (Enhanced Fields)
```sql
SELECT 
    id,
    symbol,
    entry_price,
    exit_price,
    pnl_pct,
    ml_confidence,
    market_regime,
    volatility,
    rsi,
    hour_of_day,
    day_of_week,
    hold_duration_seconds,
    exit_strategy,
    reason,
    exit_time
FROM trades
ORDER BY exit_time DESC
LIMIT 50;
```

### Best Performing Pairs (Last 30 Days)
```sql
SELECT 
    symbol,
    COUNT(*) as trade_count,
    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate,
    ROUND(SUM(pnl), 2) as total_pnl_usd,
    ROUND(AVG(ml_confidence) * 100, 1) as avg_confidence
FROM trades
WHERE exit_time >= datetime('now', '-30 days')
GROUP BY symbol
HAVING COUNT(*) >= 5  -- Min 5 trades
ORDER BY avg_pnl_pct DESC;
```

### Worst Performing Pairs
```sql
SELECT 
    symbol,
    COUNT(*) as trade_count,
    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate,
    ROUND(SUM(pnl), 2) as total_pnl_usd
FROM trades
WHERE exit_time >= datetime('now', '-30 days')
GROUP BY symbol
HAVING COUNT(*) >= 3
ORDER BY avg_pnl_pct ASC
LIMIT 10;
```

### Performance by Hour of Day
```sql
SELECT 
    hour_of_day,
    COUNT(*) as trades,
    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
FROM trades
WHERE hour_of_day IS NOT NULL
    AND exit_time >= datetime('now', '-30 days')
GROUP BY hour_of_day
HAVING COUNT(*) >= 3
ORDER BY hour_of_day;
```

### Performance by Day of Week
```sql
SELECT 
    CASE day_of_week
        WHEN 0 THEN 'Monday'
        WHEN 1 THEN 'Tuesday'
        WHEN 2 THEN 'Wednesday'
        WHEN 3 THEN 'Thursday'
        WHEN 4 THEN 'Friday'
        WHEN 5 THEN 'Saturday'
        WHEN 6 THEN 'Sunday'
    END as day_name,
    COUNT(*) as trades,
    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
FROM trades
WHERE day_of_week IS NOT NULL
    AND exit_time >= datetime('now', '-30 days')
GROUP BY day_of_week
ORDER BY day_of_week;
```

### Performance by Market Regime
```sql
SELECT 
    market_regime,
    COUNT(*) as trades,
    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate,
    ROUND(AVG(volatility), 4) as avg_volatility
FROM trades
WHERE market_regime IS NOT NULL
    AND exit_time >= datetime('now', '-30 days')
GROUP BY market_regime
ORDER BY avg_pnl_pct DESC;
```

### Performance by ML Confidence Level
```sql
SELECT 
    CASE 
        WHEN ml_confidence < 0.60 THEN '50-60%'
        WHEN ml_confidence < 0.70 THEN '60-70%'
        WHEN ml_confidence < 0.80 THEN '70-80%'
        WHEN ml_confidence < 0.90 THEN '80-90%'
        ELSE '90-100%'
    END as confidence_range,
    COUNT(*) as trades,
    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
FROM trades
WHERE ml_confidence IS NOT NULL
    AND exit_time >= datetime('now', '-30 days')
GROUP BY confidence_range
ORDER BY confidence_range;
```

### Hold Duration Analysis
```sql
SELECT 
    CASE 
        WHEN hold_duration_seconds < 300 THEN '< 5min'
        WHEN hold_duration_seconds < 900 THEN '5-15min'
        WHEN hold_duration_seconds < 1800 THEN '15-30min'
        WHEN hold_duration_seconds < 3600 THEN '30-60min'
        ELSE '> 1hr'
    END as duration_bucket,
    COUNT(*) as trades,
    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate,
    ROUND(AVG(hold_duration_seconds) / 60, 1) as avg_minutes
FROM trades
WHERE hold_duration_seconds IS NOT NULL
    AND exit_time >= datetime('now', '-30 days')
GROUP BY duration_bucket
ORDER BY 
    CASE duration_bucket
        WHEN '< 5min' THEN 1
        WHEN '5-15min' THEN 2
        WHEN '15-30min' THEN 3
        WHEN '30-60min' THEN 4
        ELSE 5
    END;
```

### Overall Performance Summary
```sql
SELECT 
    COUNT(*) as total_trades,
    ROUND(SUM(pnl), 2) as total_pnl_usd,
    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate,
    ROUND(MAX(pnl_pct), 2) as best_trade_pct,
    ROUND(MIN(pnl_pct), 2) as worst_trade_pct,
    ROUND(AVG(hold_duration_seconds) / 60, 1) as avg_hold_minutes
FROM trades
WHERE exit_time >= datetime('now', '-30 days');
```

### Recent Losing Trades (Learn from Mistakes)
```sql
SELECT 
    symbol,
    ROUND(pnl_pct, 2) as loss_pct,
    ROUND(ml_confidence * 100, 1) as confidence,
    market_regime,
    ROUND(volatility, 4) as volatility,
    rsi,
    hour_of_day,
    reason,
    exit_time
FROM trades
WHERE pnl < 0
    AND exit_time >= datetime('now', '-7 days')
ORDER BY pnl_pct ASC
LIMIT 20;
```

### Recent Winning Trades (Learn from Success)
```sql
SELECT 
    symbol,
    ROUND(pnl_pct, 2) as profit_pct,
    ROUND(ml_confidence * 100, 1) as confidence,
    market_regime,
    ROUND(volatility, 4) as volatility,
    rsi,
    hour_of_day,
    ROUND(hold_duration_seconds / 60, 1) as hold_minutes,
    exit_time
FROM trades
WHERE pnl > 0
    AND exit_time >= datetime('now', '-7 days')
ORDER BY pnl_pct DESC
LIMIT 20;
```

### Daily Performance
```sql
SELECT 
    DATE(exit_time) as trade_date,
    COUNT(*) as trades,
    ROUND(SUM(pnl), 2) as daily_pnl_usd,
    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
FROM trades
WHERE exit_time >= datetime('now', '-30 days')
GROUP BY DATE(exit_time)
ORDER BY trade_date DESC;
```

### Pairs Worth Avoiding (Low Win Rate)
```sql
SELECT 
    symbol,
    COUNT(*) as trades,
    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate,
    ROUND(SUM(pnl), 2) as total_loss
FROM trades
WHERE exit_time >= datetime('now', '-30 days')
GROUP BY symbol
HAVING COUNT(*) >= 5
    AND win_rate < 45
ORDER BY win_rate ASC;
```

---

## 🚀 Advanced Queries

### Streak Analysis (Consecutive Wins/Losses)
```sql
WITH streaks AS (
    SELECT 
        symbol,
        pnl_pct,
        exit_time,
        ROW_NUMBER() OVER (ORDER BY exit_time) - 
        ROW_NUMBER() OVER (PARTITION BY CASE WHEN pnl > 0 THEN 1 ELSE 0 END ORDER BY exit_time) as streak_group,
        CASE WHEN pnl > 0 THEN 1 ELSE 0 END as is_win
    FROM trades
    WHERE exit_time >= datetime('now', '-30 days')
)
SELECT 
    CASE WHEN is_win = 1 THEN 'Winning' ELSE 'Losing' END as streak_type,
    COUNT(*) as streak_length,
    MIN(exit_time) as streak_start,
    MAX(exit_time) as streak_end
FROM streaks
GROUP BY streak_group, is_win
HAVING COUNT(*) >= 3
ORDER BY streak_length DESC
LIMIT 10;
```

### RSI Sweet Spot
```sql
SELECT 
    CASE 
        WHEN rsi < 30 THEN 'Oversold (<30)'
        WHEN rsi < 40 THEN '30-40'
        WHEN rsi < 50 THEN '40-50'
        WHEN rsi < 60 THEN '50-60'
        WHEN rsi < 70 THEN '60-70'
        ELSE 'Overbought (>70)'
    END as rsi_range,
    COUNT(*) as trades,
    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
FROM trades
WHERE rsi IS NOT NULL
    AND exit_time >= datetime('now', '-30 days')
GROUP BY rsi_range
ORDER BY 
    CASE rsi_range
        WHEN 'Oversold (<30)' THEN 1
        WHEN '30-40' THEN 2
        WHEN '40-50' THEN 3
        WHEN '50-60' THEN 4
        WHEN '60-70' THEN 5
        ELSE 6
    END;
```

### Volatility Impact
```sql
SELECT 
    CASE 
        WHEN volatility < 0.01 THEN 'Low (<1%)'
        WHEN volatility < 0.02 THEN 'Medium (1-2%)'
        ELSE 'High (>2%)'
    END as volatility_level,
    COUNT(*) as trades,
    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
FROM trades
WHERE volatility IS NOT NULL
    AND exit_time >= datetime('now', '-30 days')
GROUP BY volatility_level
ORDER BY volatility_level;
```

---

## 📁 Export Queries

### Export to CSV
```bash
# Export all trades to CSV
sqlite3 -header -csv data/performance.db "SELECT * FROM trades;" > trades_export.csv

# Export performance summary
sqlite3 -header -csv data/performance.db "
SELECT 
    symbol,
    COUNT(*) as trades,
    ROUND(AVG(pnl_pct), 2) as avg_pnl_pct,
    ROUND(SUM(CASE WHEN pnl > 0 THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 1) as win_rate
FROM trades
WHERE exit_time >= datetime('now', '-30 days')
GROUP BY symbol
ORDER BY avg_pnl_pct DESC;
" > performance_by_symbol.csv
```

---

## 🛠 Useful Commands

### Count Total Trades
```sql
SELECT COUNT(*) FROM trades;
```

### Check if Enhanced Fields Exist
```sql
SELECT COUNT(*) as enhanced_trades
FROM trades
WHERE market_regime IS NOT NULL;
```

### Delete Old Data (Cleanup)
```sql
-- Delete trades older than 90 days
DELETE FROM trades WHERE exit_time < datetime('now', '-90 days');

-- Vacuum to reclaim space
VACUUM;
```

### Check Database Size
```bash
du -h data/performance.db
```

---

## 💡 Pro Tips

1. **Save common queries** as shell aliases:
   ```bash
   alias bot-stats="sqlite3 data/performance.db 'SELECT COUNT(*), ROUND(AVG(pnl_pct),2), ROUND(SUM(CASE WHEN pnl>0 THEN 1.0 ELSE 0 END)/COUNT(*)*100,1) FROM trades;'"
   ```

2. **Use `.mode column` for readable output:**
   ```sql
   .mode column
   .headers on
   SELECT * FROM trades LIMIT 5;
   ```

3. **Create views for frequent queries:**
   ```sql
   CREATE VIEW top_pairs AS
   SELECT symbol, COUNT(*) as trades, AVG(pnl_pct) as avg_pnl
   FROM trades
   GROUP BY symbol
   ORDER BY avg_pnl DESC;
   
   -- Then just:
   SELECT * FROM top_pairs;
   ```

---

**All your trading data is permanently stored and queryable!** 📊
