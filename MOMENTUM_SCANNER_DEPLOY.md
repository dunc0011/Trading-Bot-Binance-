# Momentum Scanner - Deployment Guide

## 🎯 What This Does

The Momentum Scanner detects explosive breakout moves like DASH in real-time across **all USDT pairs**, while filtering out pump-and-dump schemes.

**Protection against pump-and-dumps:**
1. ✅ Sustained volume (3+ candles above average, increasing)
2. ✅ No parabolic moves without prior consolidation
3. ✅ $50k+ liquidity on both bid/ask sides
4. ✅ Prior consolidation required (filters straight-line pumps)
5. ✅ Time-based late-entry rejection
6. ✅ $1M+ daily volume floor
7. ✅ Independent from BTC/ETH (not just riding market)
8. ✅ Multi-timeframe trend alignment
9. ✅ RSI in momentum zone (50-80, not overbought)
10. ✅ Volatility cap (max 5% ATR)

## 🚀 Quick Start

### 1. Add to `.env` (already configured in config.py)

```bash
# Momentum Scanner Settings
MOMENTUM_SCANNER_ENABLED=false          # Set to 'true' to enable
MOMENTUM_MIN_VOLUME_USDT=1000000        # $1M minimum daily volume
MOMENTUM_AUTO_TRADE=false               # false = alerts only, true = auto-trade
MOMENTUM_ALERT_THRESHOLD=7              # 7/10 filters = Telegram alert
MOMENTUM_TRADE_THRESHOLD=10             # 10/10 filters = auto-trade
MOMENTUM_MAX_POSITIONS=3                # Max 3 momentum trades open
MOMENTUM_POSITION_SIZE_PCT=2.0          # 2% of portfolio per trade
MOMENTUM_STOP_LOSS_PCT=7.0              # 7% stop loss
MOMENTUM_TAKE_PROFIT_PCT=14.0           # 14% take profit (2:1 R/R)
```

### 2. Integration Status

**✅ Completed:**
- Order book analyzer (`src/utils/order_book_analyzer.py`)
- Risk manager (`src/utils/momentum_risk_manager.py`)
- Scanner engine (`src/utils/momentum_scanner.py`)
- Configuration system (`config/config.py`)

**⏳ Remaining:**
- Wire scanner into `src/multi_pair_bot.py`
- Add Telegram alert formatting
- Enable in `.env`
- Test in dry-run mode

### 3. Deployment Phases

**Phase 1: Alerts Only (Recommended First Step)**
```bash
MOMENTUM_SCANNER_ENABLED=true
MOMENTUM_AUTO_TRADE=false
DRY_RUN=true
```
- Scanner runs every 60 seconds
- Sends Telegram alerts for 7-9/10 filter signals
- No trading - just notifications
- Review alerts to tune thresholds

**Phase 2: Dry-Run Auto-Trade**
```bash
MOMENTUM_SCANNER_ENABLED=true
MOMENTUM_AUTO_TRADE=true
DRY_RUN=true
```
- Auto-trades 10/10 filter signals in dry-run mode
- Logs "[DRY RUN] Would execute..." messages
- Test risk management logic
- Verify trailing stops and TTL exits

**Phase 3: Live Trading (After Testing)**
```bash
MOMENTUM_SCANNER_ENABLED=true
MOMENTUM_AUTO_TRADE=true
DRY_RUN=false
MOMENTUM_TRADE_THRESHOLD=10    # Require perfect 10/10 score
```
- Auto-trades **only** 10/10 filter signals
- Max 3 momentum positions
- 2% position sizing
- 7% SL, 14% TP, trailing stops activated at +7%

## 📊 How Signals Work

### Signal Levels

**10/10 filters:** Auto-trade (if `MOMENTUM_AUTO_TRADE=true`)
- All filters passed
- Highest confidence
- Rare but high-quality setups

**7-9/10 filters:** Telegram alert only
- Strong signal but missing 1-3 filters
- Manual review recommended
- More frequent than 10/10

**<7/10 filters:** Ignored
- Too risky or low-quality

### Momentum Score (0-10)

Weighted composite:
- **35%** Price momentum (5m/15m/1h)
- **25%** Volume surge (3-5x average)
- **20%** ADX strength (trend power)
- **10%** Bollinger Band expansion
- **10%** Multi-timeframe alignment

**8.0+**: Excellent momentum
**6.0-7.9**: Good momentum
**<6.0**: Weak momentum

## 🛡️ Risk Management

### Position Sizing
- 2% of portfolio per trade (configurable)
- Capped by `MAX_POSITION_SIZE` if set
- Minimum $10 notional (Binance requirement)

### Stop Loss / Take Profit
- **Entry**: Current price - 0.5×ATR (pullback entry)
- **Stop Loss**: Entry × (1 - 7%) = -7%
- **Take Profit**: Entry × (1 + 14%) = +14%
- **Risk/Reward**: 2:1

### Trailing Stop
- **Activation**: +7% gain
- **Trail Distance**: 50% of peak gain above +7%
- **Example**: If price hits +10%, stop moves to entry + 1.5% (50% of the 3% excess gain)

