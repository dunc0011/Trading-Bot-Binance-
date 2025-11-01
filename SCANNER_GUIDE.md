# Momentum Scanner Guide

## Overview

The Momentum Scanner is an independent, multi-timeframe breakout detection system designed to catch explosive price moves (like DASH +45% in 4 hours) that might be missed by ML strategies trained on specific pairs. It runs alongside your existing ML strategies without interference.

### Key Features

- **Multi-timeframe analysis**: 5m, 15m, 1h candles for comprehensive momentum detection
- **10 anti-pump-and-dump filters**: Strict criteria to avoid coordinated pumps and late entries
- **Smart position management**: 7% stop-loss, 14% take-profit, trailing stops, TTL exits
- **Hybrid execution**: Telegram alerts for 7-9/10 filters, auto-trade only on 10/10
- **Rate-limit aware**: Batching, caching, and concurrency limits to avoid API bans
- **Zero interference**: Runs in parallel to ML cycle with separate position tracking

---

## Architecture

### Component Flow

```
MomentumScanner (scan every 60s)
    ↓
1. Discover Universe (exchangeInfo + 24h tickers)
    → Filter USDT pairs, exclude leveraged tokens
    → Pre-filter by 24h volume ≥ MOMENTUM_MIN_VOLUME_USDT
    ↓
2. Fetch Multi-Timeframe Data
    → 5m klines (every cycle)
    → 15m klines (cached, refresh every 3 cycles)
    → 1h klines (cached, refresh every 12 cycles)
    → BTC/ETH always fetched for correlation
    ↓
3. Compute Indicators (per symbol)
    → RSI(14), ADX(14), ATR(14), Bollinger Bands(20,2)
    → Price changes (5m, 15m, 1h)
    → Volume surge (vol / SMA20_vol)
    → EMA crossovers (EMA20 vs EMA50)
    ↓
4. Apply 10 Anti-Pump Filters
    → Sustained volume, parabolic rejection, consolidation, etc.
    ↓
5. Finalize Signal (for candidates passing ≥7 filters)
    → Order book depth check (≥$50k on each side within 1%)
    → Momentum score (0-10 weighted composite)
    → Risk level (LOW/MEDIUM/HIGH)
    → Entry/SL/TP levels
    ↓
6. Hybrid Execution
    → 10/10 filters: Auto-trade (if MOMENTUM_AUTO_TRADE=true)
    → 7-9/10 filters: Telegram alert only
    → <7 filters: Ignored
```

### Integration with Multi-Pair Bot

- **Parallel execution**: Scanner runs as `asyncio.create_task()` alongside ML analysis
- **Separate position tracking**: Positions tagged as `type='MOMENTUM'` vs `type='ML'`
- **Position caps enforced**: Max 3 momentum positions, total positions ≤ 10
- **Trailing management**: Every 60s cycle checks trailing stops, TTL, and reversal signals

---

## Anti-Pump-and-Dump Filters

### 1. Sustained Volume

**Purpose**: Distinguish genuine breakouts from single-candle volume spikes (pump-and-dump hallmark).

**Criteria**:
- Last 3 candles (5m) must each have volume ≥ 1.5× the 20-period volume SMA
- At least 2 of the last 3 candles must show increasing volume vs previous candle
- Overall volume surge ≥ 3.0× (last candle volume / SMA20)

**Why it works**: Pumps typically show a single massive volume spike followed by immediate collapse. Real breakouts show sustained increasing volume over multiple candles.

---

### 2. Parabolic Rejection

**Purpose**: Avoid late entries into vertical moves without base-building.

**Criteria**:
- If 15m change > 20% OR 1h change > 40%:
  - Reject UNLESS there was prior consolidation in the last 2 hours
  - Consolidation = median ATR% < 3% AND Bollinger Band Width below 50th percentile

**Why it works**: Coordinated pumps often go parabolic immediately without consolidation. Real breakouts typically consolidate before expansion.

---

### 3. Order Book Depth

**Purpose**: Ensure tangible liquidity on both sides to prevent thin-book manipulation.

