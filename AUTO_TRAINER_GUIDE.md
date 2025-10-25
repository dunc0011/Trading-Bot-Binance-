# 🤖 Intelligent Auto-Trainer Guide

## What It Does

The Auto-Trainer is an intelligent system that **automatically discovers and trains ML models** for the best trading pairs on Binance. You don't have to pick pairs manually anymore!

### Features

✅ **Auto-Discovery**: Finds top 20 USDT pairs by 24h trading volume  
✅ **Smart Selection**: Filters out stablecoins and low-volume pairs  
✅ **Auto-Training**: Trains models for all discovered pairs  
✅ **Auto-Retraining**: Updates models weekly to keep them fresh  
✅ **Background Operation**: Runs continuously, checking daily  
✅ **Progress Tracking**: Saves training history in JSON  

---

## How It Works

### 1. Discovery Phase
```
Every 24 hours:
├── Fetch all USDT pairs from Binance
├── Filter by volume (min 10M USDT/day)
├── Skip stablecoins (USDC, BUSD, etc.)
├── Sort by volume
└── Select top 20 pairs
```

**Example output:**
```
1. BTCUSDT: $45,234,567,890 volume, +2.34% change
2. ETHUSDT: $23,456,789,012 volume, -1.23% change
3. SOLUSDT: $8,912,345,678 volume, +5.67% change
...
```

### 2. Training Phase
```
For each discovered pair:
├── Check if model exists
├── Check if model is > 7 days old
├── If needed: Train new model
│   ├── Download 90 days of data
│   ├── Calculate indicators (EMA, RSI, ATR)
│   ├── Train ML model
│   └── Save model to models/ml_ema/
└── Log results (accuracy, F1 score)
```

### 3. Maintenance Phase
```
Weekly retraining:
├── Markets change over time
├── Models need fresh data
└── Old models get retrained automatically
```

---

## Quick Start

### Option 1: Run in Docker (Recommended)

```bash
# Make sure your bot is running
docker-compose up -d

# Start the auto-trainer
./run_auto_trainer.sh
```

The trainer will run continuously and log to `logs/auto_trainer.log`.

### Option 2: Run Standalone

```bash
# Inside Docker container
docker-compose exec trading-bot python -m src.utils.auto_trainer

# Or locally (if you have dependencies installed)
python -m src.utils.auto_trainer
```

### Option 3: One-Time Training Cycle

```python
# In Python
from src.utils.auto_trainer import AutoTrainer
from config.config import Config
import asyncio

async def run_once():
    config = Config()
    trainer = AutoTrainer(config)
    await trainer.auto_train_cycle()

asyncio.run(run_once())
```

---

## Configuration

Edit `src/utils/auto_trainer.py` to customize:

```python
class AutoTrainer:
    def __init__(self, config):
        # Customize these settings
        self.min_volume_usdt = 10_000_000    # Min 24h volume (10M USDT)
        self.max_pairs = 20                  # Train top N pairs
        self.retrain_interval_days = 7       # Retrain weekly
        self.lookback_days = 90              # Training data history
        self.timeframe = '1h'                # Candle interval
```

### Settings Explained

| Setting | Default | Description |
|---------|---------|-------------|
| `min_volume_usdt` | 10M | Minimum 24h volume to consider pair |
| `max_pairs` | 20 | Maximum number of pairs to train |
| `retrain_interval_days` | 7 | Days before retraining model |
| `lookback_days` | 90 | Days of historical data for training |
| `timeframe` | 1h | Trading timeframe (1m, 5m, 1h, etc.) |

---

## Monitoring

### Check Training History

```bash
# View trained models
cat models/training_history.json
```

**Example output:**
```json
{
  "BTCUSDT": {
    "last_trained": "2025-10-25T10:00:00",
    "timeframe": "1h",
    "lookback_days": 90,
    "accuracy": 0.67,
    "f1_score": 0.64
  },
  "ETHUSDT": {
    "last_trained": "2025-10-25T10:15:00",
    "timeframe": "1h",
    "lookback_days": 90,
    "accuracy": 0.71,
    "f1_score": 0.68
  }
}
```

### View Logs

```bash
# Real-time logs
tail -f logs/auto_trainer.log

# Search for specific pair
grep "BTCUSDT" logs/auto_trainer.log

# Check training results
grep "trained successfully" logs/auto_trainer.log
```

### Check Trained Models

```bash
# List all trained models
ls -lh models/ml_ema/

# Example output:
# BTCUSDT_1h_ml_ema.joblib
# ETHUSDT_1h_ml_ema.joblib
# SOLUSDT_1h_ml_ema.joblib
```

---

## Training Timeline

### Initial Run
- Discovers 20 pairs
- Trains all 20 (if no existing models)
- Takes ~2-4 hours total (5-10 min per pair)

