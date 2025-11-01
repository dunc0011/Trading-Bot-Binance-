# RL Agent Training Guide

## Overview
Your trading bot now supports **Reinforcement Learning agents** trained via the web UI! RL agents learn trading strategies by interacting with a simulated market environment.

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
# Inside Docker (recommended)
docker-compose exec trading-bot pip install -r requirements.txt

# Or locally
pip install -r requirements.txt
```

### 2. Start the Web UI
```bash
# Start all services
docker-compose up -d

# Or run web app directly
python src/web_app.py
```

### 3. Access RL Training Page
Open your browser to:
```
http://localhost:5000/rl
```

---

## 🎯 Training Your First RL Agent

### Using the Web UI (Recommended)

1. **Navigate** to http://localhost:5000/rl
2. **Configure training:**
   - Symbol: `BTCUSDT` (or any USDT pair)
   - Timeframe: `5m` (5 minutes recommended for RL)
   - Algorithm: `PPO` (Proximal Policy Optimization - best for beginners)
   - Lookback Days: `180` (6 months of data)
   - Training Steps: `100000` (start with 100k, increase for better performance)

3. **Click "Start Training"**
   - Training runs in background
   - Progress updates in real-time via SocketIO
   - Takes 10-30 minutes depending on data size

4. **View Results**
   - Avg Return %
   - Sharpe Ratio
   - Win Rate
   - Avg Trades per Episode

5. **Evaluate Models**
   - Click "Evaluate" on any trained model
   - Tests on last 30 days of data
   - Shows performance metrics

### Using CLI (Advanced)

```bash
# Train via CLI
docker-compose exec trading-bot python -m src.utils.rl_agent

# Or with custom parameters
docker-compose exec trading-bot python -c "
from src.utils.rl_agent import train_rl_agent_for_symbol
agent, stats = train_rl_agent_for_symbol(
    symbol='ETHUSDT',
    timeframe='5m',
    lookback_days=180,
    total_timesteps=200000
)
print(stats)
"
```

---

## 🧠 How RL Training Works

### The Trading Environment

The RL agent learns by:
1. **Observing** market state (price, volume, indicators, position)
2. **Taking actions** (HOLD, BUY, SELL, BUY_LARGE, SELL_TRAILING)
3. **Receiving rewards** based on:
   - Profit/loss
   - Risk management (drawdown penalties)
   - Sharpe ratio improvements

### Training Process

```
1. Fetch Historical Data (Binance API)
   ↓
2. Create Trading Environment (Gym)
   ↓
3. Initialize PPO Agent (stable-baselines3)
   ↓
4. Train for N timesteps
   - Agent takes actions
   - Environment returns rewards
   - Agent learns from outcomes
   ↓
5. Evaluate on Test Episodes
   ↓
6. Save Model + Metadata
```

### Algorithms Available

**PPO (Proximal Policy Optimization)** ⭐ Recommended
- Most stable and reliable
- Good balance of exploration/exploitation
- Works well for trading

**A2C (Advantage Actor-Critic)**
- Faster training
- More sensitive to hyperparameters
- Good for quick experiments

---

## 📊 Understanding Results

### Key Metrics

**Avg Return %**
- Average profit/loss per episode
- Target: > 5% for short-term trading
- Higher is better

**Sharpe Ratio**
- Risk-adjusted returns
- Target: > 1.0 (good), > 2.0 (excellent)
- Measures return per unit of risk

**Win Rate**
- Percentage of profitable trades
- Target: > 50%
- Balance with avg trade size

**Max Drawdown**
- Largest peak-to-trough decline
- Target: < 10%
- Lower is safer

---

## 🎛️ Training Parameters

### Recommended Settings

| Use Case | Timeframe | Lookback Days | Training Steps |
|----------|-----------|---------------|----------------|
| **Quick Test** | 5m | 90 | 50,000 |
| **Standard** | 5m | 180 | 100,000 |
| **Production** | 15m | 365 | 500,000 |
| **Long-term** | 1h | 365 | 1,000,000 |

### Tuning Guide

**More Training Steps** = Better performance (but slower)
- Start: 50k-100k for testing
- Production: 200k-500k
- Expert: 1M+ for best results

**More Lookback Days** = More diverse experiences
- Minimum: 90 days
- Recommended: 180-365 days
- Captures different market regimes

**Shorter Timeframes** = More trades, faster feedback
- 1m-5m: Scalping/day trading
- 15m-1h: Swing trading
- 4h-1d: Position trading

---

## 🔧 Advanced Configuration

### Custom Features

Edit `src/utils/rl_trading_env.py` to add:
- Custom indicators
- Additional market data
- Alternative reward functions
- Position sizing rules

### Hyperparameter Tuning

Edit `src/utils/rl_agent.py` PPO config:
```python
self.agent = PPO(
    'MlpPolicy',
    env,
    learning_rate=3e-4,      # Lower = more stable
    n_steps=2048,            # Rollout buffer size
    batch_size=64,           # Training batch size
    n_epochs=10,             # Gradient updates per rollout
    gamma=0.99,              # Discount factor
    ent_coef=0.01,           # Exploration bonus
)
```

---

## 🐳 Docker Commands

```bash
# Build with RL dependencies
docker-compose build --no-cache