**Criteria**:
- Bid depth within 1% of mid-price ≥ $50,000 USDT
- Ask depth within 1% of mid-price ≥ $50,000 USDT

**Why it works**: Pumps often occur in thin order books where small buy orders cause massive price spikes. Real momentum has deep liquidity.

**Note**: This check is performed LAST (after technical filters) to minimize API weight (order book calls are expensive).

---

### 4. Consolidation Requirement

**Purpose**: Require proper base-building before breakout.

**Criteria**:
- Prior 2 hours (24×5m candles):
  - Median ATR% < 3%
  - Bollinger Band Width below its 50th percentile

**Why it works**: Real breakouts consolidate to build energy before expansion. Pumps skip this and go vertical immediately.

---

### 5. Time-Based Filter (Late Entry Avoidance)

**Purpose**: Avoid chasing extended moves.

**Criteria**:
- If 2h change > 15% OR 4h change > 15%:
  - Reject UNLESS there was a micro-consolidation (15-30m) immediately before current breakout
  - Micro-consolidation = ATR% < 2% AND volume < SMA for ≥ 3 candles

**Why it works**: Entering after 15%+ moves often catches reversals. Micro-consolidations after extended moves can signal continuation, but we remain conservative.

---

### 6. Market Cap / Volume Floor

**Purpose**: Avoid illiquid micro-caps vulnerable to manipulation.

**Criteria**:
- 24h quote volume ≥ MOMENTUM_MIN_VOLUME_USDT (default: 1,000,000 USDT)

**Why it works**: Low-volume coins are easily manipulated. This threshold ensures only liquid pairs are considered.

---

### 7. Independent Move vs Market

**Purpose**: Avoid beta-chasing when BTC/ETH lifts all boats.

**Criteria**:
- Asset's 15m change ≥ 2× max(BTC 15m change, ETH 15m change)
- Ignored if BTC/ETH are negative (only applies when market is rising)

**Why it works**: Many alts simply follow BTC/ETH. Real alpha is when an asset significantly outperforms the market.

---

### 8. Multi-Timeframe Alignment

**Purpose**: Ensure structural trend, not fleeting noise.

**Criteria**:
- Direction must match across 5m, 15m, AND 1h:
  - Positive returns on all timeframes OR EMA20 > EMA50 on all
  - ADX15m > 25 AND ADX1h > 25 (strong trend on both)

**Why it works**: Pumps may show momentum on 5m but lack structural strength on 15m/1h. Real breakouts are multi-timeframe aligned.

---

### 9. RSI Bounds (Momentum Zone)

**Purpose**: Avoid extreme overbought conditions and weak momentum.

**Criteria**:
- RSI5m and RSI15m both in [50, 80]
- Reject if RSI > 85 (extreme overbought) or RSI < 45 (weak momentum)

**Why it works**: RSI > 85 is often a reversal signal. RSI < 45 lacks conviction. The 50-80 zone is optimal for momentum entries.

---

### 10. Volatility Cap

**Purpose**: Avoid hyper-volatile coins typical of coordinated pumps.

**Criteria**:
- ATR% (ATR / close × 100) on 5m ≤ 5%

**Why it works**: Pumps often show extreme volatility (ATR% > 10%). Real breakouts are strong but controlled.

---

## Momentum Scoring System

### Formula (0-10 scale)

```python
momentum_score = (
    price_momentum_score * 0.35 +     # 35% weight
    volume_surge_score * 0.25 +       # 25% weight
    adx_strength_score * 0.20 +       # 20% weight
    bb_expansion_score * 0.10 +       # 10% weight
    mtf_alignment_bonus * 0.10        # 10% weight
)
```

### Sub-Scores

**Price Momentum** (0-10):
- Average of scaled 5m, 15m, 1h returns
- 5% change → score 5, 10% change → score 10, capped at 10

**Volume Surge** (0-10):
- volume / SMA20_vol, capped at 5×
- 1× → score 0, 3× → score 5, 5× → score 10

**ADX Strength** (0-10):
- Average of ADX15m and ADX1h
- 25 → score 5, 40+ → score 10

