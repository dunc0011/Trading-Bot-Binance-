# 💰 Position Sizing Guide

## Current Setup: CONSERVATIVE (5-10% of Balance)

Your bot is now configured to use **only 5-10% of your available funds**.

---

## Current Settings

### Multi-Pair Bot:
```python
Max Positions: 2
Position Size: $20 per trade
Total Limit: $40 maximum exposure
```

### Single-Pair Bot (`.env`):
```bash
MAX_POSITION_SIZE=20  # $20 per trade
```

---

## What This Means

### If You Have $400 Balance:

**Multi-Pair Bot:**
- Opens max 2 positions
- Each position = $20
- Total used = $40 (10% of $400) ✓
- Remaining safe = $360 (90%)

**Risk per trade:**
- With 2% stop-loss = $0.40 risk per trade
- Total risk if both hit stop = $0.80
- Only 0.2% of total balance at risk!

### If You Have $800 Balance:

**Multi-Pair Bot:**
- Opens max 2 positions
- Each position = $20
- Total used = $40 (5% of $800) ✓
- Remaining safe = $760 (95%)

---

## Position Sizing Calculator

### Formula:
```
Position Size = (Account Balance × Risk %) / Max Positions
```

### Examples:

| Your Balance | Risk % | Max Positions | Position Size | Total Used |
|-------------|--------|---------------|---------------|------------|
| $200 | 10% | 2 | $10 | $20 |
| $400 | 10% | 2 | $20 | $40 |
| $500 | 10% | 2 | $25 | $50 |
| $800 | 5% | 2 | $20 | $40 |
| $1,000 | 10% | 2 | $50 | $100 |
| $1,000 | 10% | 5 | $20 | $100 |

---

## How to Adjust for Your Balance

### Step 1: Check Your Balance

```bash
# See your USDT balance
docker-compose exec web-ui python -c "
from binance.client import Client
from config.config import Config
config = Config()
client = Client(config.api_key, config.api_secret, testnet=(config.trading_mode=='testnet'))
balance = client.get_asset_balance(asset='USDT')
print(f'USDT Balance: {balance[\"free\"]}')"
```

### Step 2: Calculate Your Settings

**If you have $500 USDT and want 10% risk:**
```python
Total Risk = $500 × 10% = $50
Max Positions = 2
Position Size = $50 / 2 = $25 per trade
```

### Step 3: Update Settings

**Edit `src/multi_pair_bot.py`:**
```python
self.max_concurrent_positions = 2
self.position_size_per_pair = 25    # $25 per trade
self.total_portfolio_limit = 50     # $50 total
```

**Edit `.env`:**
```bash
MAX_POSITION_SIZE=25  # for single-pair bot
```

---

## Conservative vs Aggressive

### Current: Ultra-Conservative (5-10%)
```
✅ Very safe
✅ Sleep well at night
✅ Small drawdowns
❌ Slower profit growth
❌ Underutilized capital
```

**Good for:**
- Beginners
- Testing strategies
- High volatility markets
- Risk-averse traders

### Moderate (20-30%)
```
Balance of safety and growth
Reasonable risk/reward
Still conservative
```

**Example ($500 balance):**
```python
max_concurrent_positions = 3
position_size_per_pair = 40
total_portfolio_limit = 120  # 24% of $500
```

### Aggressive (50%+)
```
⚠️ Higher profits
⚠️ Higher losses
⚠️ More stressful
⚠️ Can blow account
```

**Not recommended until:**
- 3+ months experience
- Proven profitable strategy
- Strong risk management skills

---

## Real-World Risk Examples

### With Current Settings ($20 per position, 2% stop-loss):

**Worst Case (Both Hit Stop-Loss):**
```
Position 1: -$0.40 (-2%)
Position 2: -$0.40 (-2%)
Total Loss: -$0.80
% of $400 balance: 0.2%
```

**Good Week (10 trades, 60% win rate):**
```
Wins: 6 × $1.00 (+5% each) = +$6.00
Losses: 4 × $0.40 (-2% each) = -$1.60
Net Profit: +$4.40
ROI: 1.1% weekly on $400 balance
```

**Great Month (40 trades, 60% win rate):**
```
Wins: 24 × $1.00 = +$24.00
Losses: 16 × $0.40 = -$6.40
Net Profit: +$17.60
ROI: 4.4% monthly
```

---

## How to Scale Up Safely

### Phase 1: Start Small (Current)
- $20 per position
- 2 max positions
- 10% of balance used
- **Run for 1 month**

### Phase 2: Increase if Profitable
- $40 per position
- 3 max positions
- 20-30% of balance used
- **Run for 2 months**

### Phase 3: Full Allocation
- $100 per position
- 5 max positions
- 50% of balance used
- **Only if consistently profitable**

---

## Quick Commands

### See Your Current Settings:

**Multi-Pair Bot:**
```bash
grep -A3 "Portfolio settings" src/multi_pair_bot.py
```

**Single-Pair Bot:**
```bash
grep "MAX_POSITION_SIZE" .env
```

### Update Position Size:

**For $500 balance (10% = $50 total):**
```bash
# Multi-pair
sed -i '' 's/position_size_per_pair = .*/position_size_per_pair = 25/' src/multi_pair_bot.py
sed -i '' 's/total_portfolio_limit = .*/total_portfolio_limit = 50/' src/multi_pair_bot.py

# Single-pair
sed -i '' 's/MAX_POSITION_SIZE=.*/MAX_POSITION_SIZE=25/' .env
```

---

## Important Notes

⚠️ **NEVER risk more than you can afford to lose**

⚠️ **Start with testnet** (fake money) until profitable:
```bash
# In .env:
TRADING_MODE=testnet
DRY_RUN=true
```

⚠️ **Increase position sizes gradually** - Don't jump from $20 to $200

⚠️ **Track your results** - Only scale up if profitable

✅ **Current settings are SAFE** for $400-800 balance

✅ **You can only lose 10% max** with current limits

---

## Need Help Calculating?

**Tell me your balance and I'll calculate the exact settings!**

Example:
- "I have $1,000 USDT, use 10%"
- "I have $300, be very conservative (5%)"
- "I have $5,000, moderate risk (20%)"

I'll give you the exact numbers to put in the code!
