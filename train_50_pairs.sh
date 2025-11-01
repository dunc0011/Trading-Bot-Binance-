#!/bin/bash
# Train ML models for 50 tradeable USDT pairs

echo "🚀 Training ML EMA models for 50 tradeable pairs..."
echo ""

# List of 50 pairs from your trading log
PAIRS=(
  "BTCUSDT" "ETHUSDT" "USDCUSDT" "SOLUSDT" "XRPUSDT"
  "BNBUSDT" "ZECUSDT" "FDUSDUSDT" "GIGGLEUSDT" "VIRTUALUSDT"
  "DOGEUSDT" "ASTERUSDT" "TRXUSDT" "SUIUSDT" "AIXBTUSDT"
  "USDEUSDT" "PUMPUSDT" "XPLUSDT" "AVAXUSDT" "TAOUSDT"
  "BCHUSDT" "LINKUSDT" "EDENUSDT" "AVNTUSDT" "ADAUSDT"
  "ENAUSDT" "YBUSDT" "PEPEUSDT" "WLFIUSDT" "ZBTUSDT"
  "TURTLEUSDT" "PENGUUSDT" "ZENUSDT" "WLDUSDT" "ENSOUSDT"
  "ZKCUSDT" "LTCUSDT" "HIFIUSDT" "KDAUSDT" "UNIUSDT"
  "DEGOUSDT" "DASHUSDT" "NEARUSDT" "BAKEUSDT" "BIOUSDT"
  "TONUSDT" "MATICUSDT" "ATOMUSDT" "FILUSDT" "APTUSDT"
)

TOTAL=${#PAIRS[@]}
SUCCEEDED=0
FAILED=0
FAILED_PAIRS=()

echo "📊 Training $TOTAL pairs with ML EMA strategy..."
echo "⏱️  Interval: 1h | Lookback: 90 days"
echo "=================================================="
echo ""

# Train each pair
for i in "${!PAIRS[@]}"; do
  PAIR="${PAIRS[$i]}"
  NUM=$((i + 1))
  
  echo "[$NUM/$TOTAL] Training $PAIR..."
  
  # Run training inside Docker
  docker-compose exec -T web-ui python -m src.utils.train_ml_model \
    --symbol "$PAIR" \
    --interval 1h \
    --lookback-days 90 \
    --log-level WARNING \
    > /tmp/train_${PAIR}.log 2>&1
  
  if [ $? -eq 0 ]; then
    echo "  ✅ $PAIR completed"
    SUCCEEDED=$((SUCCEEDED + 1))
  else
    echo "  ❌ $PAIR failed (check /tmp/train_${PAIR}.log)"
    FAILED=$((FAILED + 1))
    FAILED_PAIRS+=("$PAIR")
  fi
  echo ""
done

echo "=================================================="
echo "📊 Training Summary:"
echo "  ✅ Succeeded: $SUCCEEDED/$TOTAL"
echo "  ❌ Failed: $FAILED/$TOTAL"

if [ $FAILED -gt 0 ]; then
  echo ""
  echo "❌ Failed pairs:"
  for PAIR in "${FAILED_PAIRS[@]}"; do
    echo "   - $PAIR"
  done
fi

echo ""
echo "🎉 Training complete! Restart the bot to load new models."
echo ""
echo "To view bot config:"
echo "  cat config/.env | grep -E 'SYMBOL|PAIRS'"