### Daily Checks
- Runs every 24 hours
- Checks for new top pairs
- Retrains models older than 7 days
- Usually only 0-3 pairs need retraining

### Weekly Retraining
- Each model is retrained weekly
- Keeps models fresh with latest market data
- ~3 pairs retrained per day on average

---

## Integration with Trading Bot

Once models are trained, use them with your trading bot:

### 1. Update Your .env File

```bash
# Use ML strategy
STRATEGY=ml_ema

# Pick a symbol that has a trained model
SYMBOL=BTCUSDT
TIMEFRAME=1h

# Start in dry-run mode
DRY_RUN=true
```

### 2. Start Bot

```bash
docker-compose up -d
docker-compose logs -f
```

The bot will automatically load the trained model for BTCUSDT.

### 3. Multi-Symbol Trading

To trade multiple pairs simultaneously:

1. **Train models** (auto-trainer does this)
2. **Run multiple bot instances** (one per symbol)
3. **Use docker-compose** to manage multiple containers

---

## Advanced Usage

### Custom Pair Selection

Want to train specific pairs instead of top volume pairs?

```python
# Edit auto_trainer.py
def get_custom_pairs(self):
    return [
        {'symbol': 'BTCUSDT', 'volume': 999999, 'price_change': 0},
        {'symbol': 'ETHUSDT', 'volume': 999999, 'price_change': 0},
        {'symbol': 'SOLUSDT', 'volume': 999999, 'price_change': 0},
        # Add your pairs here
    ]

# Then in auto_train_cycle(), replace:
# top_pairs = self.get_top_usdt_pairs()
# With:
# top_pairs = self.get_custom_pairs()
```

### Different Timeframes

Train models for multiple timeframes:

```python
# In auto_trainer.py
self.timeframes = ['15m', '1h', '4h']

# Then loop through timeframes:
for timeframe in self.timeframes:
    self.timeframe = timeframe
    await self.train_pair(symbol)
```

### Filter by Price Change

Only train pairs with high volatility:

```python
# In get_top_usdt_pairs()
if abs(price_change) >= 5.0:  # At least 5% change
    usdt_pairs.append({...})
```

---

## Troubleshooting

### Auto-Trainer Won't Start

**Check logs:**
```bash
tail -n 50 logs/auto_trainer.log
```

**Common issues:**
- API keys not set in `.env`
- Binance API rate limits (wait 1 minute)
- Docker container not running

### Training Fails for Specific Pair

**Symptoms:** "✗ XXXUSDT training failed"

**Solutions:**
- Pair might be new (not enough history)
- Symbol might be delisted
- API rate limit reached (wait)
- Check logs for specific error

### Models Not Loading in Bot

**Check:**
1. Model file exists: `ls models/ml_ema/BTCUSDT_1h_ml_ema.joblib`
2. Symbol matches: `.env` SYMBOL must match model filename
3. Timeframe matches: `.env` TIMEFRAME must match model filename

---

## Performance Tips

### Speed Up Training

1. **Reduce lookback_days**: 60 days instead of 90
2. **Use faster timeframe**: 1h trains faster than 1m
3. **Reduce max_pairs**: Train fewer pairs (e.g., top 10)

### Optimize Model Quality

1. **Increase lookback_days**: 180 days for more data
2. **Retrain more often**: Every 3-4 days instead of 7
3. **Filter by volatility**: Only train pairs with good movement

### Reduce API Calls

```python
# Increase sleep between trainings
await asyncio.sleep(30)  # Wait 30 seconds instead of 10

# Reduce check frequency
await asyncio.sleep(48 * 60 * 60)  # Check every 48 hours
```

---

## FAQ

**Q: Does this cost money?**  
A: Training uses free historical data from Binance. It's free!

**Q: How long does initial training take?**  
A: ~2-4 hours for 20 pairs (5-10 minutes per pair).

**Q: Can I stop and restart?**  
A: Yes! Training history is saved. It will skip already-trained pairs.

**Q: Will it train pairs I don't want?**  
A: Yes, it auto-discovers. To train specific pairs only, modify `get_custom_pairs()`.

**Q: Do I need to run this 24/7?**  
A: No! You can run it once to train all models, then stop it. Rerun weekly for updates.

**Q: Can I train while the bot is trading?**  
A: Yes, they're independent. Training won't affect active trading.

---

## Summary

The Auto-Trainer is your **set-it-and-forget-it** solution for ML model management:

1. **Run it once**: `./run_auto_trainer.sh`
2. **It discovers** top pairs automatically
3. **It trains** models for all discovered pairs
4. **It maintains** models by retraining weekly
5. **You trade** with fresh, optimized models

**No manual work required!** 🚀
