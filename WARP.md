# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Development Commands

### Docker Operations (Preferred Workflow)
```bash
# Build and start the bot
docker-compose up -d

# View live logs
docker-compose logs -f

# Rebuild with fresh dependencies
docker-compose build --no-cache

# Stop the bot
docker-compose down

# Access shell inside container
docker-compose exec trading-bot /bin/bash
```

### Local Development (Without Docker)
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the bot
cd src
python main.py
```

### Testing
```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_risk_manager.py

# Run with verbose output
pytest tests/ -v

# Inside Docker
docker-compose exec trading-bot pytest tests/ -v
```

## Architecture Overview

### Component Interaction Flow
```
main.py → TradingBot → Strategy (analyze) → RiskManager (check) → OrderManager (execute)
   ↓            ↓              ↓                    ↓                      ↓
 Config    Binance Client   Klines Data      Risk Validation        Market Orders
```

### Core Components

**TradingBot (`src/bot.py`)**
- Main orchestrator that coordinates all components
- Runs async event loop checking market every 60 seconds
- Manages bot lifecycle (start/stop)
- Connects to Binance API (testnet or live)

**Config (`config/config.py`)**
- Centralized configuration management
- Loads from environment variables via `python-dotenv`
- Validates settings on initialization
- Precedence: `.env` file → environment variables → defaults

**Strategy (`src/strategies/`)**
- Strategy pattern implementation
- Each strategy implements `analyze(klines)` method
- Returns signal dict with: `action`, `price`, `reason`, `indicators`
- Current strategies:
  - `SimpleStrategy`: SMA crossover (10/30 periods)
  - `MLEMAStrategy`: Machine learning EMA strategy with walk-forward validation

**RiskManager (`src/utils/risk_manager.py`)**
- Validates trading signals before execution
- Calculates position sizing (currently fixed)
- Computes stop-loss and take-profit levels
- Expandable for portfolio risk, drawdown limits, volatility filters

**OrderManager (`src/utils/order_manager.py`)**
- Handles order execution via Binance API
- Tracks active orders
- Provides order status and cancellation
- Respects dry-run mode (no actual orders placed)

### Async Patterns
- Bot uses `asyncio` for main event loop
- `TradingBot.start()` is async and runs indefinitely
- `trading_cycle()` executes every 60 seconds via `asyncio.sleep(60)`
- OrderManager's `execute_order()` is async for future webhook support
- All I/O operations should be async when possible

### Strategy Development

To create a new strategy:

1. Create file in `src/strategies/` (e.g., `my_strategy.py`)
2. Implement the interface:
```python
class MyStrategy:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.position = None  # Track state
    
    def analyze(self, klines):
        """
        Args:
            klines: List of kline arrays from Binance API
        
        Returns:
            dict or None: {
                'action': 'BUY' or 'SELL',
                'price': float,
                'reason': str,
                'indicators': dict  # Optional
            }
        """
        # Convert klines to DataFrame
        # Calculate indicators
        # Generate signal
        # Return signal dict or None
```

3. Update `src/bot.py` to instantiate your strategy:
```python
from strategies.my_strategy import MyStrategy
# Replace line: self.strategy = SimpleStrategy(config)
self.strategy = MyStrategy(config)
```

4. Strategy guidelines:
   - Use pandas for data manipulation
   - Leverage pandas-ta or ta libraries for indicators
   - Track internal position state to avoid duplicate signals
   - Return None when no signal to conserve API calls
   - Include reasoning in signal for debugging
   - Use `self.logger` for debugging output

### Configuration

**Environment Variables (.env)**
```bash
# API Credentials (required for live trading)
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret

# Trading Settings
TRADING_MODE=testnet          # testnet | live
SYMBOL=BTCUSDT               # Any Binance trading pair
TIMEFRAME=1h                 # 1m, 5m, 15m, 1h, 4h, 1d

# Risk Management
MAX_POSITION_SIZE=100        # Position size in USDT
STOP_LOSS_PERCENTAGE=2.0     # Stop loss as %
TAKE_PROFIT_PERCENTAGE=5.0   # Take profit as %

