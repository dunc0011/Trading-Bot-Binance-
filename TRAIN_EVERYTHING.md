# 🚀 Train EVERY Pair - Quick Start

Your bot now automatically discovers and trains ML models for **EVERY tradable USDT pair** on Binance!

## Quick Setup

1. **Edit `.env`:**
   ```bash
   SYMBOLS=ALL
   ```

2. **Start the bot:**
   ```bash
   docker-compose up -d
   ```

3. **Watch it work:**
   ```bash
   docker-compose logs -f | grep ContinuousTrainer
   ```

That's it! The bot will:
- Discover all USDT pairs with >$1M volume (~80-150+ pairs)
- Train advanced ML models for each (1-3 hours initial training)
- Start trading with the best models
- Retrain everything every 24 hours automatically

## What Gets Trained

The system auto-discovers and filters:

✅ All USDT pairs  
✅ With ≥$1M daily volume  
✅ Excluding stablecoins (USDC, BUSD, etc.)  
✅ Excluding leveraged tokens (UP, DOWN, BULL, BEAR)  
✅ Sorted by volume (trains highest volume first)  

**Result**: ~80-150+ liquid, tradable pairs with fresh ML models!

## Configuration Options

### Train Fewer Pairs (Higher Volume Only)
```bash
MIN_VOLUME_USDT=5000000  # Only major coins (higher volume)
```

### Train More Pairs (Include Smaller Altcoins)
```bash
MIN_VOLUME_USDT=500000  # More altcoins (lower volume threshold)
```

### Train Specific Pairs Only
```bash
SYMBOLS=BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT
```

### Adjust Retraining Frequency
```bash
RETRAIN_INTERVAL_HOURS=12  # Retrain twice per day
RETRAIN_INTERVAL_HOURS=48  # Retrain every 2 days
```

## Expected Timeline

With `SYMBOLS=ALL`:

| Phase | Duration | What Happens |
|-------|----------|--------------|
| Discovery | 5-10 sec | Queries Binance, filters pairs |
| Initial Training | 1-3 hours | Trains all 80-150+ pairs sequentially |
| Trading Starts | Immediate | Bot trades with trained models |
| Retraining | Every 24h | Background retraining of stale models |

**Training Speed**: ~30-120 seconds per pair (depends on data/optimization)

## Monitoring

### Check How Many Pairs Were Discovered
```bash
docker-compose logs trading-bot | grep "Discovered"
```

Example output:
```
Discovered 127 USDT pairs with >$1M volume
Top 10: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, ...
```

### Watch Training Progress
```bash
docker-compose logs -f | grep ContinuousTrainer
```

Example output:
```
[1/127] Training BTCUSDT...
✓ BTCUSDT trained in 95.2s - F1: 0.687, Acc: 0.723
[2/127] Training ETHUSDT...
✓ ETHUSDT trained in 102.8s - F1: 0.701, Acc: 0.738
...
```

### Check Trainer Status via API
```bash
curl http://localhost:5000/api/continuous-trainer/status
```

### View All Trained Models
```bash
curl http://localhost:5000/api/models
```

## Resource Requirements

For training 100+ pairs:

**Minimum:**
- 2 CPU cores
- 4GB RAM
- 10GB disk space

**Recommended:**
- 4+ CPU cores
- 8GB RAM
- 20GB disk space

Update `docker-compose.yml` if needed:
```yaml
services:
  trading-bot:
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 8G
```

## Trading Strategy

After training, the bot:

1. **Ranks models by F1 score** (quality metric)
2. **Selects top performers** (typically F1 > 0.60)
3. **Trades multiple pairs simultaneously** (max 3 positions)
4. **Uses dynamic position sizing** (based on ML confidence)
5. **Manages portfolio-level risk** (max $250 total exposure)

## Performance Expectations

With 100+ trained pairs:

- **Model quality**: F1 scores typically 0.60-0.75 (60-75% accuracy)
- **Trading opportunities**: More signals across diverse pairs
- **Diversification**: Spreads risk across many assets
- **Adaptation**: Models continuously retrain on latest data

## Tips for Success

1. **Let it run overnight**: Initial training of 100+ pairs takes time
2. **Check model quality**: After training, review F1 scores in web UI
3. **Start in dry-run mode**: Test before live trading
4. **Monitor first cycle**: Watch logs to ensure training completes
5. **Adjust volume filter**: Start with $1M, adjust based on results

## Troubleshooting

### "Discovered 0 pairs"
- Check API credentials are correct
- Ensure TRADING_MODE is set correctly (testnet vs live)
- Verify Binance API is accessible

### Training is too slow
- Reduce pairs with higher MIN_VOLUME_USDT
- Increase Docker CPU allocation
- Consider training in batches manually

### Out of memory errors
- Increase Docker memory limit
- Reduce MIN_VOLUME_USDT to train fewer pairs
- Training runs sequentially to minimize memory usage

### API rate limits
- Training is already throttled to avoid limits
- If limits hit, wait 1-2 minutes and restart
- Consider upgrading Binance API tier for higher limits

## Summary

**One setting. Everything automated.**

```bash
SYMBOLS=ALL
```

Your bot will:
- 🔍 Discover every liquid USDT pair
- 🤖 Train advanced ML models for all
- 📈 Trade the best opportunities across all markets
- 🔄 Continuously retrain to stay fresh
- 📊 Manage risk across the entire portfolio

**Training against everything, all the time.** 🚀

---

**Quick Links:**
- Full docs: `CONTINUOUS_TRAINING.md`
- Configuration: `.env`
- Web UI: `http://localhost:5000`
- Logs: `docker-compose logs -f`
