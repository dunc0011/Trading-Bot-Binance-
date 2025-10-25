# Binance Trading Bot

A Python-based automated trading bot for Binance cryptocurrency exchange with support for custom strategies, risk management, and Docker deployment.

## Features

- 🤖 Automated trading with customizable strategies
- 📊 Simple Moving Average (SMA) crossover strategy included
- 🛡️ Built-in risk management and position sizing
- 🔐 Secure API key management with environment variables
- 📝 Comprehensive logging with colored output
- 🐳 Docker support for containerized deployment
- 🧪 Testnet support for risk-free testing
- 💰 Dry-run mode for strategy validation

## Project Structure

```
binance-trading-bot/
├── src/
│   ├── main.py                 # Entry point
│   ├── bot.py                  # Main bot logic
│   ├── strategies/
│   │   └── simple_strategy.py  # SMA crossover strategy
│   └── utils/
│       ├── risk_manager.py     # Risk management
│       └── order_manager.py    # Order execution
├── config/
│   └── config.py               # Configuration management
├── tests/                      # Unit tests
├── logs/                       # Log files
├── data/                       # Database and data storage
├── requirements.txt            # Python dependencies
├── .env.example               # Environment template
├── Dockerfile                 # Docker image definition
└── docker-compose.yml         # Docker composition
```

## Prerequisites

- Python 3.9+
- Binance account with API keys
- Docker (optional, for containerized deployment)

## Installation

### Local Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd binance-trading-bot
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment:
```bash
cp .env.example .env
# Edit .env with your API keys and settings
```

### Docker Setup

1. Build and run with Docker Compose:
```bash
docker-compose up -d
```

2. View logs:
```bash
docker-compose logs -f
```

## Configuration

Edit the `.env` file with your settings:

```env
# API Credentials
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret

# Trading Settings
TRADING_MODE=testnet          # testnet or live
SYMBOL=BTCUSDT               # Trading pair
TIMEFRAME=1h                 # Candle timeframe

# Risk Management
MAX_POSITION_SIZE=100        # Max position in USDT
STOP_LOSS_PERCENTAGE=2.0     # Stop loss %
TAKE_PROFIT_PERCENTAGE=5.0   # Take profit %

# Bot Settings
DRY_RUN=true                 # Simulate trading
LOG_LEVEL=INFO               # Logging level
```

## Usage

### Running the Bot

**Local:**
```bash
cd src
python main.py
```

**Docker:**
```bash
docker-compose up
```

### Testing Strategies

Always start with:
1. `DRY_RUN=true` to simulate trading
2. `TRADING_MODE=testnet` to use Binance testnet
3. Small `MAX_POSITION_SIZE` to limit risk

### Creating Custom Strategies

1. Create a new strategy file in `src/strategies/`
2. Implement the strategy interface:
```python
class MyStrategy:
    def __init__(self, config):
        self.config = config
    
    def analyze(self, klines):
        # Return trading signal or None
        return {
            'action': 'BUY',  # or 'SELL'
            'price': current_price,
            'reason': 'Strategy signal'
        }
```

3. Update `bot.py` to use your strategy

## Safety & Warnings

⚠️ **Important Safety Notes:**

- Always test strategies in DRY_RUN mode first
- Start with testnet before live trading
- Never commit API keys to version control
- Use small position sizes when starting
- Cryptocurrency trading carries significant risk
- Past performance does not guarantee future results

## Development

### Running Tests

```bash
pytest tests/
```

### Adding Dependencies

```bash
pip install <package>
pip freeze > requirements.txt
```

## Monitoring

Logs are written to:
- Console (with colored output)
- `logs/` directory (file logs)

Monitor your bot:
```bash
tail -f logs/trading_bot.log
```

## Troubleshooting

### API Connection Issues
- Verify API keys are correct
- Check API key permissions (spot trading enabled)
- Ensure IP whitelist is configured (if enabled)

### Strategy Not Triggering
- Check timeframe and data availability
- Verify signal generation logic
- Review logs for errors

### Docker Issues
- Ensure Docker daemon is running
- Check port conflicts
- Review container logs: `docker-compose logs`

## Roadmap

- [ ] Multiple strategy support
- [ ] Backtesting framework
- [ ] Web dashboard for monitoring
- [ ] Telegram notifications
- [ ] Advanced technical indicators
- [ ] Portfolio management
- [ ] Machine learning strategies

## License

MIT License - see LICENSE file for details

## Disclaimer

This software is for educational purposes only. Do not risk money you are afraid to lose. USE THE SOFTWARE AT YOUR OWN RISK. THE AUTHORS AND ALL AFFILIATES ASSUME NO RESPONSIBILITY FOR YOUR TRADING RESULTS.

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new features
4. Submit a pull request

## Support

For issues and questions:
- Open an issue on GitHub
- Review existing documentation
- Check Binance API documentation

---

**Remember:** Never trade with money you can't afford to lose. Always test thoroughly before live trading.