# Bot Behavior
DRY_RUN=true                 # true = simulate, false = real orders
LOG_LEVEL=INFO               # DEBUG | INFO | WARNING | ERROR

# Database (optional)
DATABASE_URL=sqlite:///data/trading_bot.db
```

**Config Loading**
- Reads `.env` file via `python-dotenv` on import
- Falls back to environment variables
- Validates required fields based on mode (dry-run vs live)
- Config object accessible in all components

**Safety Checks**
- Live trading requires explicit `CONFIRM` input on startup
- API credentials validated before trading
- Dry-run mode prevents actual order execution
- Testnet mode uses Binance testnet endpoints

## Development Workflow

### Adding New Features
1. Update requirements.txt if adding dependencies
2. Implement feature in appropriate module (strategy/util)
3. Add logging at INFO level for key events
4. Handle exceptions and log errors
5. Test in dry-run mode first
6. Test on testnet before live trading

### Error Handling Conventions
- Use try/except blocks for API calls
- Log exceptions with `logger.error()` or `logger.exception()`
- Fail gracefully - don't crash the bot on single errors
- Use `exc_info=True` for stack traces in logs

### Logging Levels
- **DEBUG**: Detailed diagnostic info (indicator values, calculations)
- **INFO**: General operational events (signals, orders, bot status)
- **WARNING**: Recoverable issues (rejected signals, API limits)
- **ERROR**: Serious problems (order failures, API errors)
- **CRITICAL**: Bot-stopping failures

### Dry-Run Mode
- Enabled via `DRY_RUN=true` in config
- Bot analyzes markets and generates signals
- No actual orders placed to exchange
- Logs show "[DRY RUN] Would execute: ..." messages
- Use for strategy testing and validation

### Testing Safety Progression
1. **Dry-run mode** - Test strategy logic
2. **Testnet** - Test API integration with fake funds
3. **Live with small position** - Test with minimal risk
4. **Live with full position** - Deploy confidently

## Bot Activity Monitor (Web Dashboard)

### Overview
The web dashboard at http://localhost:5000 includes a real-time Bot Activity Monitor on the Positions page that shows exactly what the bot is analyzing in real-time.

### Features
- **Real-time updates** via SocketIO (no page refresh needed)
- **Cycle tracking** with unique IDs for each 60-second analysis cycle
- **Per-pair analysis** showing:
  - Symbol being analyzed
  - ML confidence score (%)
  - Signal type (BUY/SELL/HOLD/ERROR) with color-coded badges
  - Price and reasoning
  - Time since last update
- **Live progress bar** showing analysis progress (X of Y pairs analyzed)
- **Cycle duration** showing how long the last cycle took
- **Connection status** indicator
- **Collapsible** to save screen space

### SocketIO Events
The bot emits these events that drive the UI:

**cycle_start**
- Emitted when a new trading cycle begins
- Includes: cycle_id, timeframe, list of pairs, total_pairs, dry_run status

**pair_analysis_complete**
- Emitted after each pair is analyzed
- Includes: symbol, price, ML confidence, signal, reason, progress, elapsed time
- Updates progress bar in real-time

**cycle_complete**
- Emitted when all pairs analyzed
- Includes: duration, signal counts (BUY/SELL/HOLD), error count

**live_analysis** (enhanced)
- Emitted when ML generates a signal
- Includes: cycle_id, symbol, confidence, price, reason, full indicators

### Log Files
Bot runtime logs are now written to files with rotation:
- **Location**: `logs/multi_pair_bot.log` or `logs/trading_bot.log`
- **Rotation**: 10 MB max per file, 5 backups
- **Format**: `timestamp level logger_name message`
- **Access**: Via `/api/logs?file=multi_pair_bot.log&tail=500` endpoint
- **Viewing**: Logs tab in dashboard updates automatically

### Usage
1. Start bot via dashboard (http://localhost:5000) or CLI
2. Navigate to **Positions** page
3. Watch **Bot Activity Monitor** section update in real-time
4. Click header to collapse/expand
5. Check **Logs** tab to see detailed bot logs

## Important Notes

- **Never commit `.env` file** - Contains API credentials
- **Always test on testnet first** - Binance testnet has same API
- **Docker volumes persist data** - logs/ and data/ mounted for persistence
- **Bot runs in 60-second cycles** - Signals checked once per minute
- **Strategy position tracking** - Strategies must track own position state to avoid duplicate signals
- **No automated exits** - Current implementation requires manual position management or strategy-level exit logic
- **Logs are persisted** - Both in files (logs/) and visible in dashboard
- **Real-time monitoring** - Bot Activity Monitor shows live analysis without polling

## ML EMA Strategy

### Overview
The ML EMA strategy uses machine learning (Random Forest, Gradient Boosting, or Logistic Regression) to predict profitable EMA crossover trades. It employs walk-forward validation to prevent overfitting on time-series data.

### Intelligent Auto-Trainer (NEW!)

**Automatically discovers and trains models for top trading pairs:**

```bash
# Run auto-trainer (discovers top 20 USDT pairs and trains models)
./run_auto_trainer.sh

