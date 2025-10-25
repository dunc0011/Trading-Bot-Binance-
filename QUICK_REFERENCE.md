# Quick Reference Guide - Bot Intelligence Features

## 🚀 **Quick Start**

```bash
# Start the bot
docker-compose up -d

# Watch live logs
docker-compose logs -f web-ui

# Stop the bot
docker-compose down
```

---

## 📊 **What to Watch in Logs**

### ✅ **Good Signs** (Features Working)

```bash
# Entry filters working
❌ Skipping: Near recent high
❌ Skipping: Price too extended from EMA21  
❌ Skipping: Recent bars bearish
✅ Microstructure OK - Good buy pressure

# Smart execution
🎯 Executing SMART LIMIT BUY: 0.02 ETHUSDT @ $3939.50
🛡️ Stop-loss placed at $3900.00 for ETHUSDT

# Portfolio protection
Portfolio risk manager initialized with balance: $400.00
VaR 95%: 2.5%
```

### ⚠️ **Important Alerts** (Pay Attention)

```bash
# Circuit breakers
🚨 CIRCUIT BREAKER: Daily loss limit breached: -5.2%
🚨 CIRCUIT BREAKER: Max drawdown limit breached: 15.1%

# Model decay
📉 Model decay detected for BTCUSDT: Accuracy 52% < 55%
⚠️ Model Decay Alert - Hit rate 45% < 50%

# Risk warnings
⚠️ High drawdown: 12.5% (limit: 15%)
⚠️ Daily loss approaching limit: -4.1% (limit: -5%)
```

---

## 🔍 **Log Filtering Commands**

```bash
# Show only entry filter rejections
docker-compose logs -f web-ui | grep "❌ Skipping"

# Show only successful trades
docker-compose logs -f web-ui | grep "✅.*executed"

# Show only risk warnings
docker-compose logs -f web-ui | grep "⚠️"

# Show circuit breaker events
docker-compose logs -f web-ui | grep "🚨"

# Show all important events
docker-compose logs -f web-ui | grep -E "(✅|❌|🎯|🛡️|🚨|📊|⚠️)"
```

---

## 📱 **Telegram Setup** (5 minutes)

1. **Create Bot:**
   - Open Telegram
   - Search for `@BotFather`
   - Send `/newbot`
   - Follow prompts
   - Copy token (looks like `123456:ABCdef...`)

2. **Get Chat ID:**
   - Start chat with your bot
   - Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
   - Find `"chat":{"id":123456789}`
   - Copy the ID

3. **Configure:**
   ```bash
   # Edit .env
   TELEGRAM_BOT_TOKEN=123456:ABCdefGHIjkl...
   TELEGRAM_CHAT_ID=123456789
   ```

4. **Restart Bot:**
   ```bash
   docker-compose down && docker-compose up -d
   ```

5. **Test:**
   - You should get "Bot Status: RUNNING" message

---

## 🎛️ **Key Configuration Settings**

### `.env` File:

```bash
# Trading Mode
TRADING_MODE=testnet    # testnet or live
DRY_RUN=true           # true = simulate, false = real orders

# Position Sizing (will be adjusted by ML confidence)
MAX_POSITION_SIZE=100  # Maximum position size in USDT

# Risk Management
STOP_LOSS_PERCENTAGE=2.0      # Base stop loss %
TAKE_PROFIT_PERCENTAGE=5.0    # Base take profit %

# Telegram Alerts
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
```

---

## 🧪 **Testing Checklist**

### Day 1: DRY_RUN Testing
- [ ] Start bot in DRY_RUN mode
- [ ] Verify entry filters rejecting bad entries
- [ ] Check smart limit orders appear in logs
- [ ] Confirm microstructure checks working
- [ ] Verify Telegram alerts received
- [ ] Watch for 24 hours

### Day 2: Testnet Live
- [ ] Review Day 1 logs (no errors?)
- [ ] Set `DRY_RUN=false`
- [ ] Keep `TRADING_MODE=testnet`
- [ ] Start with small positions
- [ ] Monitor closely for 48 hours
- [ ] Check exchange stops placed correctly

### Day 3+: Mainnet (Optional)
- [ ] Testnet performed well?
- [ ] Set `TRADING_MODE=live`
- [ ] Start with SMALL positions
- [ ] Monitor 24/7 for first week
- [ ] Gradually increase size

---

## 🛡️ **Safety Features Active**