**BB Expansion** (0-10):
- BBW / median(BBW_lookback)
- 1.0× → score 0, 2.0× → score 10

**MTF Alignment** (0-10):
- All timeframes aligned (5m, 15m, 1h): score 10
- Partial alignment: proportional score

### Confidence Level

```python
confidence = filters_passed / 10
```

- 10/10 filters → 100% confidence → Auto-trade
- 9/10 filters → 90% confidence → Alert + manual review
- 7-8/10 filters → 70-80% confidence → Alert only
- <7/10 filters → Below threshold → Ignored

---

## Risk Management

### Position Sizing

- **Default**: 2-3% of portfolio (MOMENTUM_POSITION_SIZE_PCT)
- **Caps**:
  - Min: Exchange minimum notional (typically $10-20 USDT)
  - Max: Bot's global MAX_POSITION_SIZE
- **Formula**: `position_size = balance_usdt × (MOMENTUM_POSITION_SIZE_PCT / 100)`

### Stop-Loss and Take-Profit

- **Stop-Loss**: 7% below entry (MOMENTUM_STOP_LOSS_PCT)
- **Take-Profit**: 14% above entry (MOMENTUM_TAKE_PROFIT_PCT)
- **Risk/Reward**: 2:1 ratio

### Trailing Stop

- **Activation**: When price reaches +7% above entry
- **Trail Formula**: `stop = entry + 0.5 × (peak_gain - 7%)`
  - Example: Entry $100, peak $110 (+10%)
  - Trailing stop = $100 + 0.5 × (10% - 7%) = $100 + 1.5% = $101.50
- **Update Frequency**: Every 60-second bot cycle

### Time-to-Live (TTL) Exit

**Trigger Conditions** (all must be true):
- Position held for ≥ 4 hours
- Current price < entry + 3%
- ADX weakening (current ADX < entry ADX - 5)
- Volume weakening (current vol < 1.0× SMA20_vol)

**Rationale**: If momentum stalls for 4 hours with no meaningful gain, exit to free capital.

### Reversal Detection Exit

**Trigger Conditions**:
- RSI divergence: RSI makes lower high while price makes higher high
- Volume confirmation: 5m volume < 0.8× SMA20_vol for 3+ consecutive candles

**Rationale**: Divergence + volume drying up signals momentum exhaustion.

### Position Limits

- **Max Concurrent Momentum Positions**: 3 (MOMENTUM_MAX_POSITIONS)
- **Global Portfolio Cap**: If total positions > 10, block new momentum entries
- **Per-Pair**: No limit, but scanner won't signal again until position closed

---

## Configuration (.env)

### Scanner Behavior

```bash
# Enable/disable scanner
MOMENTUM_SCANNER_ENABLED=true          # Master switch

# Execution mode
MOMENTUM_AUTO_TRADE=true               # false = alerts only
MOMENTUM_ALERT_THRESHOLD=7             # Min filters for Telegram alert
MOMENTUM_TRADE_THRESHOLD=10            # Min filters for auto-trade (recommend 10)

# Universe filtering
MOMENTUM_MIN_VOLUME_USDT=1000000       # 24h volume floor (1M USDT)
MOMENTUM_MAX_PAIRS=150                 # Top N pairs by volume to scan
```

### Risk Parameters

```bash
# Position sizing
MOMENTUM_POSITION_SIZE_PCT=2           # 2-3% of portfolio per trade
MOMENTUM_MAX_POSITIONS=3               # Max concurrent momentum positions

# Stop-loss and take-profit
MOMENTUM_STOP_LOSS_PCT=7.0             # 7% SL
MOMENTUM_TAKE_PROFIT_PCT=14.0          # 14% TP (2:1 R/R)
MOMENTUM_TRAILING_ACTIVATION_PCT=7.0   # Activate trailing at +7%
MOMENTUM_TRAILING_FACTOR=0.5           # Trail at 50% of peak gain
```

### Filter Thresholds (Advanced Tuning)

