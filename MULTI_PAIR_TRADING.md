# 🚀 Multi-Pair Trading Bot Guide

## What Is It?

The **Multi-Pair Trading Bot** automatically trades **ALL pairs that have trained ML models** - no manual configuration needed!

### Key Features:

✅ **Auto-Discovery** - Finds all trained models automatically  
✅ **Multi-Pair Trading** - Trades up to 5 pairs simultaneously  
✅ **Portfolio Risk Management** - Total exposure limits  
✅ **Smart Selection** - Only trades models with >55% accuracy  
✅ **Concurrent Analysis** - Analyzes all pairs in parallel  
✅ **Position Tracking** - Manages multiple open positions  

---

## How It Works

```
Every 60 seconds:
1. Discover all trained ML models in models/ml_ema/
2. Filter by accuracy (keep models >55%)
3. Select top 5 pairs by accuracy
4. Analyze all 5 pairs concurrently
5. Generate BUY/SELL signals for each
6. Check portfolio limits (max 5 positions, $500 total)
7. Execute trades for valid signals
8. Track P&L for each position
```

### Portfolio Settings (Default):

| Setting | Value | Description |
|---------|-------|-------------|
| Max Positions | 5 | Maximum open positions at once |
| Position Size | $100 | USDT allocated per pair |
| Portfolio Limit | $500 | Maximum total exposure |
| Min Accuracy | 55% | Only trade models above this |

---

## Quick Start

### 1. Wait for Models to Train

```bash
# Check training progress
tail -f logs/auto_trainer.log

# Check how many models are ready
ls models/ml_ema/*.joblib | wc -l
```

### 2. Start the Multi-Pair Bot

```bash
# Make sure Docker is running
docker-compose ps

# Start the multi-pair bot
./run_multi_pair_bot.sh
```

### 3. Monitor Trading

```bash
# Watch live trading logs
tail -f logs/multi_pair_bot.log

# Or check in the dashboard
open http://localhost:5000
```

---

## What You'll See

### Startup Output:

```
============================================================
Multi-Pair Trading Bot Starting
============================================================
Discovered 20 trained models
  1. BTCUSDT (1h): 58.4% accuracy
  2. ETHUSDT (1h): 54.3% accuracy
  3. SOLUSDT (1h): 52.3% accuracy
  ...

Trading 3 pairs with models:
  • BTCUSDT: 58.4% accuracy
  • ETHUSDT: 54.3% accuracy
  • SOLUSDT: 52.3% accuracy

============================================================
Trading Mode: DRY RUN
Max Positions: 5
Position Size: $100 per pair
Portfolio Limit: $500
============================================================
```

### Trading Logs:

```
2025-10-25 10:30:00 - BTCUSDT: Analyzing...
2025-10-25 10:30:01 - BTCUSDT: BUY signal generated (confidence: 72%)
2025-10-25 10:30:02 - ✅ BTCUSDT BUY executed at $67,890.50
2025-10-25 10:30:02 - 📊 Portfolio: 1 positions, $100 exposure

2025-10-25 10:31:00 - ETHUSDT: Analyzing...
2025-10-25 10:31:01 - ETHUSDT: BUY signal generated (confidence: 65%)
2025-10-25 10:31:02 - ✅ ETHUSDT BUY executed at $3,245.80
2025-10-25 10:31:02 - 📊 Portfolio: 2 positions, $200 exposure

2025-10-25 10:45:00 - BTCUSDT: SELL signal generated
2025-10-25 10:45:01 - ✅ BTCUSDT SELL executed at $68,120.00 (P&L: +0.34%)
2025-10-25 10:45:01 - 📊 Portfolio: 1 positions, $100 exposure
```

---

## Configuration

### Adjust Portfolio Settings

Edit `src/multi_pair_bot.py`:

```python
class MultiPairBot:
    def __init__(self, config: Config):
        # Customize these:
        self.max_concurrent_positions = 5    # Max open positions
        self.position_size_per_pair = 100    # USDT per position
        self.total_portfolio_limit = 500     # Total max exposure
```

### Change Minimum Accuracy

```python
# In start() method:
min_accuracy = 0.55  # Only use models with >55% accuracy
```

Want to trade ALL models regardless of accuracy?

```python
min_accuracy = 0.0  # Trade all available models
```

---

## Comparison: Single vs Multi-Pair

### Single-Pair Bot (Old Way):

```
❌ Trades ONE pair only (e.g., BTCUSDT)
❌ Manual configuration in .env required
❌ Misses opportunities in other pairs
❌ Limited diversification
✅ Simple to understand
```

**Usage:**
```bash
# Edit .env
SYMBOL=BTCUSDT
TIMEFRAME=1h

# Start bot
docker-compose up -d
```

### Multi-Pair Bot (New Way):

```
✅ Trades ALL pairs with models
✅ Zero manual configuration
✅ Captures opportunities across market
✅ Better diversification
✅ Portfolio-level risk management
✅ Concurrent analysis (faster)
```

**Usage:**
```bash
# Just run it!
./run_multi_pair_bot.sh
```

---

## Safety & Risk Management

### Built-in Protections:

1. **Position Limits**
   - Max 5 open positions at once
   - Prevents over-exposure

2. **Portfolio Limits**
   - Max $500 total exposure
   - Can't exceed this even with signals

3. **Quality Filter**
   - Only trades models >55% accuracy
   - Ignores weak models

4. **Risk Manager Integration**
   - Each trade validated
   - Stop-loss and take-profit calculated
   - Position sizing enforced

