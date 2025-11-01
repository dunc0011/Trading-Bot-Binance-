# RL Training Quick Start 🚀

## 1. Install Dependencies
```bash
docker-compose exec trading-bot pip install -r requirements.txt
```

## 2. Start Web UI
```bash
docker-compose up -d
```

Open: **http://localhost:5000/rl**

## 3. Train Your First Agent

### Via Web UI (Easiest) ✨
1. Navigate to http://localhost:5000/rl
2. Fill in the form:
   - Symbol: `BTCUSDT`
   - Timeframe: `5m`
   - Algorithm: `PPO`
   - Lookback: `180` days
   - Steps: `100000`
3. Click **"Start Training"**
4. Watch real-time progress
5. View results when complete

### Via CLI (Quick)
```bash
# Quick training with defaults (BTCUSDT, 5m, 100k steps)
./train_rl.sh

# Custom symbol and steps
./train_rl.sh ETHUSDT 15m 200000

# Full control
./train_rl.sh SOLUSDT 5m 150000 180
```

### Via Docker Exec (Advanced)
```bash
docker-compose exec trading-bot python -m src.utils.rl_agent
```

## 4. Evaluate Models
In the web UI, click **"Evaluate"** on any trained model to test it on recent data.

## 5. View Trained Models
```bash
ls -lh models/rl_agents/
```

---

## Key Features ✨

✅ **Web UI Training** - Train from your browser with real-time progress  
✅ **SocketIO Updates** - Live training status via WebSockets  
✅ **Model Management** - List, evaluate, and compare trained agents  
✅ **Multiple Algorithms** - PPO and A2C support  
✅ **Automatic Evaluation** - Performance metrics computed after training  
✅ **Metadata Tracking** - Training config and results saved with each model  

---

## What You Get 🎯

After training, you'll have:
- **Trained RL agent** saved to `models/rl_agents/`
- **Performance metrics** (return %, Sharpe ratio, win rate)
- **Metadata file** with training details
- **Web UI access** to view and evaluate models

---

## Training Time ⏱️

| Steps | Approximate Time |
|-------|------------------|
| 50k   | ~5-10 minutes    |
| 100k  | ~10-20 minutes   |
| 200k  | ~20-40 minutes   |
| 500k  | ~1-2 hours       |

*Times vary based on data size and hardware*

---

## Performance Targets 🎯

**Good RL Agent:**
- Avg Return: > 5%
- Sharpe Ratio: > 1.5
- Win Rate: > 50%
- Max Drawdown: < 10%

**Excellent RL Agent:**
- Avg Return: > 10%
- Sharpe Ratio: > 2.0
- Win Rate: > 60%
- Max Drawdown: < 5%

---

## Next Steps 🔜

1. ✅ Train your first agent
2. ✅ Evaluate performance
3. ✅ Try different symbols/timeframes
4. 🔜 Deploy in paper trading
5. 🔜 Integrate with live bot

---

**Full Documentation:** See `RL_TRAINING_GUIDE.md`

**Need Help?** Check the troubleshooting section in the guide.