```bash
# Volume filter
MOMENTUM_VOLUME_SURGE_MIN=3.0          # Min volume surge (vol / SMA20)
MOMENTUM_SUSTAINED_VOLUME_PERIODS=3    # Last N candles must sustain

# Parabolic rejection
MOMENTUM_PARABOLIC_15M_THRESHOLD=20.0  # % change on 15m to trigger check
MOMENTUM_PARABOLIC_1H_THRESHOLD=40.0   # % change on 1h to trigger check

# Consolidation
MOMENTUM_CONSOLIDATION_ATR_PCT=3.0     # Max ATR% for consolidation
MOMENTUM_CONSOLIDATION_PERIODS=24      # Periods to check (24×5m = 2h)

# Order book
MOMENTUM_MIN_LIQUIDITY_EACH_SIDE=50000 # Min USDT on bid/ask within 1%

# RSI bounds
MOMENTUM_RSI_MIN=50                    # Lower bound
MOMENTUM_RSI_MAX=80                    # Upper bound
MOMENTUM_RSI_OVERBOUGHT=85             # Reject if above this

# Volatility
MOMENTUM_ATR_MAX_PCT=5.0               # Max ATR% on 5m

# Independent move
MOMENTUM_INDEPENDENCE_MULTIPLIER=2.0   # Asset change must be 2× BTC/ETH
```

---

## Performance Considerations

### Rate Limiting

**Binance API Weight**:
- Klines: 1 weight per request (50 klines)
- 24h Ticker: 40 weight for all symbols
- Order Book: 50 weight per symbol (limit=500)

**Scanner Strategy**:
- Pre-filter universe with 24h ticker (40 weight, once per cycle)
- Fetch 5m klines for top 150 pairs (150 weight)
- Cache 15m/1h klines (refresh every 3/12 cycles)
- Order book only for finalists (1-5 pairs per cycle)

**Total Weight per Cycle**: ~200-250 (well below 1200/min limit)

### Caching Strategy

```python
# 5m: Always fresh (every cycle)
klines_5m = await fetch_klines(symbols, '5m')

# 15m: Refresh every 3 cycles (3 minutes)
if cycle_count % 3 == 0:
    klines_15m = await fetch_klines(symbols, '15m')

# 1h: Refresh every 12 cycles (12 minutes)
if cycle_count % 12 == 0:
    klines_1h = await fetch_klines(symbols, '1h')
```

### Concurrency Control

```python
# Limit concurrent API calls to avoid overwhelming Binance
semaphore = asyncio.Semaphore(10)

async def fetch_with_limit(symbol):
    async with semaphore:
        return await client.get_klines(symbol=symbol, interval='5m')
```

### Execution Time

- **Target**: Complete scan in < 30 seconds (60s cycle with buffer)
- **Typical**: 15-20 seconds for 150 pairs
- **Breakdown**:
  - Universe discovery: 2-3s
  - Kline fetching: 8-10s (parallel with semaphore)
  - Indicator computation: 3-5s (pandas vectorized)
  - Filter checks: 2-3s
  - Order book finalization: 1-2s (only for finalists)

---

## Testing and Backtesting

### Unit Tests

Run comprehensive filter tests:

```bash
docker-compose exec trading-bot pytest tests/test_momentum_filters.py -v
```

**Coverage**:
- `test_sustained_volume_single_spike_rejected`: Ensures single-spike pumps fail
- `test_sustained_volume_genuine_breakout_passes`: Confirms multi-candle volume accepted
- `test_parabolic_rejection_no_consolidation`: Vertical pumps without base rejected
- `test_parabolic_allowed_with_consolidation`: Consolidation-then-breakout accepted
- `test_rsi_bounds`: Validates RSI 50-80 zone enforcement
- `test_volatility_cap`: ATR% > 5% rejected
- `test_mtf_alignment`: Multi-timeframe trend coherence
- `test_independent_move`: Outperformance vs BTC/ETH required

### Backtest Script

Run historical DASH move and pump examples:

