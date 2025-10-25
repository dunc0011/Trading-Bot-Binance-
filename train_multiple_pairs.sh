#!/bin/bash
# Train advanced ML models for multiple crypto pairs
# This will take 2-4 hours depending on how many pairs you train

set -e  # Exit on error

echo "========================================="
echo "Multi-Pair Advanced ML Model Training"
echo "========================================="
echo ""

# Configuration
INTERVAL="15m"
LOOKBACK_DAYS=180
OPTIMIZE="--optimize-hyperparams"

# List of top crypto pairs to train (sorted by volume)
PAIRS=(
    "BTCUSDT"
    "ETHUSDT"
    "BNBUSDT"
    "SOLUSDT"
    "XRPUSDT"
    # Add more pairs as needed
    # "ADAUSDT"
    # "DOGEUSDT"
    # "DOTUSDT"
    # "MATICUSDT"
    # "AVAXUSDT"
)

echo "Training ${#PAIRS[@]} pairs with:"
echo "  Interval: $INTERVAL"
echo "  Lookback: $LOOKBACK_DAYS days"
echo "  Optimization: Enabled"
echo ""
echo "Estimated time: $((${#PAIRS[@]} * 20-30)) minutes"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "Training cancelled."
    exit 0
fi

# Create log directory
mkdir -p logs

# Train each pair
SUCCESSFUL=0
FAILED=0

for PAIR in "${PAIRS[@]}"
do
    echo ""
    echo "========================================="
    echo "Training: $PAIR ($((SUCCESSFUL + FAILED + 1))/${#PAIRS[@]})"
    echo "========================================="
    
    # Run training in Docker
    docker-compose exec -T web-ui python -m src.utils.train_advanced_model \
        --symbol "$PAIR" \
        --interval "$INTERVAL" \
        --lookback-days $LOOKBACK_DAYS \
        $OPTIMIZE \
        2>&1 | tee "logs/training_${PAIR}_${INTERVAL}.log"
    
    # Check if successful
    if [ $? -eq 0 ]; then
        echo "✅ SUCCESS: $PAIR trained"
        ((SUCCESSFUL++))
    else
        echo "❌ FAILED: $PAIR training failed"
        ((FAILED++))
    fi
    
    # Small delay between trainings
    sleep 2
done

echo ""
echo "========================================="
echo "Training Complete!"
echo "========================================="
echo "Successful: $SUCCESSFUL"
echo "Failed: $FAILED"
echo ""
echo "Models saved to: models/advanced_ml/"
echo "Logs saved to: logs/training_*.log"
echo ""

# List trained models
echo "Trained models:"
ls -lh models/advanced_ml/*.joblib 2>/dev/null || echo "No models found"
echo ""

echo "Next steps:"
echo "1. Review model performance in logs"
echo "2. Start multi-pair bot: docker-compose up -d"
echo "3. Check dashboard: http://localhost:5000"
