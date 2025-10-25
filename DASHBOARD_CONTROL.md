# Dashboard Control - Multi-Pair Bot Integration

## Overview
The web dashboard now fully controls the **Multi-Pair Trading Bot** with live position tracking, P&L monitoring, and real-time updates.

## What Changed

### ✅ Bot Integration
- Dashboard now starts/stops the **Multi-Pair Bot** (not single-pair bot)
- All position tracking works across multiple pairs simultaneously
- Dynamic position sizing integrated into UI

### ✅ Live Positions Tab
Navigate to **Positions** tab to see:
- **Live bot status** (Running/Stopped)
- **Active positions** with real-time P&L
- **Recent trades** history
- **Live activity feed** (updates every 3 seconds)

### ✅ Stop Bot Behavior
When you click **Stop Bot**:
- ✅ Bot stops monitoring markets
- ✅ **Positions remain OPEN** (safe default)
- ✅ Stop-loss and take-profit still active
- ⚠️ Manual position closing not yet implemented

**Why leave positions open?**
1. Avoids panic selling
2. Risk management (SL/TP) still protects you
3. Can resume bot to continue managing positions
4. You can manually close via Binance if needed

## Using the Dashboard

### 1. Start the Bot
1. Open dashboard: http://localhost:5000
2. Click **"▶️ Start Bot"** button
3. Bot discovers all trained ML models
4. Begins trading up to 3 pairs simultaneously

### 2. Monitor Positions
1. Click **"Positions"** in left sidebar
2. See all active positions updating live
3. View total P&L and exposure
4. Monitor recent trade history

### 3. Stop the Bot
1. Click **"⏸️ Stop Bot"** button
2. Bot stops analyzing markets
3. Positions remain open (protected by SL/TP)
4. Resume anytime to continue trading

### 4. Train New Models
1. Click **"ML Training"** in sidebar
2. Enter any USDT pair (e.g., ETHUSDT, BNBUSDT)
3. Select timeframe and lookback period
4. Click **"Train Model"**
5. Bot will auto-discover new models next run

### 5. Scan Market
1. Click **"Market Scanner"** in sidebar
2. Click **"Scan Market"** button
3. See all USDT pairs ranked by volume
4. ML signals shown for pairs with trained models
5. Confidence scores based on real predictions

## API Endpoints

The dashboard uses these APIs:

```bash
GET  /api/status       # Bot status and config
POST /api/start        # Start multi-pair bot
POST /api/stop         # Stop bot (positions stay open)
GET  /api/positions    # Live positions with P&L
GET  /api/trades       # Recent trade history
GET  /api/scan         # Market scanner with ML signals
GET  /api/models       # List trained models
POST /api/train        # Train new model
GET  /api/logs         # System logs
```

## Position Data Structure

Positions show:
- **Symbol**: Trading pair
- **Entry Price**: Price when position opened
- **Current Price**: Live market price
- **Size**: Position size in USDT
- **P&L**: Profit/loss in $ and %
- **Confidence**: ML confidence score (55-100%)
- **Duration**: How long position has been open

## Auto-Refresh Behavior

- **Overview**: Refreshes every 5 seconds
- **Positions**: Refreshes every 3 seconds (when tab active)
- **Logs**: Refreshes every 10 seconds
- **Trades**: Refreshes every 3 seconds (when tab active)

## Configuration

Bot settings are controlled via `.env`:

```bash
# Multi-pair bot automatically:
# - Discovers all trained ML models
# - Trades up to MAX_CONCURRENT_POSITIONS pairs
# - Uses dynamic position sizing (ML confidence-based)
# - Respects TOTAL_PORTFOLIO_LIMIT

MAX_CONCURRENT_POSITIONS=3    # Max open positions
BASE_POSITION_SIZE=20         # Min position ($20)
MAX_POSITION_SIZE=100         # Max position ($100)
TOTAL_PORTFOLIO_LIMIT=250     # Max total exposure
```

## Important Notes

### ⚠️ Positions Stay Open When Stopping
This is **intentional and safe**:
- Stop-loss (2%) and take-profit (5%) remain active
- You maintain control over exits
- No forced liquidations
- Resume bot anytime to continue management

### 🔄 Resuming After Stop
When you restart the bot:
- It rediscovers all trained models
- Continues managing existing positions
- Can open new positions (up to limit)
- Position tracking resumes automatically

### 📊 Dynamic Position Sizing
Position sizes vary by ML confidence:
- **55-65% confidence** → $20 position (5% of balance)
- **65-75% confidence** → $40-70 position (10-17%)
- **75%+ confidence** → $70-100 position (17-25%)

This is shown live in the dashboard!

## Next Features (TODO)

- [ ] **Force-close positions** when stopping bot
- [ ] **Persistent trade history** (database)
- [ ] **Email/SMS notifications** for trades
- [ ] **Advanced charting** for positions
- [ ] **Manual position management** (close specific pairs)
- [ ] **Backtesting results** in dashboard

## Troubleshooting

### Dashboard shows "Stopped" but bot is running
- Dashboard was restarted but bot process continued
- Safe to click "Start Bot" - it will sync state

### No positions showing
- Bot may not have entered any positions yet
- Check "Market Scanner" for ML signals
- Verify models are trained (ML Training tab)

### Positions not updating
- Check network connection
- Verify Binance API connectivity
- Check logs for errors (Logs tab)

## Quick Commands

```bash
# View web UI logs
docker-compose logs -f web-ui

# Restart dashboard
docker-compose restart web-ui

# Check if bot is running
docker-compose ps

# View bot logs
docker-compose logs multi-pair-bot
```

## Access
- **Dashboard**: http://localhost:5000
- **Single browser tab recommended** (WebSocket connection)

---

**Ready to trade?** Click "Start Bot" in the dashboard! 🚀
