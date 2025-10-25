# 🚀 Quick Start - Auto-Training Trading Bot

## What You Got

✅ **Modern Dashboard** - Professional UI with 5 pages (Overview, Scanner, Positions, ML Training, Logs)  
✅ **Intelligent Auto-Trainer** - Automatically discovers and trains models for top 20 trading pairs  
✅ **Continuous Learning** - Retrains models weekly to adapt to market changes  
✅ **Set-and-Forget** - No manual pair selection needed!  

---

## 3-Step Setup

### 1. Configure Your API Keys

Edit `.env` file:
```bash
BINANCE_API_KEY=your_key_here
BINANCE_API_SECRET=your_secret_here

# Safe testing mode
DRY_RUN=true
TRADING_MODE=testnet
```

### 2. Start Auto-Training

```bash
# Start Docker containers
docker-compose up -d

# Run auto-trainer (discovers & trains top 20 pairs)
./run_auto_trainer.sh
```

This will:
- Scan Binance for top USDT pairs by volume
- Train ML models for Bitcoin, Ethereum, Solana, and 17 more
- Take ~2-4 hours for initial training
- Save models to `models/ml_ema/`

### 3. Start Trading

Once training completes (check logs):

```bash
# Edit .env to use a trained model
SYMBOL=BTCUSDT
TIMEFRAME=1h
STRATEGY=ml_ema
DRY_RUN=true

# Restart bot
docker-compose restart
```

---

## Access the Dashboard

```bash
# Start web UI
./run_web_ui.sh

# Open browser
open http://localhost:5000
```

**Dashboard Pages:**
- **Overview** - Portfolio stats, quick actions
- **Market Scanner** - Scan all pairs for opportunities
- **Positions** - View active trades
- **ML Training** - Train/retrain models manually
- **Logs** - Real-time bot logs

---

## What Happens Next?

### Auto-Trainer Schedule

```
First Run (Now):
├── Discovers top 20 pairs
├── Trains all 20 models
└── Takes ~2-4 hours

Daily (Auto):
├── Checks for new top pairs
├── Retrains old models (>7 days)
└── Usually 0-3 models updated

Weekly (Auto):
├── Each model gets fresh data
├── Adapts to market changes
└── ~3 models per day
```

### Bot Trading Cycle

```
Every 60 seconds:
├── Fetch current price
├── Load ML model prediction
├── Check risk management
└── Execute trade (if signal)
```

---

## Monitoring

### Check Training Progress

```bash
# View logs
tail -f logs/auto_trainer.log

# Check trained models
ls models/ml_ema/

# View training history
cat models/training_history.json
```

### Check Bot Status

```bash
# Bot logs
docker-compose logs -f

# Or use the dashboard
open http://localhost:5000
```

---

## Key Files

| File | Purpose |
|------|---------|
| `.env` | Bot configuration (API keys, symbols, etc.) |
| `AUTO_TRAINER_GUIDE.md` | Full auto-trainer documentation |
| `DASHBOARD_GUIDE.md` | Dashboard features and usage |
| `WARP.md` | Complete technical documentation |
| `models/training_history.json` | Tracks all trained models |
| `logs/auto_trainer.log` | Auto-trainer logs |
| `logs/trading_bot.log` | Bot trading logs |

---

## Common Commands

```bash
# Start everything
docker-compose up -d
./run_auto_trainer.sh
./run_web_ui.sh

# Stop everything
docker-compose down

# View logs
docker-compose logs -f
tail -f logs/auto_trainer.log

# Train specific pair manually
docker-compose exec trading-bot python -m src.utils.train_ml_model \
  --symbol BTCUSDT --interval 1h --lookback-days 90

# Check trained models
ls -lh models/ml_ema/
```

---

## Customization

### Change Auto-Trainer Settings

Edit `src/utils/auto_trainer.py`:

```python
# Train top 10 instead of 20
self.max_pairs = 10

# Only high-volume pairs (50M+ USDT)
self.min_volume_usdt = 50_000_000

# Retrain every 3 days instead of 7
self.retrain_interval_days = 3

# Use 4-hour timeframe
self.timeframe = '4h'
```

### Pick Specific Pairs

Instead of auto-discovery, train specific pairs:

```bash
# Train your favorites
docker-compose exec trading-bot python -m src.utils.train_ml_model --symbol BTCUSDT --interval 1h
docker-compose exec trading-bot python -m src.utils.train_ml_model --symbol ETHUSDT --interval 1h
docker-compose exec trading-bot python -m src.utils.train_ml_model --symbol SOLUSDT --interval 1h
```

---

## Safety Tips

⚠️ **Start in Dry-Run Mode**
- Set `DRY_RUN=true` in `.env`
- Bot simulates trades without real money
- Check logs to verify strategy works

⚠️ **Use Testnet First**
- Set `TRADING_MODE=testnet` in `.env`
- Practice with fake Binance funds
- Get testnet funds: https://testnet.binance.vision/

⚠️ **Go Live Carefully**
- Only after successful dry-run and testnet testing
- Start with small `MAX_POSITION_SIZE` (e.g., $10-20)
- Monitor closely for first 24 hours
- Gradually increase position size

---

## Next Steps

1. ✅ **Let auto-trainer run** (~2-4 hours for 20 pairs)
2. ✅ **Monitor dashboard** to see progress
3. ✅ **Review trained models** (check accuracy in training_history.json)
4. ✅ **Start bot with best model** (highest accuracy)
5. ✅ **Test in dry-run mode first**
6. ✅ **Graduate to testnet**
7. ✅ **Go live with small positions**

---

## Need Help?

- **Auto-Trainer Questions**: Read `AUTO_TRAINER_GUIDE.md`
- **Dashboard Questions**: Read `DASHBOARD_GUIDE.md`
- **Technical Details**: Read `WARP.md`
- **Bot Not Working**: Check `logs/trading_bot.log`
- **Training Failing**: Check `logs/auto_trainer.log`

---

## What Makes This Special?

🎯 **Fully Automated** - No manual pair selection  
🧠 **Intelligent** - Discovers best pairs by volume  
📊 **Adaptive** - Retrains weekly to stay current  
🎨 **Beautiful UI** - Professional dashboard  
🔒 **Safe** - Dry-run and testnet modes  
🆓 **Free** - Uses free Binance data  

**Your bot now trains itself for the top 20 trading pairs automatically!** 🚀