```bash
docker-compose exec trading-bot python scripts/backtest_momentum.py \
  --symbol DASHUSDT \
  --start "2025-01-15 10:00:00" \
  --end "2025-01-15 16:00:00" \
  --output results/dash_backtest.csv
```

**Output**: CSV with columns:
- `timestamp`, `symbol`, `price`, `filters_passed`, `momentum_score`, `latency_seconds`, `outcome` (TP/SL/MISS)

**Metrics to Track**:
- **Detection Latency**: Time from initial breakout to signal generation
- **Filter Pass Rate**: % of scans passing ≥7 filters
- **False Positive Rate**: % of pump-and-dump patterns incorrectly signaled
- **Win Rate**: % of auto-trades hitting TP before SL
- **Average R/R**: (avg_gain / avg_loss)

### Backtesting Historical Pumps

Create a curated list of known pump-and-dump events:

```python
pump_examples = [
    {'symbol': 'RADUSDT', 'date': '2024-12-10', 'type': 'pump'},  # +80% in 10 mins
    {'symbol': 'OMUSDT', 'date': '2024-11-22', 'type': 'pump'},   # +120% in 5 mins
    # Add more...
]
```

Run backtest:

```bash
python scripts/backtest_pumps.py --pump-list data/pump_examples.json
```

**Expected**: ≥ 90% of pumps should fail filters (especially sustained volume, consolidation, parabolic rejection).

---

## Tuning Guide

### Phase 1: Dry-Run Alerts Only

**Goal**: Observe signal quality without risking capital.

**Config**:
```bash
DRY_RUN=true
MOMENTUM_SCANNER_ENABLED=true
MOMENTUM_AUTO_TRADE=false           # Alerts only
MOMENTUM_ALERT_THRESHOLD=7
```

**Monitor**:
- Telegram alerts for 7-9/10 filters
- Check `logs/momentum_scanner.log` for rejected signals
- Review `filters_failed` reasons

**Iterate**:
- If too many alerts (>10/day), increase `MOMENTUM_ALERT_THRESHOLD=8`
- If too few alerts (<1/day), decrease `MOMENTUM_MIN_VOLUME_USDT=500000`
- If late entries, reduce `MOMENTUM_PARABOLIC_15M_THRESHOLD=15.0`

---

### Phase 2: Testnet Auto-Trade (10/10 Only)

**Goal**: Validate execution logic with fake funds.

**Config**:
```bash
TRADING_MODE=testnet
DRY_RUN=false
MOMENTUM_AUTO_TRADE=true
MOMENTUM_TRADE_THRESHOLD=10         # Only 10/10 filters
MOMENTUM_POSITION_SIZE_PCT=1        # Minimal size for testing
```

**Monitor**:
- Order execution logs
- Trailing stop updates
- TTL and reversal exits

**Iterate**:
- If stops too tight, increase `MOMENTUM_STOP_LOSS_PCT=8.0`
- If trailing activates too early, increase `MOMENTUM_TRAILING_ACTIVATION_PCT=10.0`
- If TTL exits too aggressive, increase TTL threshold in code

---

### Phase 3: Live Auto-Trade (Conservative)

**Goal**: Deploy with production capital.

**Config**:
```bash
TRADING_MODE=live
DRY_RUN=false
MOMENTUM_AUTO_TRADE=true
MOMENTUM_TRADE_THRESHOLD=10         # Remain strict
MOMENTUM_POSITION_SIZE_PCT=2        # 2% per trade
MOMENTUM_MAX_POSITIONS=2            # Start with 2, increase to 3 later
```

**Monitor**:
- Win rate (target: >50%)
- Average R/R (target: >1.5:1 after slippage)
- Max drawdown (should be minimal with 7% SL)
- API rate limit warnings

**Iterate**:
- After 20+ trades, review performance
- If win rate >60%, consider increasing position size to 3%
- If false positives persist, add more filters or tighten thresholds
- If missing breakouts, backtest historical data to identify filter issues

---

### Advanced Tuning: Filter Scoring Weights

If you want more control over which filters are prioritized:

**Edit** `src/utils/momentum_scanner.py`:

