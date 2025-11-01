# Mean Reversion Strategy Implementation Guide

## Overview

This document describes the complete implementation of a mean reversion trading strategy with ML confirmation for the Binance trading bot. The strategy identifies oversold/overbought conditions using RSI and Bollinger Bands, then uses machine learning to predict whether these extremes will result in profitable bounces.

## Strategy Components

### 1. Core Strategy Logic (`src/strategies/mean_reversion_strategy.py`)

**Key Features:**
- **Entry Conditions**: RSI < 30 and BB position < 0.2 (oversold) OR RSI > 70 and BB position > 0.8 (overbought)
- **ML Prediction**: Random Forest classifier predicts bounce probability
- **Exit Conditions**:
  - Target profit at overbought levels (if in position)
  - Automatic exit when price returns to BB mean (0.4-0.6 position)

**Features Used by ML Model:**
- RSI and RSI momentum
- Bollinger Band position and width
- Volume ratio (relative to 20-period MA)
- MACD histogram and change
- ATR (volatility)
- Returns (1-period and 5-period)
- Support/resistance context (distance to highs/lows)

### 2. Training Script (`src/utils/train_mean_reversion.py`)

**Training Process:**
1. **Data Collection**: Fetches historical klines from Binance API
2. **Feature Engineering**: Calculates 13 technical indicators
3. **Labeling**: Identifies profitable bounces (2-5% returns within 10 periods)
4. **Model Selection**: Compares Random Forest vs Gradient Boosting
5. **Cross-Validation**: TimeSeriesSplit with 5 folds
6. **Class Balancing**: SMOTE for handling imbalanced datasets

**Model Performance Metrics:**
- F1 Score (harmonic mean of precision/recall)
- Precision and Recall
- Training/Validation split performance

### 3. Backtesting (`src/utils/backtest_mean_reversion.py`)

**Backtesting Features:**
- Historical simulation with realistic conditions
- Performance metrics calculation:
  - Sharpe ratio (annualized)
  - Win rate
  - Maximum drawdown
  - Profit factor
  - Total return

**Example Output:**
```
BACKTEST RESULTS
==================================================
Symbol: BTCUSDT
Timeframe: 1h
Period: 90 days
Total Trades: 7
Win Rate: 71.4%
Average Win: 1.08%
Average Loss: -2.51%
Profit Factor: 1.07
Total Return: 0.18%
Sharpe Ratio: nan
Max Drawdown: 0.00%
Final Balance: $1001.84
==================================================
```

### 4. Paper Trading Simulation (`src/utils/paper_trading_simulator.py`)

**Simulation Features:**
- Real-time market data integration
- Virtual balance and position tracking
- Realistic trading costs (fees + slippage)
- Live performance monitoring
- Circuit breaker for error handling

### 5. Error Handling (`src/utils/error_handler.py`)

**Robust Error Management:**
- **Rate Limiting**: Prevents API rate limit violations
- **Circuit Breaker**: Temporarily halts trading on repeated failures
- **Exponential Backoff**: Progressive retry delays
- **Error Classification**: Specific handling for different error types

## Configuration

### Environment Variables (`.env`)

```bash
# Strategy Selection
STRATEGY=mean_reversion
SYMBOL=BTCUSDT
TIMEFRAME=1h

# Trading Mode
DRY_RUN=true
TRADING_MODE=testnet

# Mean Reversion Settings
MR_MODEL_DIR=models/mean_reversion
MR_PROBA_THRESHOLD=0.60
MR_TARGET_RETURN_MIN=0.02
MR_TARGET_RETURN_MAX=0.05
MR_HORIZON=10
```

### Model Directory Structure

```
models/mean_reversion/
├── BTCUSDT_1h_mean_reversion.joblib      # Trained model
└── BTCUSDT_1h_mean_reversion.meta.json   # Model metadata
```

## Usage Instructions

### 1. Train the Model

```bash
# Train on 180 days of data
python src/utils/train_mean_reversion.py --symbol BTCUSDT --interval 1h --lookback-days 180

# Dry run training
python src/utils/train_mean_reversion.py --symbol BTCUSDT --interval 1h --lookback-days 30 --dry-run
```

### 2. Backtest Strategy

```bash
# Backtest on 90 days of data
python src/utils/backtest_mean_reversion.py --symbol BTCUSDT --interval 1h --lookback-days 90
```