# Or manually:
docker-compose exec trading-bot python -m src.utils.auto_trainer
```

**What it does:**
- Fetches top 20 USDT pairs by 24h volume from Binance
- Trains ML models for all discovered pairs automatically
- Retrains models weekly to keep them fresh
- Runs continuously, checking every 24 hours
- Saves training history to `models/training_history.json`

**Configuration** (`src/utils/auto_trainer.py`):
```python
self.min_volume_usdt = 10_000_000    # Min 24h volume (10M USDT)
self.max_pairs = 20                  # Train top N pairs
self.retrain_interval_days = 7       # Retrain weekly
self.lookback_days = 90              # Training data history
self.timeframe = '1h'                # Candle interval
```

**See `AUTO_TRAINER_GUIDE.md` for full documentation.**

### Manual Training (Single Pair)

**Inside Docker (recommended):**
```bash
docker-compose exec trading-bot python -m src.utils.train_ml_model \
  --symbol BTCUSDT \
  --interval 1h \
  --lookback-days 90
```

**Locally:**
```bash
python -m src.utils.train_ml_model \
  --symbol BTCUSDT \
  --interval 1h \
  --lookback-days 90 \
  --log-level INFO
```

### Running with ML Strategy

1. Train a model first (see above)
2. Set `STRATEGY=ml_ema` in `.env`
3. Start the bot:
   ```bash
   docker-compose up
   ```

### Feature Engineering
The ML model uses these features (all properly lagged to prevent data leakage):
- EMA 5 and EMA 8
- EMA crossover (normalized)
- EMA crossover momentum
- RSI (14-period)
- ATR and normalized ATR
- Recent returns (1 and 5 periods)
- Volume and volume SMA

### Configuration
```bash
STRATEGY=ml_ema                    # Enable ML strategy
ML_MODEL_DIR=models/ml_ema         # Model storage directory
ML_PROBA_THRESHOLD=0.55            # Prediction threshold (0-1)
ML_TARGET_HORIZON=1                # Periods ahead to predict
ML_TARGET_RETURN_THRESHOLD=0.001   # Min return to signal BUY
ML_WFV_SPLITS=5                    # Walk-forward validation folds
```

### Model Artifacts
- **Models**: `models/ml_ema/{symbol}_{interval}_ml_ema.joblib`
- **Metadata**: `models/ml_ema/{symbol}_{interval}_ml_ema.meta.json`
- **Training logs**: `logs/ml_training.log`

### Important Notes
- **No data leakage**: All features are lagged by 1 period
- **Walk-forward validation**: Uses TimeSeriesSplit for proper time-series CV
- **Long-only**: Strategy only generates BUY/SELL signals (no shorting)
- **Model persistence**: Atomic writes ensure model integrity
- **Risk management**: Integrates with existing RiskManager and OrderManager

## File Locations

- **Logs**: `logs/` directory (Docker volume-mounted)
- **Data**: `data/` directory for databases (Docker volume-mounted)
- **Models**: `models/` directory for ML models (Docker volume-mounted)
- **Source**: `src/` mounted in Docker for development hot-reload
- **Config**: `config/` mounted in Docker for runtime config changes