### Time-to-Live (TTL)
- **Duration**: 4 hours max
- **Extension**: Granted if position is +3% or more
- **Force Exit**: If ADX < 25 or volume weakening after 4h

### Position Limits
- **Momentum positions**: Max 3
- **Total positions**: Max 10 (bot-wide)
- **Blocks new momentum entries** if total >10

## 🔧 Tuning Thresholds

### More Conservative (Fewer Signals)
```bash
MOMENTUM_MIN_VOLUME_USDT=5000000        # $5M instead of $1M
MOMENTUM_ALERT_THRESHOLD=8              # 8/10 instead of 7/10
MOMENTUM_TRADE_THRESHOLD=10             # Keep at 10/10
MOMENTUM_STOP_LOSS_PCT=5.0              # Tighter stop (5% instead of 7%)
```

### More Aggressive (More Signals)
```bash
MOMENTUM_MIN_VOLUME_USDT=500000         # $500k instead of $1M (risky!)
MOMENTUM_ALERT_THRESHOLD=6              # 6/10 instead of 7/10
MOMENTUM_TRADE_THRESHOLD=9              # 9/10 instead of 10/10 (risky!)
MOMENTUM_STOP_LOSS_PCT=10.0             # Wider stop (10% instead of 7%)
```

**⚠️ Warning:** Lowering thresholds increases false positives and pump-and-dump risk.

## 📈 Performance Monitoring

### Logs
- `logs/multi_pair_bot.log` - Scanner cycle summaries
- `logs/momentum_scanner.log` - Detailed filter results

### Key Metrics
- **Scan time**: Should complete in 10-30 seconds
- **Signals per hour**: Expect 0-5 alerts/hour in normal markets
- **10/10 signals**: Very rare (1-3 per day)
- **False positive rate**: Target <10% (rejected by liquidity/pump filters)

### Bot Activity Monitor (Dashboard)
- Real-time scanner progress
- Current momentum signals
- Filter pass/fail breakdown
- Cycle timing

## 🚨 Telegram Alerts

Format:
```
🚀 MOMENTUM ALERT: DASHUSDT

📊 Momentum Score: 8.5/10
💰 Price: $45.67 (+8.7% 1h)
📈 Volume Surge: 4.2x average
🎯 Entry: $45.50 (on pullback)
🛡️ Stop: $42.30 (-7%)
🎁 Target: $52.00 (+14%)

✅ Filters Passed: 9/10
⚠️ Risk: MEDIUM

⏰ 2025-11-01 15:15:00
```

## 🔍 Debugging

### Scanner Not Running
```bash
# Check if enabled
grep MOMENTUM_SCANNER_ENABLED .env

# Check logs
docker-compose logs -f | grep -i momentum

# Verify bot sees config
docker-compose exec trading-bot python -c "from config.config import Config; c=Config(); print(c.momentum_scanner_enabled)"
```

### No Signals Detected
- Normal in sideways markets
- 10/10 signals are rare by design
- Check if pairs have trained ML models (scanner independent, but bot integrates both)
- Lower `MOMENTUM_ALERT_THRESHOLD` temporarily to see 6-7/10 signals

### Too Many False Positives
- Increase `MOMENTUM_MIN_VOLUME_USDT`
- Increase `MOMENTUM_ALERT_THRESHOLD` to 8 or 9
- Review filter failures in logs

## 📚 Architecture

```
MomentumScanner (every 60s)
    ↓
1. Get universe (top 150 USDT pairs by volume)
    ↓
2. Fetch 5m/15m/1h klines (cached)
    ↓
3. Compute indicators (RSI, ADX, ATR, BB, EMAs, volume)
    ↓
4. Apply 10 filters
    ↓
5. Calculate momentum score
    ↓
6. Check order book liquidity ($50k+ each side)
    ↓
7. Generate signal with entry/stop/target
    ↓
8. Route to Telegram (7-9/10) or auto-trade (10/10)
```

## 🎓 Next Steps

1. **Wire scanner into multi_pair_bot.py** (in progress)
2. **Add Telegram alert formatting**
3. **Enable with `MOMENTUM_SCANNER_ENABLED=true`**
4. **Start in alerts-only mode (Phase 1)**
5. **Monitor for 24-48 hours**
6. **Tune thresholds based on signal quality**
7. **Progress to dry-run auto-trade (Phase 2)**
8. **Test for 1 week**
9. **Go live with 10/10-only auto-trade (Phase 3)**

## ⚠️ Important Notes

- Scanner runs **independently** of ML models
- Does NOT require trained models for pairs
- Catches breakouts ML might miss (like DASH)
- Complements existing ML strategy
- Conservative by design (10 strict filters)
- Designed to reject 90%+ of pump-and-dumps
- Position sizing is small (2%) to limit risk

## 🆘 Support

If you encounter issues:
1. Check logs: `docker-compose logs -f`
2. Verify config: Review `.env` settings
3. Test filters individually: Lower thresholds temporarily
4. Review filter failure reasons in logs
5. Adjust thresholds based on market conditions

---

**Status:** Core infrastructure complete. Integration into bot pending.