# Start services
docker-compose up -d

# View training logs
docker-compose logs -f trading-bot

# Train via Docker CLI
docker-compose exec trading-bot python -m src.utils.rl_agent

# Access container shell
docker-compose exec trading-bot bash

# View trained models
docker-compose exec trading-bot ls -lh models/rl_agents/
```

---

## 📁 File Structure

```
models/rl_agents/
├── BTCUSDT_5m_rl_agent.zip         # Trained model
├── BTCUSDT_5m_rl_agent.meta.json   # Training metadata
├── ETHUSDT_15m_rl_agent.zip
└── ETHUSDT_15m_rl_agent.meta.json

logs/
└── rl_tensorboard/                  # TensorBoard logs (optional)

src/utils/
├── rl_agent.py                      # Training script
└── rl_trading_env.py                # Gym environment
```

---

## 🔥 Performance Tips

1. **Start Small**
   - Train on 50k-100k steps first
   - Validate results before scaling up

2. **Use Multiple Timeframes**
   - Train separate agents for 5m, 15m, 1h
   - Compare performance

3. **Retrain Regularly**
   - Market conditions change
   - Retrain monthly or after regime shifts

4. **Combine with ML Models**
   - Use RL for execution timing
   - Use ML models for signal generation

5. **Monitor Evaluation**
   - Check eval metrics after training
   - Poor eval = overfit or bad hyperparams

---

## 🛠️ Troubleshooting

### Training Fails Immediately
- Check data availability (Binance API limits)
- Verify symbol is valid (USDT pair)
- Ensure enough historical data exists

### Poor Performance (negative returns)
- Increase training steps (50k → 200k)
- Adjust reward function in `rl_trading_env.py`
- Try different timeframe
- Check if market was trending/ranging during training period

### Out of Memory
- Reduce `lookback_days` (365 → 180)
- Lower `max_episode_steps` in env
- Use smaller `n_steps` in PPO config

### Slow Training
- Use GPU if available (check stable-baselines3 GPU support)
- Reduce `total_timesteps`
- Train on shorter timeframe (1h → 5m has fewer candles)

---

## 🎓 Next Steps

1. ✅ Train your first agent (BTCUSDT, 5m, 100k steps)
2. ✅ Evaluate performance
3. ✅ Compare PPO vs A2C
4. ✅ Train on multiple symbols
5. 🔜 Deploy in paper trading mode
6. 🔜 Integrate with live bot (Phase 6)
7. 🔜 Build dashboard visualizations (Phase 5)

---

## 📚 Resources

- **stable-baselines3 docs**: https://stable-baselines3.readthedocs.io/
- **RL concepts**: https://spinningup.openai.com/
- **PPO paper**: https://arxiv.org/abs/1707.06347
- **Trading with RL**: https://arxiv.org/abs/1907.04373

---

## 🤝 Contributing

Found a bug or have a feature request for RL training?
Open an issue or PR on your repo!

---

**Happy Training! 🚀**
