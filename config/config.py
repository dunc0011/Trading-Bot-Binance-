"""
Configuration Management
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration."""
    
    def __init__(self):
        # Binance API
        self.api_key = os.getenv('BINANCE_API_KEY', '')
        self.api_secret = os.getenv('BINANCE_API_SECRET', '')
        
        # Trading settings
        self.trading_mode = os.getenv('TRADING_MODE', 'testnet')
        self.symbol = os.getenv('SYMBOL', 'BTCUSDT')
        self.timeframe = os.getenv('TIMEFRAME', '1h')
        
        # Risk management
        self.max_position_size = float(os.getenv('MAX_POSITION_SIZE', '100'))
        self.stop_loss_percentage = float(os.getenv('STOP_LOSS_PERCENTAGE', '2.0'))
        self.take_profit_percentage = float(os.getenv('TAKE_PROFIT_PERCENTAGE', '5.0'))
        
        # Bot settings
        self.dry_run = os.getenv('DRY_RUN', 'true').lower() == 'true'
        self.log_level = os.getenv('LOG_LEVEL', 'INFO')
        
        # Database
        self.database_url = os.getenv('DATABASE_URL', 'sqlite:///data/trading_bot.db')
        
        # Validate configuration
        self._validate()
    
    def _validate(self):
        """Validate configuration values."""
        if not self.dry_run and (not self.api_key or not self.api_secret):
            raise ValueError("API credentials required for live trading")
        
        if self.trading_mode not in ['testnet', 'live']:
            raise ValueError(f"Invalid trading mode: {self.trading_mode}")
        
        if self.max_position_size <= 0:
            raise ValueError("Max position size must be positive")