| Feature | Status | What It Does |
|---------|--------|-------------|
| Entry Filters | ✅ | Blocks bad entries (5 checks) |
| Smart Limits | ✅ | Saves spread on entries |
| Microstructure | ✅ | Avoids sell pressure |
| Exchange Stops | ✅ | Protected 24/7 |
| Circuit Breakers | ✅ | Halts on big losses |
| VaR Limits | ✅ | Caps total exposure |
| Model Monitor | ✅ | Detects decay |
| Telegram Alerts | 🟡 | (if configured) |

---

## 📈 **Performance Monitoring**

### Check Model Health:
```bash
docker-compose exec web-ui python -c "
from monitoring.model_monitor import ModelMonitor
m = ModelMonitor()
print(m.generate_report())
"
```

### Check Portfolio Risk:
```bash
docker-compose exec web-ui python -c "
from risk.portfolio_risk import PortfolioRiskManager
from config.config import Config
r = PortfolioRiskManager(Config())
r.set_starting_balance(400)
print(r.get_risk_summary())
"
```

### View Recent Trades:
```bash
docker-compose exec web-ui python -c "
from performance_tracker import PerformanceTracker
p = PerformanceTracker()
import json
print(json.dumps(p.get_trades(10), indent=2))
"
```

---

## 🚨 **Emergency Procedures**

### Bot Losing Money Fast:
```bash
# Stop immediately
docker-compose down

# Check logs
docker-compose logs web-ui > emergency_logs.txt

# Check if circuit breaker should have fired
# (Max 5% daily loss, 15% total drawdown)
```

### Circuit Breaker Activated:
```bash
# Review why it fired (check logs)
docker-compose logs web-ui | grep "CIRCUIT BREAKER"

# If legitimate, wait for market conditions to improve
# If false alarm, can manually reset (not recommended)
```

### Model Decay Detected:
```bash
# Check which symbol
docker-compose logs web-ui | grep "Model decay"

# Retrain the model
docker-compose exec web-ui python -m src.utils.train_advanced_model \
  --symbol BTCUSDT --interval 1h --lookback-days 90

# Bot will automatically use new model
```

---

## 💡 **Pro Tips**

### Maximize Entry Quality:
- Entry filters will reject 50-70% of signals
- This is GOOD - quality over quantity
- Expect fewer trades but higher win rate

### Monitor Microstructure:
- "Heavy sell pressure" rejections = saved losses
- "Good buy pressure" confirmations = quality entries
- Watch imbalance ratio in logs

### Use Telegram:
- Set it up - worth the 5 minutes
- Get real-time trade alerts
- Know when circuit breakers fire
- Receive model decay warnings

### Position Sizing:
- Bot adjusts size based on:
  - ML confidence (55-100%)
  - Market regime (trending vs ranging)
  - VaR limits
  - Don't override unless you know why

---

## 📞 **Support Commands**

```bash
# Check bot status
docker-compose ps

# View all logs
docker-compose logs web-ui

# Restart bot
docker-compose restart web-ui

# Full restart
docker-compose down && docker-compose up -d

# Enter bot container
docker-compose exec web-ui /bin/bash

# Check Python errors
docker-compose logs web-ui | grep "Error\|Exception"
```

---

## 🎯 **Success Metrics to Track**

### Daily:
- [ ] Win rate improved? (target: >55%)
- [ ] Average P&L per trade positive?
- [ ] Entry filter rejection rate (expect 50-70%)
- [ ] Any circuit breaker alerts?

### Weekly:
- [ ] Total P&L trending up?
- [ ] Model accuracy stable? (>55%)
- [ ] Max drawdown under control? (<15%)
- [ ] Any model decay alerts?

### Monthly:
- [ ] ROI vs baseline?
- [ ] Sharpe ratio?
- [ ] Need to retrain models?
- [ ] Adjust position sizes?

---

## ✅ **You're Ready!**

**Your bot is now:**
- 🧠 **Smart** - Filters bad entries, reads order books
- 🛡️ **Protected** - Exchange stops, circuit breakers, VaR limits
- 📊 **Monitored** - Model decay detection, performance tracking
- 📱 **Connected** - Telegram alerts

**Next:** Test in DRY_RUN for 24 hours, then proceed to testnet!

---

**Questions?** Check:
- `IMPROVEMENTS_IMPLEMENTED.md` - Feature details
- `PROGRESS_SUMMARY.md` - Status tracking
- `COMPLETION_REPORT.md` - Full overview
- `WARP.md` - Original documentation
