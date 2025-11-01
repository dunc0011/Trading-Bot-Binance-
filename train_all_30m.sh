#!/bin/bash
# Train ML models for top pairs on 30m timeframe

PAIRS=(
  "BTCUSDT"
  "ETHUSDT"
  "BNBUSDT"
  "SOLUSDT"
  "XRPUSDT"
  "ADAUSDT"
  "DOGEUSDT"
  "AVAXUSDT"
  "DOTUSDT"
  "MATICUSDT"
  "LINKUSDT"
  "ATOMUSDT"
  "NEARUSDT"
  "UNIUSDT"
  "LTCUSDT"
)

echo "🚀 Training ML models for ${#PAIRS[@]} pairs on 30m timeframe..."
echo "This will take 15-30 minutes depending on CPU"
echo ""

for pair in "${PAIRS[@]}"; do
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "📊 Training $pair (30m, 90 days lookback)..."
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  
  docker-compose exec -T web-ui python -m src.utils.train_ml_model \
    --symbol "$pair" \
    --interval 30m \
    --lookback-days 90 \
    --model-dir models/ml_ema \
    --log-level INFO
  
  if [ $? -eq 0 ]; then
    echo "✅ $pair trained successfully"
  else
    echo "❌ $pair training failed"
  fi
  
  echo ""
  sleep 2
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Training complete! Models saved to models/ml_ema/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Next steps:"
echo "1. Review model performance in logs"
echo "2. Set DRY_RUN=true to test in paper trading"
echo "3. Monitor for 24-48 hours"
echo "4. Set DRY_RUN=false to go live"