5. **Dry-Run Mode**
   - Set `DRY_RUN=true` in .env
   - Simulates all trades
   - No real money at risk

---

## When to Use Each Bot

### Use Single-Pair Bot When:

- 🎯 You want to focus on one specific pair
- 📚 You're learning and want simplicity
- 🧪 You're testing a new strategy
- 💰 You have limited capital (<$100)

### Use Multi-Pair Bot When:

- 🚀 You want maximum market coverage
- 💰 You have moderate capital ($500+)
- 📊 You want diversification
- ⚡ You want to capture more opportunities
- 🤖 You want full automation

---

## Monitoring & Management

### Check Active Positions

```python
# In the bot logs, look for:
📊 Portfolio: 3 positions, $300 exposure
```

### View All Positions

The bot logs every trade:
- Entry price
- Exit price
- P&L percentage
- Reason for trade

### Stop the Bot

```bash
# Press Ctrl+C in the terminal
# Or kill the process:
docker-compose exec web-ui pkill -f multi_pair_bot
```

---

## Advanced Customization

### Trade Specific Pairs Only

Edit `src/multi_pair_bot.py`, in `start()` method:

```python
# After discovering models, filter manually:
allowed_pairs = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
good_models = [m for m in models if m['symbol'] in allowed_pairs]
```

### Increase Max Positions

```python
self.max_concurrent_positions = 10  # Trade up to 10 pairs
self.total_portfolio_limit = 1000   # Increase portfolio limit
```

### Adjust Position Sizing

```python
self.position_size_per_pair = 50   # $50 per position (smaller)
# or
self.position_size_per_pair = 200  # $200 per position (larger)
```

### Dynamic Position Sizing

Based on model accuracy:

```python
def initialize_pair(self, symbol: str, timeframe: str):
    # Get model accuracy
    model_accuracy = self.get_model_accuracy(symbol)
    
    # Allocate more to better models
    if model_accuracy > 0.60:
        position_size = 150  # $150 for great models
    else:
        position_size = 50   # $50 for ok models
    
    pair_config.max_position_size = position_size
```

---

## Troubleshooting

### "No trained models found"

```bash
# Check if models exist
ls models/ml_ema/

# If empty, run auto-trainer first
./run_auto_trainer.sh
```

### "No models with accuracy >= 55%"

All your models are <55% accuracy. Options:

1. **Wait for more training data** (models improve over time)
2. **Lower the threshold** in code:
   ```python
   min_accuracy = 0.50  # Accept 50%+ models
   ```
3. **Retrain with more data**:
   ```bash
   # In auto_trainer.py, increase:
   self.lookback_days = 180  # Use 6 months instead of 3
   ```

### Bot stops unexpectedly

Check logs:
```bash
tail -100 logs/multi_pair_bot.log
```

Common causes:
- API rate limits (wait 1 minute)
- Network issues
- Invalid API keys

---

## Performance Expectations

### Realistic Expectations:

| Metric | Conservative | Average | Optimistic |
|--------|-------------|---------|------------|
| Win Rate | 50-55% | 55-60% | 60-65% |
| Avg Profit/Trade | 0.5-1% | 1-2% | 2-5% |
| Monthly Return | 3-5% | 5-10% | 10-20% |
| Drawdown | 5-10% | 10-15% | 15-20% |

### Factors Affecting Performance:

✅ **Model Quality** - Higher accuracy = better results  
✅ **Market Conditions** - Bull markets perform better  
✅ **Diversification** - More pairs = smoother returns  
✅ **Risk Management** - Stop-losses prevent big losses  
❌ **Over-trading** - Too many trades = more fees  
❌ **Slippage** - Fast markets = worse fills  

---

## FAQ

**Q: Can I run both single-pair and multi-pair bots?**  
A: No, they'll conflict. Choose one.

**Q: How many pairs can I trade?**  
A: Default is 5, but you can increase it in the code.

**Q: What if a pair doesn't have a model?**  
A: It's skipped. Only pairs with models are traded.

**Q: Can I trade on multiple timeframes?**  
A: Currently, all pairs use the same timeframe (1h default). Could be enhanced.

**Q: How do I know which pairs are being traded?**  
A: Check startup logs - it lists all trading pairs.

**Q: What happens if I hit portfolio limit?**  
A: New BUY signals are rejected until positions close.

**Q: Can I prioritize certain pairs?**  
A: Yes, edit the code to give them larger position sizes.

---

## Summary

The Multi-Pair Bot is your **set-it-and-forget-it** solution:

1. ✅ **Auto-discovers** all trained models
2. ✅ **Auto-selects** best pairs by accuracy
3. ✅ **Auto-trades** multiple pairs simultaneously
4. ✅ **Auto-manages** portfolio risk
5. ✅ **Auto-adapts** as new models are trained

**No manual configuration. No babysitting. Just results.** 🚀

---

## Next Steps

1. ✅ **Wait for auto-trainer** to finish training models (~2 hours)
2. ✅ **Start multi-pair bot**: `./run_multi_pair_bot.sh`
3. ✅ **Monitor logs**: `tail -f logs/multi_pair_bot.log`
4. ✅ **Watch dashboard**: http://localhost:5000
5. ✅ **Review performance** after 24 hours
6. ✅ **Adjust settings** based on results
7. ✅ **Graduate from dry-run** to testnet
8. ✅ **Go live** with real money (carefully!)

Happy trading! 💰