```python
# Example: Increase weight on volume and consolidation
FILTER_WEIGHTS = {
    'sustained_volume': 1.5,        # Default 1.0
    'consolidation': 1.5,           # Default 1.0
    'parabolic_rejection': 1.0,
    'order_book_depth': 1.2,
    # etc.
}

# Compute weighted score
weighted_score = sum(filter_weights[k] for k in filters_passed) / sum(filter_weights.values())
```

This allows you to require certain "critical" filters (like sustained volume) while being more lenient on others.

---

## Expected Performance

### Historical DASH Example

**Event**: DASH +45% in 4 hours (Jan 15, 2025)

**Expected Detection**:
- **Latency**: 5-15 minutes from initial breakout
- **Filters Passed**: 9-10/10
  - Likely passes: Sustained volume, consolidation, MTF alignment, RSI bounds, liquidity, independence
  - Edge case: Parabolic rejection (depends on rate of ascent)
- **Entry**: ~$42-43 (pullback level after initial spike)
- **Outcome**: TP hit at +14% (~$49-50) before 4h mark

### Typical Signal Frequency

**Conservative (default config)**:
- 10/10 filters: 1-3 signals per week
- 9/10 filters: 5-10 alerts per week
- 7-8/10 filters: 10-20 alerts per week

**Aggressive (tuned for more signals)**:
- Lower thresholds (e.g., MOMENTUM_TRADE_THRESHOLD=9)
- More frequent but lower quality
- Requires active monitoring and manual curation

### Win Rate and R/R

**Conservative (10/10 filters)**:
- **Win Rate**: 50-65% (assuming proper entry on pullback)
- **Avg R/R**: 1.8:1 (14% TP vs 7% SL with trailing locking profits)
- **Max Drawdown**: <5% (3 positions × 7% SL, staggered)

**Aggressive (8-9/10 filters)**:
- **Win Rate**: 40-50%
- **Avg R/R**: 1.5:1
- **Max Drawdown**: <8%

---

## Debugging and Troubleshooting

### No Signals Generated

**Check**:
1. `MOMENTUM_SCANNER_ENABLED=true` in `.env`
2. `MOMENTUM_MIN_VOLUME_USDT` not too high (try 500k)
3. Check `logs/momentum_scanner.log` for rejected symbols and reasons

**Common Issues**:
- **Volume floor too high**: Lower to 500k or 300k
- **Parabolic rejection too strict**: Increase thresholds to 25%/50%
- **RSI bounds too narrow**: Widen to [45, 85]

---

### Too Many False Positives (Pumps Detected)

**Check**:
1. Review `filters_failed` in logs for which filters are NOT catching pumps
2. Backtest against known pump examples to identify weak filters

**Solutions**:
- **Increase consolidation requirement**: `MOMENTUM_CONSOLIDATION_PERIODS=36` (3h instead of 2h)
- **Stricter volume surge**: `MOMENTUM_VOLUME_SURGE_MIN=4.0` (4× instead of 3×)
- **Higher liquidity floor**: `MOMENTUM_MIN_LIQUIDITY_EACH_SIDE=100000` ($100k instead of $50k)

---

### Late Entries (Missing Momentum Peak)

**Check**:
1. Detection latency in backtest results
2. Order book depth check causing delays

**Solutions**:
- **Cache order book**: Pre-fetch depth for top 50 pairs every cycle
- **Reduce kline fetch time**: Increase `max_concurrent_requests` in semaphore
- **Skip 15m/1h caching**: Fetch fresh every cycle (increases API weight, use carefully)

---

### Trailing Stop Not Activating

**Check**:
1. Position peak tracking in `logs/multi_pair_bot.log`
2. `MOMENTUM_TRAILING_ACTIVATION_PCT` threshold

**Debug**:
```bash
docker-compose logs -f | grep "Trailing stop"
```

**Expected Output**:
```
[INFO] DASHUSDT trailing stop activated at +7.2%, current stop: $43.50
[INFO] DASHUSDT trailing stop updated: peak +9.5%, new stop: $44.25
```

