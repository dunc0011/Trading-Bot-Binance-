# Continuous Training System

Your bot now automatically trains ML models for all configured pairs **continuously in the background**.

## How It Works

When the multi-pair bot starts, it automatically:

1. **Discovers all configured pairs** from `SYMBOLS` in `.env`
2. **Trains initial models** for all pairs (one-time on startup)
3. **Starts continuous retraining** on a schedule (default: every 24 hours)
4. **Keeps models fresh** as market conditions change

The continuous trainer runs in a background thread and doesn't interfere with trading.

## Configuration

Edit `.env` to configure:

```bash
# TRAIN EVERY PAIR! Set to ALL for auto-discovery
SYMBOLS=ALL

# Or specify specific pairs (comma-separated)
# SYMBOLS=BTCUSDT,ETHUSDT,BNBUSDT

# Minimum daily volume for auto-discovery (USDT)
MIN_VOLUME_USDT=1000000  # $1M minimum

# Enable/disable continuous training
CONTINUOUS_TRAINING_ENABLED=true

# Hours between retraining cycles
RETRAIN_INTERVAL_HOURS=24
```

### Auto-Discovery Mode

When `SYMBOLS=ALL`, the system:
- Queries Binance API for all trading pairs
- Filters to USDT pairs only
- Excludes stablecoins (USDC, BUSD, etc.)
- Excludes leveraged tokens (UP, DOWN, BULL, BEAR)
- Only includes pairs with ≥$1M daily volume
- Sorts by volume (trains highest volume first)

**Example**: This typically discovers **80-150+ pairs** depending on market conditions!

## Training Schedule

- **Initial Training**: All pairs trained when bot starts (sequential)
- **Continuous Retraining**: Every 24h (or configured interval)
- **Smart Scheduling**: Only retrains models that are 24h+ old
- **No Interruption**: Training happens in background, bot keeps trading

## What Gets Trained

The system trains **advanced ML models** with:
- 65+ technical indicators and features
- XGBoost/LightGBM ensemble models
- Walk-forward validation
- Hyperparameter optimization (when enabled)
- ATR-based dynamic stop-losses

## Monitoring

### Via Web UI

Check training status at:
- **Dashboard**: Live bot status shows continuous trainer
- **Training Tab**: View model metrics and training history
- **API Endpoint**: `/api/continuous-trainer/status`

### Via Logs

```bash
# View continuous trainer logs
docker-compose logs -f | grep ContinuousTrainer

# Or check log file
tail -f logs/continuous_trainer.log
```

### Status Information

The trainer provides:
- **Running status**: Is the trainer active?
- **Pairs being trained**: List of all symbols
- **Last training times**: When each model was last retrained
- **Next training times**: When each model will retrain next
- **Training results**: F1 scores, accuracy, errors

## Usage Examples

### Start Bot with Continuous Training (Default)

```bash
docker-compose up -d
```

The continuous trainer starts automatically with the multi-pair bot.

### View Training Status

```bash
# Check if trainer is running
curl http://localhost:5000/api/continuous-trainer/status

# View logs
docker-compose logs -f trading-bot | grep ContinuousTrainer
```

### Adjust Training Interval

Edit `.env`:
```bash
RETRAIN_INTERVAL_HOURS=12  # Retrain every 12 hours
```

Then restart:
```bash
docker-compose restart
```

### Train Every Pair (Auto-Discovery)

Edit `.env`:
```bash
SYMBOLS=ALL  # Auto-discover all USDT pairs with >$1M volume
```

Restart bot - all pairs will be discovered and trained automatically.

### Train Specific Pairs

Edit `.env`:
```bash
SYMBOLS=BTCUSDT,ETHUSDT,BNBUSDT,LINKUSDT,AVAXUSDT  # Specific pairs only
```

Restart bot - only specified pairs will be trained.

### Adjust Volume Filter

For more/fewer pairs, adjust the minimum volume:

```bash
MIN_VOLUME_USDT=5000000  # Higher = fewer pairs (only major coins)
MIN_VOLUME_USDT=500000   # Lower = more pairs (includes altcoins)
```

### Disable Continuous Training

Edit `.env`:
```bash
CONTINUOUS_TRAINING_ENABLED=false
```

Or modify the bot code to skip starting the trainer.

## Training Process