### 3. Run Paper Trading Simulation

```bash
# Simulate for 24 hours
python -m src.utils.paper_trading_simulator --symbol BTCUSDT --interval 1h --duration-hours 24
```

### 4. Live Trading

```bash
# Set environment variables
export STRATEGY=mean_reversion
export DRY_RUN=false
export TRADING_MODE=live

# Run the bot
python src/main.py
```

## Performance Expectations

### Target Metrics
- **Win Rate**: 60-75%
- **Profit Factor**: > 1.2
- **Sharpe Ratio**: > 1.5
- **Max Drawdown**: < 5%
- **Average Trade Return**: 1-3%

### Risk Management
- **Position Sizing**: 15% of available balance (configurable)
- **Stop Loss**: 2% per trade
- **Take Profit**: 5% per trade
- **Max Drawdown Limit**: 10% (circuit breaker)

## Technical Indicators Explained

### RSI (Relative Strength Index)
- **Formula**: 100 - (100 / (1 + RS))
- **Oversold**: < 30
- **Overbought**: > 70
- **Momentum**: Rate of RSI change

### Bollinger Bands
- **Formula**: SMA ± (2 × Standard Deviation)
- **Position**: (Price - Lower Band) / (Upper Band - Lower Band)
- **Width**: (Upper - Lower) / SMA

### MACD Histogram
- **Formula**: MACD Line - Signal Line
- **Purpose**: Momentum divergence indicator

### ATR (Average True Range)
- **Purpose**: Volatility measurement
- **Usage**: Risk adjustment and position sizing

## Best Practices

### Model Training
1. **Data Quality**: Use clean, gap-free historical data
2. **Feature Selection**: Avoid overfitting with too many features
3. **Cross-Validation**: Always use time-series aware validation
4. **Regular Retraining**: Update models with new market conditions

### Risk Management
1. **Position Sizing**: Never risk more than 1-2% per trade
2. **Diversification**: Trade multiple uncorrelated pairs
3. **Monitoring**: Regular performance reviews
4. **Circuit Breakers**: Automatic shutdown on excessive losses

### Live Trading
1. **Start Small**: Begin with minimal position sizes
2. **Monitor Closely**: First few days of live trading
3. **Gradual Scaling**: Increase size only after proven performance
4. **Emergency Stops**: Quick shutdown mechanisms

## Troubleshooting

### Common Issues

1. **"No trained model found"**
   - Solution: Run training script first
   - Check model directory permissions

2. **Low win rate in backtesting**
   - Check feature calculations
   - Verify labeling logic
   - Consider different timeframes

3. **API rate limit errors**
   - Implement proper rate limiting
   - Use error handler with backoff
   - Consider upgrading API plan

4. **Poor live performance**
   - Compare live vs backtest conditions
   - Check for overfitting
   - Review slippage and fees

### Performance Optimization

1. **Feature Engineering**: Add more relevant indicators
2. **Model Selection**: Try different algorithms (XGBoost, LSTM)
3. **Parameter Tuning**: Optimize hyperparameters
4. **Market Regime**: Adapt to different market conditions

## Future Enhancements

### Planned Features
- **Multi-timeframe Analysis**: Combine signals from different timeframes
- **Market Regime Detection**: Adapt strategy to trending vs ranging markets
- **Dynamic Position Sizing**: Volatility-adjusted sizing
- **Portfolio Optimization**: Multi-asset mean reversion
- **Reinforcement Learning**: Learn optimal entry/exit timing

### Advanced ML Models
- **LSTM Networks**: For sequential pattern recognition
- **Ensemble Methods**: Combine multiple model predictions
- **Online Learning**: Adapt to changing market conditions
- **Feature Importance**: Automatic feature selection

## Support and Maintenance

### Regular Tasks
1. **Model Retraining**: Monthly or when performance degrades
2. **Performance Monitoring**: Daily P&L and risk metrics
3. **Code Updates**: Keep dependencies current
4. **Security Updates**: Monitor for API changes

### Contact and Documentation
- **Logs**: Check `logs/` directory for detailed execution logs
- **Models**: Backup trained models regularly
- **Configuration**: Document all parameter changes
- **Performance**: Maintain trading journal

This implementation provides a solid foundation for mean reversion trading with ML confirmation, following industry best practices for algorithmic trading systems.