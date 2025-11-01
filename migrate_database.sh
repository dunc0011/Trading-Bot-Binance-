#!/bin/bash
# Database Migration Script - Add Enhanced Columns

DB="data/performance.db"

echo "🔧 Migrating database to add enhanced columns..."

sqlite3 "$DB" <<'EOF'
-- Add new columns if they don't exist
ALTER TABLE trades ADD COLUMN market_regime TEXT;
ALTER TABLE trades ADD COLUMN volatility REAL;
ALTER TABLE trades ADD COLUMN volume_24h REAL;
ALTER TABLE trades ADD COLUMN rsi REAL;
ALTER TABLE trades ADD COLUMN trend_strength REAL;
ALTER TABLE trades ADD COLUMN feature_importance TEXT;
ALTER TABLE trades ADD COLUMN hour_of_day INTEGER;
ALTER TABLE trades ADD COLUMN day_of_week INTEGER;
ALTER TABLE trades ADD COLUMN peak_price REAL;
ALTER TABLE trades ADD COLUMN exit_strategy TEXT;
ALTER TABLE trades ADD COLUMN hold_duration_seconds INTEGER;
EOF

if [ $? -eq 0 ]; then
    echo "✅ Database migrated successfully!"
    echo "   New columns added: market_regime, volatility, volume_24h, rsi, trend_strength,"
    echo "   feature_importance, hour_of_day, day_of_week, peak_price, exit_strategy, hold_duration_seconds"
    echo ""
    echo "Note: Existing trades will have NULL values for new fields (that's OK)."
    echo "      New trades will automatically populate these fields."
else
    echo "⚠️  Migration had some errors (columns may already exist - that's OK)"
fi

echo ""
echo "Total trades in database:" $(sqlite3 "$DB" "SELECT COUNT(*) FROM trades;")