If not seeing these logs, check `src/multi_pair_bot.py` for trailing logic in main cycle.

---

### API Rate Limit Warnings

**Check**:
```bash
docker-compose logs -f | grep "rate limit"
```

**Solutions**:
- **Reduce universe size**: `MOMENTUM_MAX_PAIRS=100` (instead of 150)
- **Increase cache intervals**: 15m every 5 cycles, 1h every 15 cycles
- **Reduce concurrency**: `asyncio.Semaphore(5)` (instead of 10)

---

## Security and Safety

### API Key Permissions

**Required Binance API Permissions**:
- **Spot Trading**: Read and write (for orders)
- **Wallet**: Read only (for balance checks)

**NOT Required**:
- Withdraw
- Margin trading
- Futures

### Dry-Run Safety

**Always test with DRY_RUN=true first**:
- Bot simulates orders without execution
- Logs show `[DRY RUN] Would execute: BUY DASHUSDT @ $45.50`
- No actual capital at risk

### Live Trading Checklist

Before enabling live auto-trade:

- [ ] Tested in dry-run mode for ≥48 hours
- [ ] Backtest on historical DASH move shows timely detection
- [ ] Backtest on pump examples shows ≥90% rejection rate
- [ ] Testnet auto-trade (10 trades) executed correctly
- [ ] Trailing stops, TTL, and reversals working as expected
- [ ] Position limits enforced (max 3 momentum positions)
- [ ] Emergency stop command ready: `docker-compose down` or web UI stop button
- [ ] Telegram alerts configured for real-time monitoring

---

## FAQ

### Q: Can I run scanner without ML strategies?

**A**: Yes! Set `PAIRS=` (empty) in `.env` to disable ML. Scanner will run independently.

---

### Q: Does scanner interfere with existing ML strategies?

**A**: No. Scanner runs in parallel via `asyncio.create_task()` and tracks positions separately (`type='MOMENTUM'`). ML strategies remain unaffected.

---

### Q: Can I customize filter thresholds per filter?

**A**: Yes. All thresholds are configurable via `.env`. See "Filter Thresholds (Advanced Tuning)" section above.

---

### Q: How do I backtest on a specific date range?

**A**: Use `scripts/backtest_momentum.py` with `--start` and `--end` flags:

```bash
python scripts/backtest_momentum.py --symbol DASHUSDT \
  --start "2025-01-15 10:00:00" --end "2025-01-15 16:00:00"
```

---

### Q: What if I want to auto-trade on 9/10 filters?

**A**: Change `MOMENTUM_TRADE_THRESHOLD=9` in `.env`. **Caution**: This increases false positives. Recommend extensive dry-run testing first.

---

### Q: How do I disable scanner temporarily without changing .env?

**A**: Set `MOMENTUM_SCANNER_ENABLED=false` in `.env` and restart:

```bash
docker-compose restart
```

---

### Q: Can I scan non-USDT pairs?

**A**: Yes, but requires code changes in `src/utils/momentum_scanner.py` to filter by quote asset. Current implementation hardcoded to USDT pairs.

---

### Q: Does scanner work on other exchanges (e.g., Coinbase, Kraken)?

**A**: Not directly. Implementation is Binance-specific (API calls, kline format). Porting requires:
- Exchange-specific client implementation
- Kline format normalization
- Order book depth API differences

---

## Changelog

**v1.0.0** (Jan 2025)
- Initial release
- 10 anti-pump-and-dump filters
- Multi-timeframe analysis (5m, 15m, 1h)
- Hybrid execution (alerts + auto-trade)
- Trailing stops, TTL, reversal detection
- Rate-limit aware batching and caching

---

## Support and Contributing

**Issues**: Report bugs or suggest features via GitHub issues.

**Logs**: Always include `logs/momentum_scanner.log` and `logs/multi_pair_bot.log` when reporting issues.

**Testing**: Run full test suite before submitting PRs:

```bash
docker-compose exec trading-bot pytest tests/ -v
```

---

## License

Same as parent project. See `LICENSE` file.
