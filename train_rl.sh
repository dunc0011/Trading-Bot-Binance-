#!/bin/bash
# RL Agent Training Script
# Usage: ./train_rl.sh [SYMBOL] [TIMEFRAME] [STEPS]

# Default values
SYMBOL=${1:-BTCUSDT}
TIMEFRAME=${2:-5m}
STEPS=${3:-100000}
LOOKBACK=${4:-180}

echo "=================================================="
echo "  🤖 RL Agent Training"
echo "=================================================="
echo "Symbol:       $SYMBOL"
echo "Timeframe:    $TIMEFRAME"
echo "Steps:        $STEPS"
echo "Lookback:     $LOOKBACK days"
echo "=================================================="
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    exit 1
fi

# Check if container exists
if ! docker-compose ps | grep -q "trading-bot"; then
    echo "⚠️  Starting trading-bot container..."
    docker-compose up -d
    sleep 3
fi

# Install RL dependencies if needed
echo "📦 Ensuring RL dependencies are installed..."
docker-compose exec -T trading-bot pip install -q stable-baselines3 gym 'shimmy[gym-v21]>=1.2.1'

echo ""
echo "🚀 Starting RL training..."
echo ""

# Run training
docker-compose exec -T trading-bot python -c "
import logging
logging.basicConfig(level=logging.INFO)

from src.utils.rl_agent import train_rl_agent_for_symbol

print('Training $SYMBOL $TIMEFRAME with $STEPS steps...')
agent, stats = train_rl_agent_for_symbol(
    symbol='$SYMBOL',
    timeframe='$TIMEFRAME',
    lookback_days=$LOOKBACK,
    total_timesteps=$STEPS
)

print('')
print('=' * 60)
print('✅ Training Complete!')
print('=' * 60)
print(f\"Avg Return:    {stats['avg_return_pct']:.2f}%\")
print(f\"Sharpe Ratio:  {stats['avg_sharpe_ratio']:.2f}\")
print(f\"Win Rate:      {stats['avg_win_rate']*100:.1f}%\")
print(f\"Avg Trades:    {stats['avg_trades_per_episode']:.1f}\")
print(f\"Max Drawdown:  {stats['avg_max_drawdown']:.2f}%\")
print('=' * 60)
print('')
print('Model saved to: models/rl_agents/${SYMBOL}_${TIMEFRAME}_rl_agent.zip')
"

echo ""
echo "✨ Done! Check the web UI at http://localhost:5000/rl to view your trained models."
