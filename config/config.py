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
        
        # Risk management - percentage-based position sizing
        self.position_size_percentage = float(os.getenv('POSITION_SIZE_PERCENTAGE', '15'))
        if not (0 < self.position_size_percentage <= 100):
            raise ValueError("POSITION_SIZE_PERCENTAGE must be between 0 and 100")
        
        # Optional USDT ceiling (safety cap)
        max_pos_str = os.getenv('MAX_POSITION_SIZE', '')
        self.max_position_size = float(max_pos_str) if max_pos_str and max_pos_str.strip() else None
        
        self.stop_loss_percentage = float(os.getenv('STOP_LOSS_PERCENTAGE', '2.0'))
        self.take_profit_percentage = float(os.getenv('TAKE_PROFIT_PERCENTAGE', '5.0'))
        
        # Bot settings
        self.dry_run = os.getenv('DRY_RUN', 'true').lower() == 'true'
        self.log_level = os.getenv('LOG_LEVEL', 'INFO')
        self.strategy = os.getenv('STRATEGY', 'simple')
        
        # ML settings (for ml_ema strategy)
        self.ml_model_dir = os.getenv('ML_MODEL_DIR', 'models/ml_ema')
        self.ml_proba_threshold = float(os.getenv('ML_PROBA_THRESHOLD', '0.55'))
        self.ml_target_horizon = int(os.getenv('ML_TARGET_HORIZON', '1'))
        self.ml_target_return_threshold = float(os.getenv('ML_TARGET_RETURN_THRESHOLD', '0.001'))
        self.ml_wfv_splits = int(os.getenv('ML_WFV_SPLITS', '5'))
        
        # Telegram settings
        self.telegram_enabled = os.getenv('TELEGRAM_NOTIFICATIONS', 'false').lower() == 'true'
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
        
        # Database
        self.database_url = os.getenv('DATABASE_URL', 'sqlite:///data/trading_bot.db')
        
        # Real-time Position Monitoring
        self.realtime_monitoring_enabled = os.getenv('REALTIME_MONITORING_ENABLED', 'true').lower() == 'true'
        self.monitor_poll_fallback_interval = float(os.getenv('MONITOR_POLL_FALLBACK_INTERVAL', '1.0'))
        self.websocket_reconnect_delay = int(os.getenv('WEBSOCKET_RECONNECT_DELAY', '5'))
        
        # Exit Logic Thresholds (for real-time monitor)
        self.partial_exit_1_pct = float(os.getenv('PARTIAL_EXIT_1_PCT', '0.0015'))  # +0.15%
        self.partial_exit_2_pct = float(os.getenv('PARTIAL_EXIT_2_PCT', '0.0030'))  # +0.30%
        self.partial_exit_1_size = float(os.getenv('PARTIAL_EXIT_1_SIZE', '0.60'))  # 60%
        self.partial_exit_2_size = float(os.getenv('PARTIAL_EXIT_2_SIZE', '0.40'))  # 40%
        self.hard_stop_loss_pct = float(os.getenv('HARD_STOP_LOSS_PCT', '0.0050'))  # -0.50%
        self.trailing_lock_1_min = float(os.getenv('TRAILING_LOCK_1_MIN', '0.0015'))  # 0.15%
        self.trailing_lock_1_max = float(os.getenv('TRAILING_LOCK_1_MAX', '0.0030'))  # 0.30%
        self.trailing_lock_1_keep = float(os.getenv('TRAILING_LOCK_1_KEEP', '0.70'))  # keep 70%
        self.trailing_lock_2_keep = float(os.getenv('TRAILING_LOCK_2_KEEP', '0.80'))  # keep 80%
        self.trailing_before_0_2_sl = float(os.getenv('TRAILING_BEFORE_0_2_SL', '0.0020'))  # -0.20%
        self.monitor_tick_ms = int(os.getenv('MONITOR_TICK_MS', '200'))  # 200ms check interval
        
        # Validate configuration
        self._validate()
    
    def _validate(self):
        """Validate configuration values."""
        if not self.dry_run and (not self.api_key or not self.api_secret):
            raise ValueError("API credentials required for live trading")
        
        if self.trading_mode not in ['testnet', 'live']:
            raise ValueError(f"Invalid trading mode: {self.trading_mode}")
        
        # Validate max_position_size only if it's set (not None)
        if self.max_position_size is not None and self.max_position_size <= 0:
            raise ValueError("Max position size must be positive")
