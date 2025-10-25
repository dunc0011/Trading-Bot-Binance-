# Trading Bot Dashboard Guide

## 🎯 What You're Seeing

The dashboard now has **5 working pages**:

### 1. **Overview** (Home)
- Portfolio stats (balance, positions, P&L, win rate)
- Current bot configuration
- Quick action buttons

### 2. **Market Scanner**
- Scan all USDT pairs for trading opportunities
- Uses ML models to predict profitable trades
- (Backend integration needed)

### 3. **Positions**
- View all active trading positions
- Track P&L in real-time
- (Populated when bot is trading)

### 4. **ML Training**
- **Train models for ANY symbol** - not just ETH!
- Change the symbol to BTCUSDT, SOLUSDT, etc.
- Adjust timeframe and lookback period
- View all trained models

### 5. **Logs**
- Real-time bot logs
- Auto-refreshes every 10 seconds
- Clear button to reset view

---

## 💡 About the Default "ETHUSDT" Symbol

You asked why it defaults to ETHUSDT - **it's just a placeholder!** You can train models for **any USDT trading pair**:

### How to Train Different Symbols:

1. Go to **ML Training** tab
2. Change the symbol field to:
   - `BTCUSDT` - Bitcoin
   - `SOLUSDT` - Solana
   - `ADAUSDT` - Cardano
   - `DOGEUSDT` - Dogecoin
   - Any other USDT pair on Binance!

3. Select your timeframe (1m, 5m, 1h, etc.)
4. Choose lookback days (more data = better model, but slower)
5. Click **Train Model**

The bot will:
- Download historical price data from Binance
- Calculate technical indicators (EMA, RSI, ATR)
- Train a machine learning model
- Save it for future trading

---

## 🧪 About Testing

### What is "Testing"?

Your bot has multiple modes:

1. **Dry Run Mode** (`DRY_RUN=true`)
   - Bot analyzes markets and generates signals
   - **NO real orders** are placed
   - Great for testing strategies safely
   - Your `.env` file controls this

2. **Testnet Mode** (`TRADING_MODE=testnet`)
   - Uses Binance **testnet** (fake money)
   - Actually places orders, but with fake funds
   - Tests the full trading flow
   - Get testnet funds from: https://testnet.binance.vision/

3. **Live Mode** (`TRADING_MODE=live`)
   - **REAL MONEY** trading
   - Only use after thorough testing!

### Current Setup

Check your `.env` file to see which mode you're in:

```bash
# Safe testing setup
DRY_RUN=true
TRADING_MODE=testnet
```

### Why Test First?

- ML models need historical data to learn patterns
- Each symbol/timeframe combination needs its own model
- You want to verify the model performs well before risking real money

---

## 🚀 Typical Workflow

1. **Train a Model** (ML Training tab)
   - Pick a symbol (e.g., BTCUSDT)
   - Choose 1h timeframe
   - Use 90 days of data
   - Wait 2-10 minutes for training

2. **Review Model Performance** (see accuracy, F1 score)
   - Good models: >60% accuracy
   - Check the trained models list

3. **Update Bot Config** (in your `.env` file)
   ```bash
   SYMBOL=BTCUSDT
   TIMEFRAME=1h
   STRATEGY=ml_ema
   ```

4. **Start Bot** (Overview tab > Start Bot button)
   - Bot will use your trained model
   - In dry-run mode, it simulates trades
   - Check logs to see signals

5. **Monitor** (Positions & Logs tabs)
   - Watch for buy/sell signals
   - Track performance
   - Adjust strategy as needed

---

## ⚙️ Multi-Symbol Trading

You can train models for **multiple symbols** and run multiple bots:

1. Train models for: BTCUSDT, ETHUSDT, SOLUSDT
2. Each symbol+timeframe gets its own model file in `models/ml_ema/`
3. Run separate bot instances for each symbol (Docker-based setup)

---

## 📊 Dashboard Features

- ✅ **5 navigation tabs** - all working
- ✅ **Real-time updates** via WebSocket
- ✅ **Modern dark theme** - easy on the eyes
- ✅ **Responsive design** - works on any screen
- ✅ **Live status badges** - see bot & API status
- ✅ **Quick actions** - jump to any page fast

---

## 🐛 Troubleshooting

**Q: Symbol training fails?**
- Make sure the symbol exists on Binance (e.g., BTCUSDT)
- Check you have internet connection
- Binance API might be rate-limited

**Q: Bot won't start?**
- Check your API keys are set in `.env`
- Verify `DRY_RUN=true` for safe testing
- Look at the Logs tab for errors

**Q: No models showing?**
- Click "Refresh" button
- Make sure training completed (check logs)
- Models are saved in `models/ml_ema/` directory

---

Need help? Check the logs tab or the main WARP.md documentation!