For each pair, the trainer:

1. **Fetches market data** (90 days by default)
2. **Generates 65+ features** (EMAs, RSI, ATR, fractals, Hurst, etc.)
3. **Trains ensemble models** (XGBoost + LightGBM + voting classifier)
4. **Validates with walk-forward** (prevents overfitting)
5. **Saves model + metadata** (models/advanced_ml/)
6. **Emits progress events** (WebSocket updates for UI)

Average training time: **30-120 seconds per pair** (depends on optimization)

## Architecture

```
MultiPairBot
    ├── ContinuousTrainer (background thread)
    │   ├── Initial training cycle (all pairs)
    │   ├── Wait for retrain interval
    │   └── Continuous retraining (only stale models)
    │
    ├── Strategy instances (per pair)
    ├── Risk managers (per pair)
    └── Order managers (per pair)
```

## Best Practices

1. **Start with ALL pairs**: Let the system discover and train everything
2. **Use volume filter wisely**: $1M minimum is good for active pairs
3. **24h retraining interval**: Daily retraining balances freshness vs. compute
4. **Monitor model quality**: Check F1 scores - models >60% F1 are good
5. **Watch resource usage**: Training is CPU-intensive (expect 1-3 hours initial training for 100+ pairs)
6. **Prioritize by volume**: High-volume pairs train first and are most reliable
7. **Test in dry-run first**: Validate before live trading
8. **Increase Docker resources**: 4+ CPU cores and 8GB RAM recommended for many pairs

## Logs Example

```
2025-01-25 10:00:00 - ContinuousTrainer - INFO - Starting continuous training service
2025-01-25 10:00:00 - ContinuousTrainer - INFO - Running initial training cycle...
2025-01-25 10:00:00 - ContinuousTrainer - INFO - [1/10] Training BTCUSDT...
2025-01-25 10:02:15 - ContinuousTrainer - INFO - ✓ BTCUSDT trained in 135.2s - F1: 0.687, Acc: 0.723
2025-01-25 10:02:15 - ContinuousTrainer - INFO - [2/10] Training ETHUSDT...
...
2025-01-25 10:25:30 - ContinuousTrainer - INFO - Cycle complete in 1530.5s - 10/10 successful
2025-01-25 10:25:30 - ContinuousTrainer - INFO - Next cycle in 24.0h
```

## Troubleshooting

### Training Fails for Some Pairs

**Cause**: Insufficient data, API rate limits, or data quality issues

**Solution**: 
- Check logs for specific error
- Increase `lookback_days` if data is sparse
- Ensure API key has market data permissions

### Training Takes Too Long

**Cause**: Too many pairs or hyperparameter optimization enabled

**Solution**:
- Reduce number of pairs in `SYMBOLS`
- Disable optimization (default is already optimized)
- Increase training interval to 48h+

### Bot Starts Without Training

**Cause**: Models already exist and are fresh (<24h old)

**Solution**: This is normal! Trainer only retrains stale models.

### Memory Issues

**Cause**: Training all pairs simultaneously consumes RAM

**Solution**: Trainer already runs sequentially. Increase Docker memory limit if needed.

## Performance

Expected performance with continuous retraining:

- **Model freshness**: Always trained on latest 90 days of data
- **Adaptation**: Responds to changing market conditions
- **Consistency**: Automatic retraining removes manual overhead
- **Reliability**: Handles failures gracefully, retries on next cycle

## Advanced Usage

### Standalone Continuous Trainer

Run trainer separately from bot:

```bash
python -m src.utils.continuous_trainer --interval-hours 12
```

### Programmatic Access

```python
from src.utils.continuous_trainer import ContinuousTrainer
from config.config import Config

config = Config()
trainer = ContinuousTrainer(config, retrain_interval_hours=24)
trainer.start()

# Get status
status = trainer.get_status()
print(f"Training {status['total_symbols']} pairs")

# Stop when done
trainer.stop()
```

## Summary

Your bot now **trains against everything, all the time**:

✅ Automatically discovers all pairs in config  
✅ Trains initial models on startup  
✅ Continuously retrains every 24h  
✅ Keeps models fresh with latest data  
✅ Runs in background without interrupting trading  
✅ Provides status monitoring via API and logs  

**Just start the bot and it handles the rest!** 🚀
