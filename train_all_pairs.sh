#!/bin/bash
# Train ALL liquid USDT pairs with proper ML validation

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         TRAINING ALL USDT PAIRS WITH FIXED ML               ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║ ✓ Recent 30-day data only                                   ║"
echo "║ ✓ Strict time-based validation                              ║"
echo "║ ✓ Realistic targets: 0.5% profit within 2h                  ║"
echo "║ ✓ All features properly lagged                              ║"
echo "║ ✓ Walk-forward validation                                   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Get all USDT pairs with >$1M daily volume
docker-compose exec -T web-ui python3 << 'EOF'
from binance.client import Client
import os

client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))

# Get all tickers
tickers = client.get_ticker()

# Filter USDT pairs with >$1M volume
pairs = []
for t in tickers:
    if t['symbol'].endswith('USDT'):
        try:
            volume = float(t['quoteVolume'])
            if volume > 1_000_000:  # $1M+ daily volume
                pairs.append(t['symbol'])
        except:
            pass

pairs.sort()
print(' '.join(pairs))
EOF

# Save pairs to variable
PAIRS=$(docker-compose exec -T web-ui python3 << 'EOF'
from binance.client import Client
import os

client = Client(os.getenv('BINANCE_API_KEY'), os.getenv('BINANCE_API_SECRET'))
tickers = client.get_ticker()
pairs = []
for t in tickers:
    if t['symbol'].endswith('USDT'):
        try:
            volume = float(t['quoteVolume'])
            if volume > 1_000_000:
                pairs.append(t['symbol'])
        except:
            pass
pairs.sort()
print(' '.join(pairs))
EOF
)

echo "Found $(echo $PAIRS | wc -w) liquid USDT pairs"
echo ""
echo "Training parameters:"
echo "  Interval: 5m"
echo "  Lookback: 30 days"
echo "  Profit Target: 0.5%"
echo "  Stop Loss: 1.0%"
echo "  Max Holding: 24 candles (2 hours)"
echo ""
read -p "Press ENTER to start training (Ctrl+C to cancel)..."

SUCCESS=0
FAILED=0
FAILED_PAIRS=""

for PAIR in $PAIRS; do
    echo ""
    echo "========================================"
    echo "Training $PAIR ($((SUCCESS + FAILED + 1)) / $(echo $PAIRS | wc -w))"
    echo "========================================"
    
    docker-compose exec -T web-ui python -m src.utils.train_advanced_model \
        --symbol "$PAIR" \
        --interval 5m \
        --lookback-days 30 \
        --profit-target 0.005 \
        --stop-loss 0.01 \
        --max-holding 24 \
        --log-level INFO
    
    if [ $? -eq 0 ]; then
        echo "✅ $PAIR trained successfully"
        SUCCESS=$((SUCCESS + 1))
    else
        echo "❌ $PAIR training failed"
        FAILED=$((FAILED + 1))
        FAILED_PAIRS="$FAILED_PAIRS $PAIR"
    fi
done

echo ""
echo "========================================"
echo "TRAINING COMPLETE"
echo "========================================"
echo "✅ Success: $SUCCESS"
echo "❌ Failed: $FAILED"
if [ -n "$FAILED_PAIRS" ]; then
    echo "Failed pairs:$FAILED_PAIRS"
fi
echo ""
echo "Models saved to: models/advanced_ml/"
echo "Restart bot: docker-compose restart web-ui"
