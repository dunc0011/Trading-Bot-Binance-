"""
Multi-Pair Trading Bot

Automatically trades ALL pairs that have trained ML models.
Manages multiple positions simultaneously with portfolio-level risk management.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, List, Optional
import json

from binance.client import Client
from binance.exceptions import BinanceAPIException
from config.config import Config
from strategies.advanced_ml_strategy import AdvancedMLStrategy

# Try to import RL strategy (optional dependency)
try:
    from strategies.rl_strategy import RLStrategy
    RL_AVAILABLE = True
except ImportError:
    RL_AVAILABLE = False
    import logging
    logging.warning("RL strategy not available - install stable-baselines3 to enable")

from utils.advanced_risk_manager import AdvancedRiskManager
from utils.order_manager import OrderManager
from utils.continuous_trainer import ContinuousTrainer
from utils.volume_profile import VolumeProfileAnalyzer
from utils.microstructure import MicrostructureAnalyzer
from utils.realtime_position_monitor import RealtimePositionMonitor
from performance_tracker import PerformanceTracker
from alerts.telegram_client import TelegramClient
from monitoring.model_monitor import ModelMonitor
from risk.portfolio_risk import PortfolioRiskManager
# Adaptive learning systems
from analytics.pattern_analyzer import PatternAnalyzer
from adaptive.parameter_tuner import AdaptiveParameterTuner
from meta_learning.ensemble_optimizer import EnsembleOptimizer
from utils.trade_logger import TradeLogger
from utils.rl_online_learner import get_online_learner
from utils.position_tracker import PositionTracker


logger = logging.getLogger(__name__)


def setup_file_logger(name: str, filename: str, level=logging.INFO) -> logging.Logger:
    """Setup file-based logging with rotation"""
    os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else 'logs', exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid duplicate handlers
    base_filename = os.path.basename(filename)
    has_handler = any(
        isinstance(h, RotatingFileHandler) and 
        getattr(h, 'baseFilename', '').endswith(base_filename)
        for h in logger.handlers
    )
    
    if not has_handler:
        handler = RotatingFileHandler(
            filename,
            maxBytes=10_000_000,  # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        formatter = logging.Formatter(
            '%(asctime)s %(levelname)s %(name)s %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.info(f"File logging initialized: {filename}")
    
    return logger


class MultiPairBot:
    """
    Multi-pair trading bot that:
    - Discovers all available ML models
    - Trades each pair independently
    - Manages portfolio-level risk
    - Handles multiple positions simultaneously
    """
    
    def __init__(self, config: Config, socketio=None):
        self.config = config
        self.running = False
        self.socketio = socketio  # For real-time UI updates
        self.current_cycle_id = None  # Track current trading cycle
        
        # Setup file logging
        setup_file_logger(__name__, 'logs/multi_pair_bot.log', logging.INFO)
        
        # Binance client with increased recvWindow for timestamp tolerance
        if config.trading_mode == "testnet":
            self.client = Client(config.api_key, config.api_secret, testnet=True)
        else:
            self.client = Client(config.api_key, config.api_secret)
        
        # Increase recvWindow to 10 seconds to handle network latency
        self.client.timestamp_offset = 0  # Auto-sync with Binance server time
        
        # Portfolio settings - DYNAMIC POSITION SIZING
        self.max_concurrent_positions = 15  # Max 15 open positions
        
        # Use percentage-based sizing as base (supports None for max_position_size)
        if config.max_position_size is not None:
            self.base_position_size = config.max_position_size * 0.5  # Base: 50% of max (low confidence)
            self.max_position_size = config.max_position_size
        else:
            # No cap - use percentage of balance for base sizing
            self.base_position_size = None  # Will be calculated dynamically
            self.max_position_size = None  # No fixed cap
        
        self.position_size_percentage = config.position_size_percentage
        self.total_portfolio_limit = None  # Will be set dynamically based on account balance
        
        # Dynamic sizing based on ML confidence:
        # 55-65% confidence → $20-40 position (5-10% of balance)
        # 65-75% confidence → $40-70 position (10-17% of balance)
        # 75%+ confidence  → $70-100 position (17-25% of balance)
        
        # Correlation groups (prevent over-exposure to correlated assets)
        self.correlation_groups = {
            'major': ['BTCUSDT', 'ETHUSDT', 'BNBUSDT'],  # Major coins (highly correlated)
            'defi': ['SOLUSDT', 'AVAXUSDT', 'NEARUSDT', 'ADAUSDT'],  # DeFi/Smart contract platforms
            'payments': ['XRPUSDT', 'XLMUSDT', 'TRXUSDT'],  # Payment/transfer coins
            'altcoins': ['DOGEUSDT', 'SHIBUSDT', 'FLOKIUSDT'],  # Meme coins
            'layer1': ['DOTUSDT', 'ATOMUSDT', 'ALGOUSDT'],  # Layer 1 blockchains
        }
        self.max_per_group = 1  # Max 1 position per correlation group
        
        # Track active positions and strategies
        self.active_positions = {}  # symbol -> position info
        self.position_tracker = PositionTracker()  # Persistent storage
        self.strategies = {}        # symbol -> MLEMAStrategy instance
        self.risk_managers = {}     # symbol -> RiskManager instance
        self.order_managers = {}    # symbol -> OrderManager instance
        self.model_accuracies = {}  # symbol -> accuracy (for priority scoring)
        self.model_performance = {}  # symbol -> {'consecutive_losses': int, 'disabled_until': timestamp}
        self.model_loss_threshold = 3  # Disable model after 3 consecutive losses
        self.model_cooldown_hours = 24  # Re-enable after 24 hours
        
        # Blacklist symbols with proven terrible performance or no volatility
        self.blacklisted_symbols = {
            # Terrible performers
            'ZECUSDT', 'PEPEUSDT', 'FLOKIUSDT', 'PENDLEUSDT', 'ETHFIUSDT', 'PENGUUSDT', 'ONDOUSDT',
            # Stablecoins (no volatility - always 1:1)
            'USDCUSDT', 'FDUSDUSDT', 'TUSDUSDT', 'BUSDUSDT', 'USDEUSDT', 'USDPUSDT', 'PAXUSDT',
            # Not permitted on this account
            'FFUSDT', 'VIRTUALUSDT', 'EULUSDT'
        }
        
        # Confidence filter: Accept 55-100% confidence signals
        self.min_confidence = 0.55  # Minimum 55% - accept more signals
        self.max_confidence = 1.00  # No cap - accept all high confidence signals
        
        # Intelligent scanning state
        self.recently_exited = {}   # symbol -> exit_timestamp (track for 15 mins)
        self.all_pairs_rotation_idx = 0  # Rotate through all pairs on alternating cycles
        self.scan_all_pairs_this_cycle = False  # Toggle between full scan and position-only
        
        # Continuous model trainer (retrains all models every 24h)
        self.continuous_trainer = ContinuousTrainer(config, retrain_interval_hours=24)
        
        # Performance tracker
        self.performance_tracker = PerformanceTracker()
        
        # Volume profile analyzer
        self.volume_analyzer = VolumeProfileAnalyzer()
        
        # Microstructure analyzer for smart entry timing
        self.microstructure_analyzer = MicrostructureAnalyzer(self.client)
        
        # Telegram alerts
        telegram_token = getattr(config, 'telegram_bot_token', '')
        telegram_chat_id = getattr(config, 'telegram_chat_id', '')
        self.telegram = TelegramClient(telegram_token, telegram_chat_id)
        
        # Model performance monitoring
        self.model_monitor = ModelMonitor(window_size=100, decay_threshold=0.10)
        
        # Portfolio-level risk management
        self.portfolio_risk = PortfolioRiskManager(config)
        
        # Adaptive learning systems
        self.pattern_analyzer = PatternAnalyzer()
        self.adaptive_tuner = AdaptiveParameterTuner()
        self.meta_learner = EnsembleOptimizer()
        self.trade_logger = TradeLogger()  # For Learning Analytics
        self.rl_online_learner = get_online_learner(config)  # For online RL updates
        logger.info("🧠 Adaptive learning systems initialized")
        
        # Momentum Scanner (independent of ML models)
        self.momentum_scanner = None
        self.momentum_risk_manager = None
        if config.momentum_scanner_enabled:
            from utils.order_book_analyzer import OrderBookAnalyzer
            from utils.momentum_scanner import MomentumScanner
            from utils.momentum_risk_manager import MomentumRiskManager
            
            order_book_analyzer = OrderBookAnalyzer(self.client)
            self.momentum_scanner = MomentumScanner(self.client, config, order_book_analyzer)
            self.momentum_risk_manager = MomentumRiskManager(config)
            logger.info("🚀 Momentum Scanner initialized (enabled)")
        else:
            logger.info("⚠️  Momentum Scanner disabled")
        
        # Real-time Position Monitor (WebSocket-based fast exits)
        self.rtm = None
        if config.realtime_monitoring_enabled:
            # Setup dedicated RTM logger
            rtm_logger = setup_file_logger('rtm', 'logs/multi_pair_bot.log', logging.INFO)
            # RTM will access order_managers dict after it's populated
            self.rtm = RealtimePositionMonitor(
                client=self.client,
                order_manager=self.order_managers,  # Pass dict for per-symbol access
                config=config,
                logger=rtm_logger,
                on_position_closed=self._on_rtm_position_closed,  # Callback for exit tracking
                telegram=self.telegram  # Pass Telegram client for stop loss alerts
            )
            logger.info("✅ Real-time Position Monitor enabled")
        else:
            logger.info("⚠️  Real-time Position Monitor disabled (using legacy 10s polling)")
        
        logger.info("Multi-Pair Bot initialized")
    
    def is_symbol_tradeable(self, symbol: str) -> bool:
        """
        Check if a symbol is tradeable on this account (prevents -2010 errors)
        
        Args:
            symbol: Trading pair to test
            
        Returns:
            True if symbol can be traded, False otherwise
        """
        try:
            # Test with minimum notional via test order
            self.client.create_test_order(
                symbol=symbol,
                side='BUY',
                type='MARKET',
                quoteOrderQty=10
            )
            return True
        except BinanceAPIException as e:
            if e.code == -2010:
                logger.warning(f"{symbol} not permitted for this account - skipping")
                return False
            # Other errors (network, etc) - assume tradeable
            return True
        except Exception:
            # Unknown error - assume tradeable to avoid filtering too aggressively
            return True
    
    def discover_models(self) -> List[Dict]:
        """
        Discover all trained models (RL, advanced ML, and legacy ML)
        
        Returns:
            List of dicts with symbol, timeframe, accuracy
        """
        models = []
        
        # Check for RL models first (highest priority)
        rl_dir = Path('models/rl_agents')
        if rl_dir.exists():
            for meta_file in rl_dir.glob('*.meta.json'):
                try:
                    with open(meta_file, 'r') as f:
                        meta = json.load(f)
                    
                    symbol = meta.get('symbol')
                    timeframe = meta.get('timeframe')
                    
                    if symbol and timeframe:
                        eval_stats = meta.get('evaluation', {})
                        models.append({
                            'symbol': symbol,
                            'timeframe': timeframe,
                            'accuracy': 1.0,  # RL gets priority
                            'f1_score': 1.0,  # RL gets top priority
                            'model_type': 'rl',
                            'model_name': meta.get('algorithm', 'PPO'),
                            'avg_return': eval_stats.get('avg_return_pct', 0),
                            'sharpe': eval_stats.get('avg_sharpe_ratio', 0)
                        })
                        logger.debug(f"Found RL model: {symbol}_{timeframe}")
                except Exception as e:
                    logger.error(f"Error reading {meta_file}: {e}")
        
        # Check for mean reversion models
        mean_reversion_dir = Path('models/mean_reversion')
        if mean_reversion_dir.exists():
            for meta_file in mean_reversion_dir.glob('*.meta.json'):
                try:
                    with open(meta_file, 'r') as f:
                        meta = json.load(f)
                    
                    # Parse filename: BTCUSDT_1h_mean_reversion.meta.json
                    parts = meta_file.stem.replace('_mean_reversion.meta', '').split('_')
                    if len(parts) >= 2:
                        symbol = parts[0]
                        timeframe = parts[1]
                        
                        models.append({
                            'symbol': symbol,
                            'timeframe': timeframe,
                            'accuracy': meta.get('precision', meta.get('accuracy', 0)),  # Use precision for mean reversion
                            'f1_score': meta.get('f1', 0),
                            'model_type': 'mean_reversion',
                            'model_name': meta.get('model_type', 'MeanReversion'),
                            'n_features': 13  # Fixed feature count for mean reversion
                        })
                        logger.debug(f"Found mean reversion model: {symbol}_{timeframe}")
                except Exception as e:
                    logger.error(f"Error reading {meta_file}: {e}")
        
        # Check for advanced models
        advanced_dir = Path('models/advanced_ml')
        if advanced_dir.exists():
            for meta_file in advanced_dir.glob('*.meta.json'):
                try:
                    with open(meta_file, 'r') as f:
                        meta = json.load(f)
                    
                    # Parse filename: BTCUSDT_15m_advanced_ml.meta.json
                    parts = meta_file.stem.replace('_advanced_ml.meta', '').split('_')
                    if len(parts) >= 2:
                        symbol = parts[0]
                        timeframe = parts[1]
                        
                        models.append({
                            'symbol': symbol,
                            'timeframe': timeframe,
                            'accuracy': meta.get('accuracy', 0),
                            'f1_score': meta.get('f1', 0),
                            'model_type': 'advanced',
                            'model_name': meta.get('model_name', 'Unknown'),
                            'n_features': meta.get('n_features', 0)
                        })
                        logger.debug(f"Found advanced model: {symbol}_{timeframe}")
                except Exception as e:
                    logger.error(f"Error reading {meta_file}: {e}")
        
        # ALWAYS check legacy models (not just fallback)
        legacy_dir = Path('models/ml_ema')
        if legacy_dir.exists():
            for meta_file in legacy_dir.glob('*.meta.json'):
                try:
                    with open(meta_file, 'r') as f:
                        meta = json.load(f)
                    
                    parts = meta_file.stem.replace('_ml_ema.meta', '').split('_')
                    if len(parts) >= 2:
                        symbol = parts[0]
                        timeframe = parts[1]
                        
                        models.append({
                            'symbol': symbol,
                            'timeframe': timeframe,
                            'accuracy': meta.get('accuracy', 0),
                            'f1_score': meta.get('f1', 0),
                            'model_type': 'legacy',
                            'model_name': meta.get('model', 'Unknown'),
                            'n_features': 0
                        })
                        logger.debug(f"Found legacy model: {symbol}_{timeframe}")
                except Exception as e:
                    logger.error(f"Error reading {meta_file}: {e}")
        
        # Sort by accuracy (best first) - F1 can be misleading for imbalanced datasets
        models.sort(key=lambda x: x.get('accuracy', 0), reverse=True)
        
        logger.info(f"Discovered {len(models)} trained models")
        advanced_count = sum(1 for m in models if m.get('model_type') == 'advanced')
        legacy_count = len(models) - advanced_count
        logger.info(f"  Advanced models: {advanced_count}, Legacy models: {legacy_count}")
        
        for i, model in enumerate(models[:10], 1):
            model_type = model.get('model_type', 'unknown')
            model_name = model.get('model_name', 'Unknown')
            logger.info(
                f"  {i}. {model['symbol']} ({model['timeframe']}): "
                f"F1={model.get('f1_score', 0)*100:.1f}%, "
                f"Acc={model['accuracy']*100:.1f}% "
                f"[{model_type}/{model_name}]"
            )
        
        return models
    
    def calculate_position_size(self, ml_confidence: float, balance: float = 141.69) -> float:
        """
        Calculate position size based on ML confidence
        
        Args:
            ml_confidence: ML prediction confidence (0.0 to 1.0)
            balance: Current USDT balance (for percentage-based sizing)
            
        Returns:
            Position size in USDT
        """
        # Use percentage-based sizing if no fixed base
        if self.base_position_size is None:
            # Scale percentage based on confidence:
            # 50-65% confidence → 10% of balance
            # 65-75% confidence → 15% of balance  
            # 75%+ confidence → 20% of balance
            confidence_pct = ml_confidence * 100
            if confidence_pct < 65:
                pct = 0.10
            elif confidence_pct < 75:
                pct = 0.15
            else:
                pct = 0.20
            return balance * pct
        
        # Fixed sizing based on base_position_size
        confidence_pct = ml_confidence * 100
        
        # Low confidence (55-65%): Small positions
        if confidence_pct < 65:
            return self.base_position_size
        
        # Medium confidence (65-75%): Medium positions
        elif confidence_pct < 75:
            # Scale from base to base+50
            scale = (confidence_pct - 65) / 10  # 0 to 1
            return self.base_position_size + (50 * scale)
        
        # High confidence (75%+): Large positions
        else:
            # Scale from base+50 to base+80
            scale = min((confidence_pct - 75) / 25, 1.0)  # 0 to 1, capped
            return self.base_position_size + 50 + (30 * scale)
    
    def initialize_pair(self, symbol: str, timeframe: str):
        """
        Initialize trading components for a pair
        
        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            timeframe: Timeframe (e.g., '1h')
        """
        if symbol in self.strategies:
            return  # Already initialized
        
        # Create temporary config for this pair
        pair_config = Config()
        pair_config.symbol = symbol
        pair_config.timeframe = timeframe
        pair_config.max_position_size = self.base_position_size  # Will adjust dynamically
        
        # Initialize components - prioritize RL > Advanced ML > Legacy ML > Scalping
        from pathlib import Path
        
        # Check for models in priority order: RL > Mean Reversion > Advanced ML > Legacy ML > Scalping
        rl_model_path = Path(f'models/rl_agents/{symbol}_{timeframe}_rl_agent.zip')
        mean_reversion_path = Path(f'models/mean_reversion/{symbol}_{timeframe}_mean_reversion.joblib')
        advanced_model_path = Path(f'models/advanced_ml/{symbol}_{timeframe}_advanced_ml.joblib')
        legacy_model_path = Path(f'models/ml_ema/{symbol}_{timeframe}_ml_ema.joblib')
        
        if rl_model_path.exists() and RL_AVAILABLE:
            # Use RL strategy
            self.strategies[symbol] = RLStrategy(pair_config)
            logger.info(f"🤖 Using RL strategy for {symbol}")
        elif mean_reversion_path.exists():
            # Use Mean Reversion strategy
            from strategies.mean_reversion_strategy import MeanReversionStrategy
            self.strategies[symbol] = MeanReversionStrategy(pair_config)
            logger.info(f"🔄 Using Mean Reversion strategy for {symbol}")
        elif advanced_model_path.exists():
            # Use Advanced ML strategy
            from strategies.advanced_ml_strategy import AdvancedMLStrategy
            self.strategies[symbol] = AdvancedMLStrategy(pair_config, model_monitor=self.model_monitor)
            logger.info(f"Using Advanced ML strategy for {symbol}")
        elif legacy_model_path.exists():
            # Use Legacy ML EMA strategy
            from strategies.ml_ema_strategy import MLEMAStrategy
            self.strategies[symbol] = MLEMAStrategy(pair_config)
            logger.info(f"📊 Using ML EMA strategy for {symbol}")
        else:
            # Fallback to fast scalping strategy
            from strategies.scalping_strategy import ScalpingStrategy
            self.strategies[symbol] = ScalpingStrategy(pair_config, model_monitor=self.model_monitor)
            logger.info(f"Using Fast Scalping strategy for {symbol} (no ML model)")
        
        self.risk_managers[symbol] = AdvancedRiskManager(pair_config)
        self.order_managers[symbol] = OrderManager(self.client, pair_config)
        
        logger.info(f"Initialized trading components for {symbol}")
    
    def check_multi_timeframe_confirmation(self, symbol: str, primary_signal: Dict, primary_tf: str) -> bool:
        """
        Confirm signal across multiple timeframes
        
        Args:
            symbol: Trading pair
            primary_signal: Signal from primary timeframe
            primary_tf: Primary timeframe (e.g., '5m')
            
        Returns:
            True if signal confirmed across timeframes
        """
        try:
            # Define timeframe hierarchy
            tf_hierarchy = {'1m': 0, '5m': 1, '15m': 2, '1h': 3, '4h': 4}
            
            if primary_tf not in tf_hierarchy:
                return True  # Can't confirm, allow signal
            
            primary_level = tf_hierarchy[primary_tf]
            action = primary_signal['action']
            
            # Check higher timeframe (trend confirmation)
            if primary_level < 3:  # If not already on 1h
                higher_tf = '1h' if primary_level <= 1 else '4h'
                try:
                    higher_klines = self.client.get_klines(symbol=symbol, interval=higher_tf, limit=50)
                    strategy = self.strategies[symbol]
                    higher_signal = strategy.analyze(higher_klines)
                    
                    if higher_signal and higher_signal['action'] == action:
                        logger.debug(f"{symbol}: ✓ {higher_tf} confirms {action}")
                    elif higher_signal and higher_signal['action'] != action:
                        logger.info(f"{symbol}: ✗ {higher_tf} conflicts with {primary_tf} signal")
                        return False  # Higher timeframe disagrees
                except Exception as e:
                    logger.debug(f"Could not check {higher_tf}: {e}")
            
            return True  # Confirmed or unable to check
        
        except Exception as e:
            logger.error(f"Multi-timeframe check failed: {e}")
            return True  # Default to allowing signal
    
    async def analyze_pair(self, symbol: str, timeframe: str) -> Optional[tuple]:
        """
        Analyze a single pair and generate trading signal with multi-timeframe confirmation
        
        Args:
            symbol: Trading pair
            timeframe: Timeframe
            
        Returns:
            Tuple of (signal dict, klines) or (None, None)
        """
        try:
            # Get recent klines
            klines = self.client.get_klines(
                symbol=symbol,
                interval=timeframe,
                limit=100
            )
            
            # Analyze with ML strategy
            strategy = self.strategies[symbol]
            signal = strategy.analyze(klines)
            
            # Multi-timeframe confirmation for BUY signals
            if signal and signal['action'] == 'BUY':
                if not self.check_multi_timeframe_confirmation(symbol, signal, timeframe):
                    logger.info(f"{symbol}: Signal rejected - multi-timeframe conflict")
                    if self.socketio:
                        self.socketio.emit('signal_rejected', {
                            'symbol': symbol,
                            'action': 'BUY',
                            'reason': 'Multi-timeframe conflict',
                            'timestamp': datetime.now().isoformat()
                        })
                    return (None, klines)
                
                # Volume profile check - DISABLED (too strict for 5m trading)
                # volume_profile = self.volume_analyzer.calculate_volume_profile(klines)
                # if not self.volume_analyzer.should_enter(volume_profile):
                #     logger.info(f"{symbol}: Signal rejected - price at resistance (volume profile)")
                #     if self.socketio:
                #         self.socketio.emit('signal_rejected', {
                #             'symbol': symbol,
                #             'action': 'BUY',
                #             'reason': 'At resistance level',
                #             'timestamp': datetime.now().isoformat()
                #         })
                #     return (None, klines)
                
                # MICROSTRUCTURE CHECK - DISABLED for more aggressive trading
                # microstructure = self.microstructure_analyzer.should_enter(symbol)
                # if not microstructure['allowed']:
                #     logger.info(f"{symbol}: ❌ Signal rejected - {microstructure['reason']}")
                #     if self.socketio:
                #         self.socketio.emit('signal_rejected', {
                #             'symbol': symbol,
                #             'action': 'BUY',
                #             'reason': microstructure['reason'],
                #             'imbalance': microstructure.get('imbalance'),
                #             'spread_pct': microstructure.get('spread_pct'),
                #             'timestamp': datetime.now().isoformat()
                #         })
                #     return (None, klines)
                # else:
                #     logger.info(f"{symbol}: ✅ Microstructure OK - {microstructure['reason']}")
            
            # Emit live analysis
            if self.socketio and signal:
                self.socketio.emit('live_analysis', {
                    'cycle_id': self.current_cycle_id,
                    'symbol': symbol,
                    'action': signal.get('action'),
                    'confidence': signal.get('indicators', {}).get('ml_confidence', 0),
                    'price': signal.get('price'),
                    'reason': signal.get('reason', 'ML signal'),
                    'indicators': signal.get('indicators', {}),
                    'timestamp': datetime.utcnow().isoformat() + 'Z'
                })
            
            return (signal, klines)
        
        except Exception as e:
            logger.error(f"Error analyzing {symbol}: {e}")
            return (None, None)
    
    async def execute_signal(self, symbol: str, signal: Dict, klines: list):
        """
        Execute a trading signal with risk management
        
        Args:
            symbol: Trading pair
            signal: Signal dict from strategy
            klines: Recent klines data for risk validation
        """
        try:
            # Initialize variables for later use
            position_size = None
            ml_confidence = signal.get('indicators', {}).get('ml_confidence', 0.55)
            
            # Check if we can open new position
            if signal['action'] == 'BUY':
                # Check if we already have a position in this symbol
                if symbol in self.active_positions:
                    reason = f"Already holding position in {symbol} (${self.active_positions[symbol]['size']:.0f})"
                    logger.info(f"{symbol}: {reason}")
                    if self.socketio:
                        self.socketio.emit('signal_rejected', {
                            'symbol': symbol,
                            'action': 'BUY',
                            'reason': reason,
                            'timestamp': datetime.now().isoformat()
                        })
                    return
                
                # COOLDOWN CHECK: Block re-entry within 5 mins to prevent fee churn
                if symbol in self.recently_exited:
                    time_since_exit = (datetime.now() - self.recently_exited[symbol]).total_seconds() / 60
                    cooldown_mins = 5  # 5 minute cooldown
                    if time_since_exit < cooldown_mins:
                        reason = f"Cooldown active ({time_since_exit:.1f}m / {cooldown_mins}m)"
                        logger.info(f"{symbol}: ⏱️ {reason} - preventing fee churn")
                        if self.socketio:
                            self.socketio.emit('signal_rejected', {
                                'symbol': symbol,
                                'action': 'BUY',
                                'reason': reason,
                                'timestamp': datetime.now().isoformat()
                            })
                        return
                
                if len(self.active_positions) >= self.max_concurrent_positions:
                    reason = f"Max positions reached ({len(self.active_positions)}/{self.max_concurrent_positions})"
                    logger.info(f"{symbol}: {reason}")
                    if self.socketio:
                        self.socketio.emit('signal_rejected', {
                            'symbol': symbol,
                            'action': 'BUY',
                            'reason': reason,
                            'timestamp': datetime.now().isoformat()
                        })
                    return
                
                # Correlation limit DISABLED for aggressive trading
                # symbol_group = None
                # for group_name, symbols in self.correlation_groups.items():
                #     if symbol in symbols:
                #         symbol_group = group_name
                #         break
                # 
                # if symbol_group:
                #     # Count how many positions we have in this group
                #     group_positions = [s for s in self.active_positions.keys() 
                #                      if s in self.correlation_groups[symbol_group]]
                #     
                #     if len(group_positions) >= self.max_per_group:
                #         reason = f"Correlation limit: already holding {group_positions[0]} in {symbol_group} group"
                #         logger.info(f"{symbol}: {reason}")
                #         if self.socketio:
                #             self.socketio.emit('signal_rejected', {
                #                 'symbol': symbol,
                #                 'action': 'BUY',
                #                 'reason': reason,
                #                 'timestamp': datetime.now().isoformat()
                #             })
                #         return
                
                # Check portfolio-level risk BEFORE calculating position size
                try:
                    account = self.client.get_account()
                    usdt_balance = float([b for b in account['balances'] if b['asset'] == 'USDT'][0]['free'])
                    
                    # Circuit breaker DISABLED for aggressive trading
                    risk_check = self.portfolio_risk.update_balance(usdt_balance)
                    # if not risk_check['allowed']:
                    #     logger.error(f"🚨 CIRCUIT BREAKER: {risk_check['reason']}")
                    #     self.telegram.send_error_alert(f"Circuit breaker activated: {risk_check['reason']}")
                    #     if self.socketio:
                    #         self.socketio.emit('signal_rejected', {
                    #             'symbol': symbol,
                    #             'action': 'BUY',
                    #             'reason': f"Circuit breaker: {risk_check['reason']}",
                    #             'timestamp': datetime.now().isoformat()
                    #         })
                    #     return
                except Exception as e:
                    logger.warning(f"Could not check portfolio risk: {e}")
                    usdt_balance = 400  # Default testnet balance
                
                # Calculate dynamic position size based on ML confidence
                position_size = self.calculate_position_size(ml_confidence, usdt_balance)
                
                # Apply regime-based multiplier
                regime_params = signal.get('regime_params', {})
                if regime_params.get('is_trending'):
                    position_size *= 1.2  # 20% larger in trending markets
                    logger.debug(f"{symbol}: Trending market detected, increasing position size")
                elif regime_params.get('is_ranging'):
                    position_size *= 0.8  # 20% smaller in ranging markets
                    logger.debug(f"{symbol}: Ranging market detected, reducing position size")
                
                # Cap at max position size if set
                if self.max_position_size is not None:
                    position_size = min(position_size, self.max_position_size)
                
                # VaR check DISABLED - too strict for small balance aggressive scalping
                # try:
                #     var_check = self.portfolio_risk.check_var_limit(position_size, usdt_balance)
                #     logger.debug(f"{symbol}: VaR check - desired ${position_size:.0f}, allowed: {var_check['allowed']}, adjusted: ${var_check['adjusted_size']:.0f}")
                #     
                #     if not var_check['allowed']:
                #         logger.warning(f"{symbol}: ❌ Trade REJECTED - {var_check['reason']} (wanted ${position_size:.0f})")
                #         if self.socketio:
                #             self.socketio.emit('signal_rejected', {
                #                 'symbol': symbol,
                #                 'action': 'BUY',
                #                 'reason': var_check['reason'],
                #                 'timestamp': datetime.now().isoformat()
                #             })
                #         return
                #     
                #     # Adjust position size based on VaR
                #     if var_check['adjusted_size'] < position_size:
                #         logger.info(f"{symbol}: Position size adjusted by VaR: ${position_size:.0f} → ${var_check['adjusted_size']:.0f}")
                #     position_size = var_check['adjusted_size']
                # except Exception as e:
                #     logger.warning(f"VaR check failed: {e}")
                
                logger.info(f"{symbol}: ML confidence {ml_confidence*100:.1f}% → ${position_size:.0f} position")
                
                # Check portfolio limit (use full account balance dynamically)
                total_exposure = sum(pos['size'] for pos in self.active_positions.values())
                
                # Calculate dynamic portfolio limit based on current account balance
                try:
                    # Get total account value (USDT + positions)
                    account = self.client.get_account()
                    usdt_free = float([b for b in account['balances'] if b['asset'] == 'USDT'][0]['free'])
                    
                    # Calculate value of open positions
                    positions_value = 0
                    for pos_symbol, pos in self.active_positions.items():
                        try:
                            ticker = self.client.get_symbol_ticker(symbol=pos_symbol)
                            current_price = float(ticker['price'])
                            qty = pos.get('quantity', pos['size'] / pos['entry_price'])
                            positions_value += qty * current_price
                        except:
                            pass
                    
                    # Dynamic limit = full account value (allow using everything)
                    dynamic_limit = usdt_free + positions_value
                    
                    if total_exposure + position_size > dynamic_limit:
                        reason = f"Portfolio limit (${total_exposure:.0f}/${dynamic_limit:.0f} - full account)"
                        logger.info(f"{symbol}: {reason}")
                        if self.socketio:
                            self.socketio.emit('signal_rejected', {
                                'symbol': symbol,
                                'action': 'BUY',
                                'reason': reason,
                                'timestamp': datetime.now().isoformat()
                            })
                        return
                except Exception as e:
                    logger.warning(f"Could not calculate dynamic portfolio limit: {e}")
                    # Fallback: no limit check if balance fetch fails
                    pass
            
            # Risk manager validation DISABLED for aggressive trading
            # risk_manager = self.risk_managers[symbol]
            # validated_signal = risk_manager.validate_signal(
            #     signal=signal,
            #     klines=klines,
            #     current_balance=None
            # )
            # 
            # if not validated_signal:
            #     reason = "Risk manager rejection"
            #     logger.info(f"{symbol}: {reason}")
            #     if self.socketio:
            #         self.socketio.emit('signal_rejected', {
            #             'symbol': symbol,
            #             'action': signal['action'],
            #             'reason': reason,
            #             'timestamp': datetime.now().isoformat()
            #         })
            #     return
            
            # Use signal as-is (ML already validated it)
            validated_signal = signal
            
            # === REGIME FILTER: Avoid mid-range chop (TEMPORARILY DISABLED) ===
            # TODO: Re-enable after verifying RL agents work
            # if signal['action'] == 'BUY' and klines and len(klines) >= 24:
            #     from utils.atr_calculator import calculate_range_position, calculate_atr
            #     
            #     # Calculate where price sits in recent 24-period range
            #     range_pos = calculate_range_position(klines, lookback=24)
            #     
            #     # Calculate ATR for volatility check
            #     atr_pct = calculate_atr(klines, period=14)
            #     
            #     if range_pos is not None:
            #         # Only enter at extremes: near lows (<0.2) or near highs (>0.8)
            #         # Avoid mid-range chop (0.2-0.8) where price oscillates without follow-through
            #         if 0.2 <= range_pos <= 0.8:
            #             logger.info(
            #                 f"{symbol}: ❌ MID-RANGE CHOP - range_pos={range_pos:.2f} "
            #                 f"(need <0.2 or >0.8 for entry quality)"
            #             )
            #             if self.socketio:
            #                 self.socketio.emit('signal_rejected', {
            #                     'symbol': symbol,
            #                     'action': 'BUY',
            #                     'reason': f'Mid-range chop (pos={range_pos:.2f})',
            #                     'timestamp': datetime.now().isoformat()
            #                 })
            #             return
            #         else:
            #             logger.info(
            #                 f"{symbol}: ✅ REGIME OK - range_pos={range_pos:.2f} "
            #                 f"{'(near low, bounce play)' if range_pos < 0.2 else '(near high, breakout play)'}"
            #             )
            
            # === CONFIDENCE FILTER ===
            # Only trade 50-95% confidence (high confidence is overfit)
            # Exception: Mean reversion strategies can have >95% at extremes (RSI<30, RSI>70)
            ml_confidence = signal.get('indicators', {}).get('ml_confidence', 0)
            strategy_type = signal.get('indicators', {}).get('strategy', '')
            
            # Mean reversion gets higher confidence threshold (extremes are obvious)
            max_conf_threshold = 1.0 if strategy_type == 'mean_reversion' else self.max_confidence
            
            logger.info(f"{symbol}: Confidence check - type='{strategy_type}', conf={ml_confidence*100:.1f}%, threshold={max_conf_threshold*100:.1f}%")
            
            if ml_confidence > max_conf_threshold:
                logger.info(f"{symbol}: ❌ Confidence {ml_confidence*100:.0f}% TOO HIGH (overfit risk) - skipping")
                if self.socketio:
                    self.socketio.emit('signal_rejected', {
                        'symbol': symbol,
                        'action': 'BUY',
                        'reason': f'Confidence {ml_confidence*100:.0f}% too high (overfit)',
                        'timestamp': datetime.now().isoformat()
                    })
                return
            
            # === 15-SECOND ENTRY CONFIRMATION ===
            # Wait briefly and re-check price to avoid buying tops
            if signal['action'] == 'BUY':
                signal_price = signal['price']
                logger.debug(f"{symbol}: Signal @ ${signal_price:.2f}, waiting 15s for confirmation...")
                
                await asyncio.sleep(15)  # 15 second wait
                
                # Get current price
                try:
                    ticker = self.client.get_symbol_ticker(symbol=symbol)
                    current_price = float(ticker['price'])
                    price_change_pct = ((current_price - signal_price) / signal_price) * 100
                    
                    # Entry logic:
                    # - Dropped >1%: Skip (signal failed)
                    # - Otherwise: Execute (dip, flat, or rising = all good)
                    if price_change_pct < -1.0:
                        logger.info(f"{symbol}: ❌ Entry SKIPPED - price dropped {price_change_pct:.2f}% in 15s (signal failed)")
                        if self.socketio:
                            self.socketio.emit('signal_rejected', {
                                'symbol': symbol,
                                'action': 'BUY',
                                'reason': f'Price dropped {price_change_pct:.2f}% after signal',
                                'timestamp': datetime.now().isoformat()
                            })
                        return
                    
                    # Update signal with current price for better entry
                    validated_signal['price'] = current_price
                    logger.info(f"{symbol}: ✓ Entry confirmed - price {price_change_pct:+.2f}% @ ${current_price:.2f}")
                    
                except Exception as e:
                    logger.warning(f"{symbol}: Could not get current price for confirmation: {e}")
                    # Continue with original price if check fails
            
            # CRITICAL: Prevent duplicate orders - check if position already open
            if signal['action'] == 'BUY' and symbol in self.active_positions:
                logger.warning(f"{symbol}: ⚠️ BUY signal IGNORED - position already open (preventing duplicate)")
                return
            
            if signal['action'] == 'SELL' and symbol not in self.active_positions:
                logger.warning(f"{symbol}: ⚠️ SELL signal IGNORED - no position to close")
                return
            
            # Execute order with position size
            order_manager = self.order_managers[symbol]
            if signal['action'] == 'BUY':
                logger.info(f"{symbol}: Executing BUY with position_usdt=${position_size}")
                order = await order_manager.execute_order(
                    signal=validated_signal,
                    position_usdt=position_size
                )
            else:
                order = await order_manager.execute_order(validated_signal)
            
            if order:
                # Track position
                if signal['action'] == 'BUY':
                    # Detect if this is RL or ML strategy
                    is_rl = 'rl_action' in signal.get('indicators', {})
                    
                    # Extract entry fee and order type from order
                    entry_fee = order.get('total_fee_usdt', 0.0)
                    order_type = order.get('type', 'UNKNOWN')  # LIMIT or MARKET
                    
                    # Determine if maker or taker (LIMIT orders at bid/ask are maker)
                    is_maker = order_type == 'LIMIT'
                    
                    self.active_positions[symbol] = {
                        'entry_price': signal['price'],
                        'size': position_size,  # Use dynamic size
                        'remaining_size': position_size,  # Track remaining after partial exits
                        'timestamp': datetime.now().isoformat(),
                        'ml_confidence': ml_confidence,
                        'highest_price': signal['price'],  # Track highest price for trailing stop
                        'trailing_stop_activated': False,
                        'partial_exits': [],  # Track partial exits taken
                        'strategy': 'RL' if is_rl else 'ML',  # Tag strategy type
                        'entry_fee_usdt': entry_fee,  # Actual fee paid on entry
                        'entry_order_type': order_type,  # LIMIT or MARKET
                        'entry_is_maker': is_maker  # True if maker order
                    }
                    
                    # Save to persistent tracker
                    self.position_tracker.save_position(
                        symbol=symbol,
                        entry_price=signal['price'],
                        size=position_size,
                        ml_confidence=ml_confidence,
                        metadata={'timestamp': datetime.now().isoformat(), 'strategy': 'RL' if is_rl else 'ML'}
                    )
                    
                    logger.info(f"✅ {symbol} BUY executed at ${signal['price']:.2f} (${position_size:.0f} @ {ml_confidence*100:.0f}% conf) | Fee: ${entry_fee:.4f}")
                    
                    # Track position in portfolio risk manager
                    self.portfolio_risk.add_position(symbol, position_size, signal['price'], ml_confidence)
                    
                    # Register position with Real-time Monitor
                    if self.rtm and order:
                        try:
                            # Get actual fill quantity from order
                            fill_qty = float(order.get('executedQty', 0))
                            if fill_qty == 0 and signal['price'] > 0:
                                # Fallback: calculate from position size
                                fill_qty = position_size / signal['price']
                            
                            if fill_qty > 0:
                                # Pass entry fee to RTM so it can adjust break-even
                                await self.rtm.register_position(symbol, signal['price'], fill_qty, entry_fee)
                                logger.debug(f"RTM registered {symbol}: {fill_qty:.8f} @ ${signal['price']:.2f}")
                            else:
                                logger.warning(f"Cannot register {symbol} with RTM: fill_qty is zero")
                        except Exception as e:
                            logger.error(f"Failed to register position with RTM: {e}", exc_info=True)
                    
                    # Send Telegram alert
                    self.telegram.send_trade_alert({
                        'symbol': symbol,
                        'action': 'BUY',
                        'price': signal['price'],
                        'size': position_size,
                        'ml_confidence': ml_confidence,
                        'reason': signal.get('reason', 'ML signal')
                    })
                    
                    if self.socketio:
                        self.socketio.emit('trade_executed', {
                            'symbol': symbol,
                            'action': 'BUY',
                            'price': signal['price'],
                            'size': position_size,
                            'confidence': ml_confidence,
                            'timestamp': datetime.now().isoformat()
                        })
                elif signal['action'] == 'SELL' and symbol in self.active_positions:
                    position = self.active_positions.pop(symbol)
                    
                    # Remove from persistent tracker
                    self.position_tracker.remove_position(symbol)
                    
                    # Extract exit fee from order
                    exit_fee = order.get('total_fee_usdt', 0.0)
                    entry_fee = position.get('entry_fee_usdt', 0.0)
                    total_fees = entry_fee + exit_fee
                    
                    # Calculate P&L (gross and net)
                    gross_pnl_usd = (signal['price'] - position['entry_price']) * (position['size'] / position['entry_price'])
                    net_pnl_usd = gross_pnl_usd - total_fees
                    gross_pnl_pct = (signal['price'] - position['entry_price']) / position['entry_price'] * 100
                    net_pnl_pct = (net_pnl_usd / position['size']) * 100
                    
                    # Use net P&L for all reporting
                    pnl_pct = net_pnl_pct
                    pnl_usd = net_pnl_usd
                    
                    # Unregister from Real-time Monitor
                    if self.rtm:
                        try:
                            await self.rtm.unregister_position(symbol)
                        except Exception as e:
                            logger.error(f"Failed to unregister position from RTM: {e}")
                    
                    # Remove from portfolio risk manager
                    self.portfolio_risk.remove_position(symbol)
                    
                    # Update model monitor with actual outcome
                    actual_outcome = 1 if pnl_pct > 0 else 0
                    self.model_monitor.update_actual_outcome(symbol, actual_outcome)
                    
                    # Check for model decay
                    decay_check = self.model_monitor.check_decay(symbol)
                    if decay_check['needs_retrain']:
                        logger.warning(f"📉 Model decay detected for {symbol}: {decay_check['reason']}")
                        self.telegram.send_error_alert(
                            f"⚠️ Model Decay Alert\n\n"
                            f"Symbol: {symbol}\n"
                            f"Reason: {decay_check['reason']}\n\n"
                            f"Accuracy: {decay_check['metrics'].get('accuracy', 0):.2%}\n"
                            f"Hit Rate: {decay_check['metrics'].get('hit_rate', 0):.2%}\n\n"
                            f"Recommendation: Retrain model for {symbol}"
                        )
                    
                    # Record trade in performance tracker
                    self.performance_tracker.record_trade({
                        'symbol': symbol,
                        'action': 'SELL',
                        'entry_price': position['entry_price'],
                        'exit_price': signal['price'],
                        'size': position['size'],
                        'pnl': pnl_usd,
                        'pnl_pct': pnl_pct,
                        'ml_confidence': position.get('ml_confidence', 0),
                        'entry_time': position['timestamp'],
                        'exit_time': datetime.now().isoformat(),
                        'reason': signal.get('reason', 'ML exit')
                    })
                    
                    # Log to TradeLogger for Learning Analytics (with fees)
                    trade_data = {
                        'symbol': symbol,
                        'entry_price': position['entry_price'],
                        'exit_price': signal['price'],
                        'position_size': position['size'],
                        'profit_usd': pnl_usd,  # Net P&L after fees
                        'profit_pct': pnl_pct,  # Net P&L% after fees
                        'fees_paid': total_fees,  # Total fees (entry + exit)
                        'ml_confidence': position.get('ml_confidence', 0),
                        'entry_time': position['timestamp'],
                        'exit_time': datetime.now().isoformat(),
                        'exit_reason': signal.get('reason', 'RL/ML exit')
                    }
                    self.trade_logger.log_trade(trade_data)
                    
                    # Online RL learning from this trade
                    if position.get('strategy') == 'RL':
                        self.rl_online_learner.log_trade_experience(trade_data)
                    
                    # Update adaptive Kelly with trade result
                    risk_manager = self.risk_managers[symbol]
                    risk_manager.update_recent_performance(won=(pnl_pct > 0))
                    
                    # Send Telegram close alert
                    self.telegram.send_position_close_alert({
                        'symbol': symbol,
                        'entry_price': position['entry_price'],
                        'exit_price': signal['price'],
                        'pnl': pnl_usd,
                        'pnl_pct': pnl_pct,
                        'reason': signal.get('reason', 'ML exit')
                    })
                    
                    logger.info(f"✅ {symbol} SELL executed at ${signal['price']:.2f} (P&L: {pnl_pct:+.2f}%)")
        
        except Exception as e:
            logger.error(f"Error executing signal for {symbol}: {e}")
            
            # Auto-blacklist symbols that return -2010 (not permitted)
            if 'code=-2010' in str(e) or 'not permitted' in str(e).lower():
                if symbol not in self.blacklisted_symbols:
                    self.blacklisted_symbols.add(symbol)
                    logger.warning(f"🚫 Auto-blacklisted {symbol} - not permitted on this account")
                    
                    # Remove strategy to prevent future signals
                    if symbol in self.strategies:
                        del self.strategies[symbol]
                    if symbol in self.risk_managers:
                        del self.risk_managers[symbol]
                    if symbol in self.order_managers:
                        del self.order_managers[symbol]
    
    async def _on_rtm_position_closed(self, exit_data: dict):
        """Callback when RTM closes a position - log trade and track for re-entry window"""
        symbol = exit_data['symbol']
        exit_price = exit_data['exit_price']
        reason = exit_data['reason']
        exit_fee = exit_data.get('exit_fee_usdt', 0.0)
        
        # Get position data before removing
        if symbol in self.active_positions:
            position = self.active_positions.pop(symbol)
            
            # Get entry fee from position
            entry_fee = position.get('entry_fee_usdt', 0.0)
            total_fees = entry_fee + exit_fee
            
            # Calculate P&L (gross and net)
            gross_pnl_usd = (exit_price - position['entry_price']) * (position['size'] / position['entry_price'])
            net_pnl_usd = gross_pnl_usd - total_fees
            gross_pnl_pct = ((exit_price - position['entry_price']) / position['entry_price']) * 100
            net_pnl_pct = (net_pnl_usd / position['size']) * 100
            
            # Use net P&L for all reporting
            pnl_pct = net_pnl_pct
            pnl_usd = net_pnl_usd
            
            logger.info(f"📤 {symbol} RTM exit | Gross: {gross_pnl_pct:+.2f}% | Fees: ${total_fees:.4f} | Net: {net_pnl_pct:+.2f}% (${net_pnl_usd:+.2f})")
            
            # Record trade in performance tracker
            self.performance_tracker.record_trade({
                'symbol': symbol,
                'action': 'SELL',
                'entry_price': position['entry_price'],
                'exit_price': exit_price,
                'size': position['size'],
                'pnl': pnl_usd,
                'pnl_pct': pnl_pct,
                'ml_confidence': position.get('ml_confidence', 0),
                'entry_time': position['timestamp'],
                'exit_time': datetime.now().isoformat(),
                'reason': f'RTM: {reason}'
            })
            
            # Log to TradeLogger for Learning Analytics (with fees)
            trade_data = {
                'symbol': symbol,
                'entry_price': position['entry_price'],
                'exit_price': exit_price,
                'position_size': position['size'],
                'profit_usd': pnl_usd,  # Net P&L after fees
                'profit_pct': pnl_pct,  # Net P&L% after fees
                'fees_paid': total_fees,  # Total fees (entry + exit)
                'ml_confidence': position.get('ml_confidence', 0),
                'entry_time': position['timestamp'],
                'exit_time': datetime.now().isoformat(),
                'exit_reason': f'RTM: {reason}'
            }
            self.trade_logger.log_trade(trade_data)
            
            # Online RL learning from this trade
            if position.get('strategy') == 'RL':
                self.rl_online_learner.log_trade_experience(trade_data)
            
            # Send Telegram close alert
            self.telegram.send_position_close_alert({
                'symbol': symbol,
                'entry_price': position['entry_price'],
                'exit_price': exit_price,
                'pnl': pnl_usd,
                'pnl_pct': pnl_pct,
                'reason': reason
            })
            
            # Remove from portfolio risk manager
            self.portfolio_risk.remove_position(symbol)
            
            # Update model monitor with actual outcome
            actual_outcome = 1 if pnl_pct > 0 else 0
            self.model_monitor.update_actual_outcome(symbol, actual_outcome)
            
            # Update adaptive Kelly
            if symbol in self.risk_managers:
                risk_manager = self.risk_managers[symbol]
                risk_manager.update_recent_performance(won=(pnl_pct > 0))
            
            logger.info(f"📤 {symbol} RTM exit logged: P&L {pnl_pct:+.2f}% (${pnl_usd:+.2f})")
        
        # Notify strategy about exit (triggers cooldown)
        if symbol in self.strategies:
            strategy = self.strategies[symbol]
            if hasattr(strategy, 'last_exit_time'):
                strategy.last_exit_time[symbol] = datetime.now()
                logger.debug(f"⏱️ {symbol}: Strategy cooldown activated (2 min)")
        
        self.recently_exited[symbol] = datetime.now()
        logger.info(f"🕒 {symbol} tracked as recently exited via RTM (2 min monitoring window)")
    
    async def check_trailing_stops(self):
        """Check trailing stops for all open positions (LEGACY - RTM supersedes this)"""
        for symbol, position in list(self.active_positions.items()):
            try:
                # Get current price
                ticker = self.client.get_symbol_ticker(symbol=symbol)
                current_price = float(ticker['price'])
                entry_price = position['entry_price']
                
                # Update highest price
                if current_price > position['highest_price']:
                    position['highest_price'] = current_price
                
                # Calculate profit
                profit_pct = ((current_price - entry_price) / entry_price) * 100
                remaining_size = position.get('remaining_size', position['size'])
                
                # AGGRESSIVE SCALPING - Quick profit taking for 5m timeframe
                partial_exits = position.get('partial_exits', [])
                
                # Exit 60% at +0.15% profit (first target)
                if profit_pct >= 0.15 and '0.15' not in partial_exits:
                    exit_amount = position['size'] * 0.6
                    if exit_amount > 0:
                        logger.info(f"💰 {symbol}: Taking 60% profit at +{profit_pct:.2f}% (${exit_amount:.0f})")
                        # TODO: Execute partial sell order here
                        position['remaining_size'] = remaining_size - exit_amount
                        position['partial_exits'].append('0.15')
                
                # Exit remaining 40% at +0.3% profit (second target)
                if profit_pct >= 0.3 and '0.3' not in partial_exits:
                    exit_amount = remaining_size  # Close remaining position
                    if exit_amount > 0:
                        logger.info(f"💎 {symbol}: Taking final 40% profit at +{profit_pct:.2f}% (${exit_amount:.0f})")
                        # Full exit at this level
                        position['remaining_size'] = 0
                        position['partial_exits'].append('0.3')
                        # Will trigger full close below
                
                # AGGRESSIVE TRAILING STOP: Very tight for 5m scalping
                if not position['trailing_stop_activated']:
                    # Activate trailing stop immediately
                    position['trailing_stop_activated'] = True
                    position['initial_stop'] = entry_price * 0.998  # Start at -0.2% stop
                    logger.debug(f"🔒 {symbol}: Aggressive trailing stop active")
                
                # Ultra-tight trailing for scalping
                if profit_pct < 0.20:
                    # Very tight stop loss for scalping
                    stop_price = entry_price * 0.998  # -0.2% stop loss
                elif profit_pct < 0.15:
                    # Move past fees at 0.20% (covers 0.15% round-trip fees)
                    stop_price = entry_price * 1.0005  # Lock in +0.05% after fees
                    if profit_pct >= 0.20 and not position.get('break_even_locked'):
                        position['break_even_locked'] = True
                        logger.info(f"🔒 {symbol}: Break-even locked at +{profit_pct:.2f}%")
                elif profit_pct < 0.3:
                    # Lock in 70% of gains between 0.15% and 0.3%
                    stop_price = entry_price + (current_price - entry_price) * 0.7
                else:
                    # Lock in 80% of gains above 0.3%
                    stop_price = entry_price + (position['highest_price'] - entry_price) * 0.8
                
                # Check if stop triggered
                if current_price <= stop_price:
                        logger.info(f"🛑 {symbol}: Trailing stop triggered! Stop ${stop_price:.2f} → Current ${current_price:.2f} (P&L: {profit_pct:+.2f}%)")
                        
                        # Create SELL signal and execute
                        strategy = self.strategies[symbol]
                        sell_signal = {
                            'action': 'SELL',
                            'price': current_price,
                            'reason': 'Trailing stop triggered',
                            'indicators': {}
                        }
                        
                        # Execute SELL order
                        order_manager = self.order_managers[symbol]
                        order = await order_manager.execute_order(sell_signal)
                        
                        if order:
                            position = self.active_positions.pop(symbol)
                            pnl_usd = (current_price - position['entry_price']) * (position['size'] / position['entry_price'])
                            
                            # Record trade
                            self.performance_tracker.record_trade({
                                'symbol': symbol,
                                'action': 'SELL',
                                'entry_price': position['entry_price'],
                                'exit_price': current_price,
                                'size': position['size'],
                                'pnl': pnl_usd,
                                'pnl_pct': profit_pct,
                                'ml_confidence': position.get('ml_confidence', 0),
                                'entry_time': position['timestamp'],
                                'exit_time': datetime.now().isoformat(),
                                'reason': 'Trailing stop'
                            })
                            
                            # Track recently exited for 2 min window (watch for bounce/re-entry)
                            self.recently_exited[symbol] = datetime.now()
                            logger.info(f"🕒 {symbol} tracked as recently exited (2 min monitoring window)")
                            
                            logger.info(f"✅ {symbol} SELL executed via trailing stop (P&L: +{profit_pct:.2f}%)")
                            if self.socketio:
                                self.socketio.emit('trade_executed', {
                                    'symbol': symbol,
                                    'action': 'SELL',
                                    'price': current_price,
                                    'profit': profit_pct,
                                    'reason': 'Trailing stop',
                                    'timestamp': datetime.now().isoformat()
                                })
            
            except Exception as e:
                logger.error(f"Error checking trailing stop for {symbol}: {e}")
    
    async def trading_cycle(self):
        """Run one complete trading cycle with intelligent scanning priority"""
        logger.info(f"⚡ TRADING_CYCLE CALLED - Strategies loaded: {len(self.strategies)} pairs")
        cycle_start = datetime.now()
        
        # Generate unique cycle ID
        self.current_cycle_id = str(uuid.uuid4())
        
        # Get list of all available pairs
        all_symbols = list(self.strategies.keys())
        total_pairs = len(all_symbols)
        timeframe = self.config.timeframe
        
        # Clean up recently_exited dict (remove pairs older than 2 mins - aggressive re-entry)
        now = datetime.now()
        expired = [sym for sym, exit_time in self.recently_exited.items() 
                   if (now - exit_time).total_seconds() > 120]  # 2 mins = 120s (reduced from 15)
        for sym in expired:
            del self.recently_exited[sym]
            logger.debug(f"🕒 {sym} no longer recently exited (2 min cooldown passed)")
        
        # ===== INTELLIGENT SCANNING PRIORITY =====
        # Priority 1: ALWAYS scan open positions (must check exits every cycle)
        priority_symbols = list(self.active_positions.keys())
        
        # Priority 2: Recently exited positions (2 min cooldown - monitor but DON'T re-enter yet)
        recently_exited_symbols = [sym for sym in self.recently_exited.keys() 
                                   if sym not in priority_symbols]
        # DON'T add to priority - let them cool down briefly to avoid immediate churn
        # priority_symbols.extend(recently_exited_symbols)
        
        # Priority 3: Major pairs (BTC, ETH) - always include for high-value signals
        major_pairs = ['BTCUSDT', 'ETHUSDT']
        for major in major_pairs:
            if major in all_symbols and major not in priority_symbols:
                priority_symbols.append(major)
        
        # Scan pairs in batches of 15 for balanced coverage
        max_pairs_per_cycle = 15  # Balanced: good coverage while staying responsive
        
        # Always include priority pairs first
        priority_count = len(priority_symbols)
        remaining_slots = max_pairs_per_cycle - priority_count
        
        if remaining_slots > 0:
            # Get non-priority pairs sorted by ML model accuracy (best first)
            other_pairs = [s for s in all_symbols if s not in priority_symbols]
            
            # Sort by accuracy (high to low) - pairs with best models get scanned first
            other_pairs.sort(key=lambda s: self.model_accuracies.get(s, 0), reverse=True)
            
            # Rotate through all pairs (not just top N)
            if self.all_pairs_rotation_idx >= len(other_pairs):
                self.all_pairs_rotation_idx = 0
            
            # Take batch starting from rotation index
            batch = other_pairs[self.all_pairs_rotation_idx:self.all_pairs_rotation_idx + remaining_slots]
            
            # If batch is smaller than remaining_slots, wrap around
            if len(batch) < remaining_slots and len(other_pairs) > 0:
                wrap_count = remaining_slots - len(batch)
                batch.extend(other_pairs[:wrap_count])
                self.all_pairs_rotation_idx = wrap_count
            else:
                self.all_pairs_rotation_idx += len(batch)
            
            symbols_to_analyze = priority_symbols + batch
            scan_mode = f"ROTATING BATCH ({len(batch)} pairs, idx={self.all_pairs_rotation_idx}/{len(other_pairs)})"
        else:
            # Too many priority symbols - just scan those
            symbols_to_analyze = priority_symbols[:max_pairs_per_cycle]
            scan_mode = "PRIORITY ONLY (overflow)"
        
        pairs_this_cycle = len(symbols_to_analyze)
        priority_count = len(priority_symbols)
        
        # Log cycle start with scan mode
        logger.info(f"🔄 Cycle [{scan_mode}] - Analyzing {pairs_this_cycle} pairs "
                   f"({priority_count} priority: {len(self.active_positions)} open + {len(recently_exited_symbols)} recent exits)")
        
        # Emit cycle_start event
        if self.socketio:
            self.socketio.emit('cycle_start', {
                'cycle_id': self.current_cycle_id,
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'timeframe': timeframe,
                'pairs': symbols_to_analyze,  # Only pairs being analyzed this cycle
                'total_pairs': pairs_this_cycle,  # Show actual pairs this cycle
                'dry_run': self.config.dry_run
            })
        
        # Check trailing stops for open positions (LEGACY - superseded by RTM)
        # Only runs if RTM is disabled
        if self.active_positions and not self.rtm:
            await self.check_trailing_stops()
        
        # Track analysis stats
        analyzed_count = 0
        error_count = 0
        signal_counts = {'BUY': 0, 'SELL': 0, 'HOLD': 0}
        
        for idx, symbol in enumerate(symbols_to_analyze):
            pair_start = datetime.now()
            logger.debug(f"  🔍 [{idx+1}/{len(symbols_to_analyze)}] Analyzing {symbol} ({timeframe})")
            
            try:
                # Yield to event loop BEFORE each analysis so RTM can run
                await asyncio.sleep(0.1)  # 100ms pause for RTM
                
                # Analyze with ultra-aggressive timeout (2s max per pair)
                result = await asyncio.wait_for(
                    self.analyze_pair(symbol, timeframe),
                    timeout=2.0
                )
                
                signal, klines = result if result else (None, None)
                analyzed_count += 1
                
                # Determine signal type
                signal_type = signal['action'] if signal else 'HOLD'
                signal_counts[signal_type] = signal_counts.get(signal_type, 0) + 1
                
                # Emit pair_analysis_complete event
                if self.socketio:
                    elapsed_ms = int((datetime.now() - pair_start).total_seconds() * 1000)
                    self.socketio.emit('pair_analysis_complete', {
                        'cycle_id': self.current_cycle_id,
                        'timestamp': datetime.utcnow().isoformat() + 'Z',
                        'symbol': symbol,
                        'price': signal.get('price', 0) if signal else 0,
                        'confidence': signal.get('indicators', {}).get('ml_confidence', 0) if signal else 0,
                        'signal': signal_type,
                        'reason': signal.get('reason', 'No signal') if signal else 'No signal',
                        'elapsed_ms': elapsed_ms,
                        'analyzed_index': idx + 1,
                        'total_pairs': pairs_this_cycle,
                        'progress': (idx + 1) / pairs_this_cycle
                    })
                
                # Execute signal if present
                if signal and klines:
                    logger.info(f"📈 {symbol}: {signal['action']} signal @ ${signal['price']:.2f} - {signal['reason']}")
                    await self.execute_signal(symbol, signal, klines)
                else:
                    logger.debug(f"  ⏸  {symbol}: No signal")
                    
            except asyncio.TimeoutError:
                logger.warning(f"⏱️  [{symbol}] Analysis timed out after 2s - skipping")
                error_count += 1
                analyzed_count += 1
                # Yield to event loop after timeout
                await asyncio.sleep(0)
                
                if self.socketio:
                    self.socketio.emit('pair_analysis_complete', {
                        'cycle_id': self.current_cycle_id,
                        'timestamp': datetime.utcnow().isoformat() + 'Z',
                        'symbol': symbol,
                        'signal': 'ERROR',
                        'reason': 'Analysis timeout',
                        'error': True,
                        'analyzed_index': idx + 1,
                        'total_pairs': pairs_this_cycle,
                        'progress': (idx + 1) / pairs_this_cycle
                    })
                    
            except Exception as e:
                logger.error(f"❌ [{symbol}] Analysis failed: {e}", exc_info=True)
                error_count += 1
                analyzed_count += 1
                
                if self.socketio:
                    self.socketio.emit('pair_analysis_complete', {
                        'cycle_id': self.current_cycle_id,
                        'timestamp': datetime.utcnow().isoformat() + 'Z',
                        'symbol': symbol,
                        'signal': 'ERROR',
                        'reason': str(e),
                        'error': True,
                        'analyzed_index': idx + 1,
                        'total_pairs': pairs_this_cycle,
                        'progress': (idx + 1) / pairs_this_cycle
                    })
        
        # === RUN MOMENTUM SCANNER (in parallel with ML) ===
        momentum_signals = []
        if self.momentum_scanner:
            try:
                logger.debug("🔍 Running momentum scanner...")
                momentum_signals = await self.momentum_scanner.scan()
                
                if momentum_signals:
                    logger.info(f"🚀 Momentum scanner found {len(momentum_signals)} signals")
                    
                    # Process momentum signals
                    for signal in momentum_signals:
                        await self.handle_momentum_signal(signal)
            
            except Exception as e:
                logger.error(f"Momentum scanner failed: {e}", exc_info=True)
        
        # Calculate cycle duration
        cycle_duration_ms = int((datetime.now() - cycle_start).total_seconds() * 1000)
        cycle_time_s = cycle_duration_ms / 1000
        
        # Log summary
        signals_found = signal_counts.get('BUY', 0) + signal_counts.get('SELL', 0)
        if signals_found > 0:
            logger.info(f"✅ Cycle complete: {signals_found} ML signals in {cycle_time_s:.2f}s")
        else:
            logger.debug(f"✅ Cycle complete: No ML signals in {cycle_time_s:.2f}s")
        
        if momentum_signals:
            logger.info(f"✅ Momentum: {len(momentum_signals)} signals detected")
        
        # Log portfolio status
        if self.active_positions:
            logger.info(f"📊 Portfolio: {len(self.active_positions)} positions, "
                       f"${sum(p['size'] for p in self.active_positions.values()):.0f} exposure")
        
        # Emit cycle_complete event with detailed stats
        if self.socketio:
            self.socketio.emit('cycle_complete', {
                'cycle_id': self.current_cycle_id,
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'total_pairs': total_pairs,
                'analyzed': analyzed_count,
                'duration_ms': cycle_duration_ms,
                'signals': signal_counts,
                'errors': error_count,
                'positions': len(self.active_positions),
                'dry_run': self.config.dry_run
            })
    
    async def handle_momentum_signal(self, signal: Dict):
        """
        Handle momentum scanner signal: Telegram alert or auto-trade
        
        Args:
            signal: Momentum signal dict from scanner
        """
        try:
            symbol = signal['symbol']
            filters_passed = signal['filters_passed']
            momentum_score = signal['momentum_score']
            
            # Check if we can open a momentum position
            can_open, reason = self.momentum_risk_manager.can_open_momentum_position(self.active_positions)
            
            if not can_open:
                logger.info(f"{symbol}: Momentum signal blocked - {reason}")
                return
            
            # Determine action based on filters passed
            if filters_passed >= self.config.momentum_trade_threshold and self.config.momentum_auto_trade:
                # AUTO-TRADE: 10/10 filters
                logger.info(f"🚀 {symbol}: MOMENTUM AUTO-TRADE (filters {filters_passed}/10, score {momentum_score:.1f}/10)")
                await self.execute_momentum_trade(signal)
            
            elif filters_passed >= self.config.momentum_alert_threshold:
                # ALERT: 7-9/10 filters
                logger.info(f"🚨 {symbol}: MOMENTUM ALERT (filters {filters_passed}/10, score {momentum_score:.1f}/10)")
                self.send_momentum_alert(signal)
            
            # Emit to dashboard
            if self.socketio:
                self.socketio.emit('momentum_signal', {
                    'symbol': symbol,
                    'filters_passed': filters_passed,
                    'momentum_score': momentum_score,
                    'price': signal['current_price'],
                    'entry': signal['recommended_entry'],
                    'stop_loss': signal['stop_loss'],
                    'take_profit': signal['take_profit'],
                    'risk_level': signal['risk_level'],
                    'auto_trade': filters_passed >= self.config.momentum_trade_threshold and self.config.momentum_auto_trade,
                    'timestamp': datetime.now().isoformat()
                })
        
        except Exception as e:
            logger.error(f"Error handling momentum signal: {e}", exc_info=True)
    
    def send_momentum_alert(self, signal: Dict):
        """Send Telegram alert for momentum signal"""
        try:
            symbol = signal['symbol']
            score = signal['momentum_score']
            price = signal['current_price']
            entry = signal['recommended_entry']
            stop_loss = signal['stop_loss']
            take_profit = signal['take_profit']
            filters_passed = signal['filters_passed']
            risk_level = signal['risk_level']
            
            # Calculate price changes from indicators
            indicators = signal.get('indicators', {})
            price_change_1h = indicators.get('price_change_1h', 0)
            vol_ratio = indicators.get('vol_ratio_5m', 0)
            
            # Format message
            message = (
                f"🚀 <b>MOMENTUM ALERT: {symbol}</b>\n\n"
                f"📊 Momentum Score: {score:.1f}/10\n"
                f"💰 Price: ${price:.4f} ({price_change_1h:+.1f}% 1h)\n"
                f"📈 Volume Surge: {vol_ratio:.1f}x average\n"
                f"🎯 Entry: ${entry:.4f} (on pullback)\n"
                f"🛡️ Stop: ${stop_loss:.4f} (-{((entry-stop_loss)/entry*100):.1f}%)\n"
                f"🎁 Target: ${take_profit:.4f} (+{((take_profit-entry)/entry*100):.1f}%)\n\n"
                f"✅ Filters Passed: {filters_passed}/10\n"
                f"⚠️ Risk: {risk_level}\n\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            
            self.telegram.send_message(message)
            logger.info(f"📤 Telegram alert sent for {symbol}")
        
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
    
    async def execute_momentum_trade(self, signal: Dict):
        """
        Execute momentum trade (10/10 filters only)
        
        Args:
            signal: Momentum signal dict
        """
        try:
            symbol = signal['symbol']
            
            # Check if position already exists
            if symbol in self.active_positions:
                logger.warning(f"{symbol}: Momentum trade blocked - position already open")
                return
            
            # Get account balance
            account = self.client.get_account()
            usdt_free = float([b for b in account['balances'] if b['asset'] == 'USDT'][0]['free'])
            
            # Calculate position size
            entry_price = signal['recommended_entry']
            position_usdt = self.momentum_risk_manager.size_position(entry_price, usdt_free)
            
            if position_usdt == 0:
                logger.warning(f"{symbol}: Position size too small, skipping")
                return
            
            # Get or create order manager for this symbol
            if symbol not in self.order_managers:
                from utils.order_manager import OrderManager
                self.order_managers[symbol] = OrderManager(
                    client=self.client,
                    config=self.config,
                    symbol=symbol
                )
            
            order_manager = self.order_managers[symbol]
            
            # Create order signal format
            order_signal = {
                'action': 'BUY',
                'price': entry_price,
                'reason': f"Momentum breakout (score {signal['momentum_score']:.1f}/10)",
                'indicators': signal['indicators']
            }
            
            # Execute order
            if self.config.dry_run:
                logger.info(f"[DRY RUN] Would execute momentum BUY for {symbol}: ${position_usdt:.2f} @ ${entry_price:.4f}")
            else:
                order = await order_manager.execute_order(
                    signal=order_signal,
                    position_usdt=position_usdt
                )
                
                if order:
                    # Track position with MOMENTUM tag
                    stop_loss, take_profit = self.momentum_risk_manager.stops_targets(entry_price)
                    
                    self.active_positions[symbol] = {
                        'entry_price': entry_price,
                        'size': position_usdt,
                        'quantity': position_usdt / entry_price,
                        'entry_time': datetime.now(),
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'strategy_type': 'MOMENTUM',  # Tag as momentum trade
                        'momentum_score': signal['momentum_score'],
                        'filters_passed': signal['filters_passed'],
                        'peak_price': entry_price  # For trailing stops
                    }
                    
                    logger.info(
                        f"✅ {symbol}: Momentum position opened - ${position_usdt:.2f} @ ${entry_price:.4f} "
                        f"(SL: ${stop_loss:.4f}, TP: ${take_profit:.4f})"
                    )
                    
                    # Send Telegram notification
                    self.telegram.send_message(
                        f"✅ <b>MOMENTUM TRADE EXECUTED</b>\n\n"
                        f"Symbol: {symbol}\n"
                        f"Entry: ${entry_price:.4f}\n"
                        f"Size: ${position_usdt:.2f}\n"
                        f"Stop Loss: ${stop_loss:.4f}\n"
                        f"Take Profit: ${take_profit:.4f}\n"
                        f"Score: {signal['momentum_score']:.1f}/10"
                    )
        
        except Exception as e:
            logger.error(f"Failed to execute momentum trade: {e}", exc_info=True)
    
    async def start(self):
        """Start the multi-pair trading bot"""
        logger.info("=" * 60)
        logger.info("Multi-Pair Trading Bot Starting")
        logger.info("=" * 60)
        
        # Discover available models
        models = self.discover_models()
        
        if not models:
            logger.error("No trained models found! Run auto-trainer first.")
            return
        
        # If no models found, use top liquid pairs with scalping strategy
        if not models:
            logger.warning("No trained models found - using scalping strategy on top pairs")
            
            # Get top liquid pairs
            try:
                tickers = self.client.get_ticker()
                top_pairs = []
                
                for ticker in tickers:
                    if ticker['symbol'].endswith('USDT'):
                        try:
                            volume = float(ticker['quoteVolume'])
                            if volume > 5_000_000:  # $5M+ volume
                                top_pairs.append((ticker['symbol'], volume))
                        except:
                            continue
                
                top_pairs.sort(key=lambda x: x[1], reverse=True)
                
                # Use top 5 most liquid pairs
                models = [{
                    'symbol': pair[0],
                    'timeframe': '1m',  # Fast 1-minute scalping
                    'accuracy': 0,
                    'f1_score': 0,
                    'model_type': 'scalping'
                } for pair in top_pairs[:5]]
                
                logger.info(f"Selected top 5 liquid pairs for scalping: {[m['symbol'] for m in models]}")
            except Exception as e:
                logger.error(f"Failed to get top pairs: {e}")
                # Fallback to popular pairs
                models = [{
                    'symbol': sym,
                    'timeframe': '1m',
                    'accuracy': 0,
                    'f1_score': 0,
                    'model_type': 'scalping'
                } for sym in ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']]
        
        # Filter models by minimum accuracy (only for ML models)
        min_accuracy = 0.55  # 55% minimum - relaxed for mean reversion
        good_models = [m for m in models if m.get('model_type') == 'scalping' or m['accuracy'] >= min_accuracy]
        
        if not good_models:
            logger.warning(f"No good models - using all discovered pairs")
            good_models = models  # Use ALL models, not just first 6
        
        # Filter out symbols not tradeable on this account (prevent -2010 errors)
        logger.info(f"Checking {len(good_models)} pairs for account permissions...")
        tradeable_models = []
        for model in good_models:
            if self.is_symbol_tradeable(model['symbol']):
                tradeable_models.append(model)
        
        skipped = len(good_models) - len(tradeable_models)
        if skipped > 0:
            logger.warning(f"⚠️  Skipped {skipped} pairs due to account restrictions")
        
        good_models = tradeable_models
        
        if not good_models:
            logger.error("❌ No tradeable pairs remaining after filtering!")
            return
        
        logger.info(f"Trading {len(good_models)} pairs with models:")
        for model in good_models:
            logger.info(f"  • {model['symbol']}: {model['accuracy']*100:.1f}% accuracy")
        
        # Initialize trading for each pair and store model quality
        # Skip blacklisted symbols
        for model in good_models:
            if model['symbol'] in self.blacklisted_symbols:
                logger.warning(f"⚠️  Skipping blacklisted symbol: {model['symbol']}")
                continue
            self.initialize_pair(model['symbol'], model['timeframe'])
            self.model_accuracies[model['symbol']] = model.get('accuracy', 0)
        
        # Initialize portfolio risk manager with starting balance
        try:
            account = self.client.get_account()
            usdt_balance = float([b for b in account['balances'] if b['asset'] == 'USDT'][0]['free'])
            total_balance = float([b for b in account['balances'] if b['asset'] == 'USDT'][0]['free']) + \
                          float([b for b in account['balances'] if b['asset'] == 'USDT'][0].get('locked', 0))
            
            self.portfolio_risk.set_starting_balance(usdt_balance)
            logger.info(f"Portfolio risk manager initialized with balance: ${usdt_balance:.2f} (total with locked: ${total_balance:.2f})")
        except Exception as e:
            logger.warning(f"Could not fetch account balance: {e}")
            self.portfolio_risk.set_starting_balance(400)  # Default testnet balance
            logger.info("Portfolio risk manager initialized with default balance: $400")
        
        # RECONCILE EXISTING POSITIONS
        logger.info("Checking for existing open positions...")
        try:
            # Get all open orders
            open_orders = self.client.get_open_orders()
            
            if open_orders:
                logger.warning(f"Found {len(open_orders)} open orders on startup")
                for order in open_orders:
                    symbol = order['symbol']
                    side = order['side']
                    order_type = order['type']
                    logger.info(f"  - {symbol}: {side} {order_type} order (ID: {order['orderId']})")
                
                # Ask user what to do (for now, just log)
                logger.warning("⚠️  EXISTING ORDERS DETECTED - You may want to manually close or manage these")
                self.telegram.send_error_alert(
                    f"⚠️ Bot Startup Warning\n\n"
                    f"Found {len(open_orders)} existing open orders:\n" +
                    "\n".join([f"- {o['symbol']}: {o['side']} {o['type']}" for o in open_orders[:5]]) +
                    "\n\nReview these positions before continuing."
                )
            else:
                logger.info("No existing open orders found")
        except Exception as e:
            logger.error(f"Error checking existing orders: {e}")
        
        # LOAD POSITIONS FROM PERSISTENT TRACKER FIRST
        logger.info("📂 Loading positions from persistent tracker...")
        tracked_positions = self.position_tracker.get_all_positions()
        if tracked_positions:
            logger.info(f"Found {len(tracked_positions)} tracked positions from previous session")
            for symbol, tracked in tracked_positions.items():
                logger.info(f"  {symbol}: entry=${tracked['entry_price']:.2f}, size=${tracked['size']:.2f}")
        
        # CHECK FOR EXISTING HOLDINGS (actual positions)
        logger.info("Scanning account for existing holdings...")
        try:
            account = self.client.get_account()
            holdings_found = 0
            
            for balance in account['balances']:
                asset = balance['asset']
                free = float(balance['free'])
                locked = float(balance.get('locked', 0))
                total = free + locked
                
                # Skip USDT and zero/tiny balances
                if asset == 'USDT' or total < 0.0001:
                    continue
                
                # Found a non-USDT holding - check if it's a USDT pair
                symbol = asset + 'USDT'
                
                try:
                    # Get current price to calculate USD value
                    ticker = self.client.get_symbol_ticker(symbol=symbol)
                    current_price = float(ticker['price'])
                    position_value = total * current_price
                    
                    # Only track positions worth > $5 (ignore dust) and not blacklisted
                    if position_value > 5.0 and symbol not in self.blacklisted_symbols:
                        holdings_found += 1
                        
                        # Try to get entry price from persistent tracker first
                        entry_price = current_price  # Default to current price
                        entry_trades_count = 0
                        entry_source_type = 'current price'
                        
                        if symbol in tracked_positions:
                            # Use tracked entry price (most accurate)
                            entry_price = tracked_positions[symbol]['entry_price']
                            entry_source_type = 'persistent tracker'
                            logger.info(f"{symbol}: Using tracked entry price ${entry_price:.2f}")
                        else:
                            # Fallback to trade history if not in tracker
                            try:
                                # Fetch trades in batches until we match the full quantity
                                max_iterations = 5  # Prevent infinite loops (500 trades max)
                                all_buy_trades = []
                                last_trade_id = None
                                accumulated_qty = 0.0
                                
                                for _ in range(max_iterations):
                                    params = {'symbol': symbol, 'limit': 100}
                                    if last_trade_id:
                                        params['fromId'] = last_trade_id
                                    
                                    trades = self.client.get_my_trades(**params)
                                    if not trades:
                                        break
                                    
                                    # Filter BUY trades (moving backwards in time)
                                    buy_trades_batch = [t for t in trades if t['isBuyer']]
                                    all_buy_trades.extend(buy_trades_batch)
                                    accumulated_qty += sum(float(t['qty']) for t in buy_trades_batch)
                                    
                                    # Stop if we've matched or exceeded our current quantity
                                    if accumulated_qty >= total * 0.99:  # 99% match is good enough
                                        break
                                    
                                    # Update last trade ID for next iteration
                                    last_trade_id = trades[-1]['id'] - 1
                                
                                if all_buy_trades:
                                    # Calculate weighted average entry price
                                    total_qty_trades = sum(float(t['qty']) for t in all_buy_trades)
                                    weighted_sum = sum(float(t['price']) * float(t['qty']) for t in all_buy_trades)
                                    
                                    if total_qty_trades > 0:
                                        entry_price = weighted_sum / total_qty_trades
                                        entry_trades_count = len(all_buy_trades)
                                        match_pct = (total_qty_trades / total) * 100
                                        logger.debug(
                                            f"{symbol}: Calculated entry from {entry_trades_count} trades "
                                            f"({match_pct:.1f}% qty match)"
                                        )
                                        
                                        if match_pct < 95:
                                            logger.warning(
                                                f"{symbol}: Partial qty match - holding {total:.6f} but "
                                                f"trades show {total_qty_trades:.6f} ({match_pct:.1f}%). "
                                                f"Entry price may be inaccurate."
                                        )
                            except Exception as e:
                                logger.debug(f"Could not fetch trade history for {symbol}: {e}")
                        
                        # Add to active positions
                        self.active_positions[symbol] = {
                            'entry_price': entry_price,
                            'size': position_value,  # Current USD value
                            'quantity': total,  # Actual coin quantity
                            'timestamp': datetime.now().isoformat(),
                            'ml_confidence': 0.0,  # Unknown for pre-existing positions
                            'loaded_from_account': True,
                            'entry_from_trades': entry_trades_count > 0,
                            # Initialize trailing stop fields
                            'highest_price': current_price,
                            'trailing_stop_activated': False,
                            'partial_exits': []
                        }
                        
                        pnl = (current_price - entry_price) * total  # P&L in USD
                        pnl_pct = ((current_price - entry_price) / entry_price) * 100
                        
                        if entry_source_type == 'persistent tracker':
                            entry_source = 'tracker (accurate)'
                        elif entry_trades_count > 0:
                            entry_source = f"{entry_trades_count} trades"
                        else:
                            entry_source = "current price (no history)"
                        
                        logger.info(
                            f"  📦 Found {symbol}: {total:.6f} {asset} @ ${current_price:.4f} "
                            f"(~${position_value:.2f}, entry: ${entry_price:.4f} from {entry_source}, "
                            f"P&L: ${pnl:.2f} / {pnl_pct:+.2f}%)"
                        )
                        
                        # Initialize strategy for this pair if not already done
                        if symbol not in self.strategies:
                            timeframe = self.config.timeframe
                            logger.info(f"  Initializing strategy for existing position: {symbol} ({timeframe})")
                            self.initialize_pair(symbol, timeframe)
                        
                except Exception as e:
                    logger.debug(f"Could not process {asset}: {e}")
                    continue
            
            if holdings_found > 0:
                total_value = sum(pos['size'] for pos in self.active_positions.values())
                logger.info(
                    f"✅ Loaded {holdings_found} existing positions from account "
                    f"(${total_value:.2f} total exposure)"
                )
                self.telegram.send_message(
                    f"🔄 Bot Started\n\n"
                    f"Loaded {holdings_found} existing positions:\n" +
                    "\n".join([
                        f"- {sym}: ${pos['size']:.2f}" 
                        for sym, pos in list(self.active_positions.items())[:10]
                    ]) +
                    f"\n\nTotal exposure: ${total_value:.2f}"
                )
            else:
                logger.info("No existing holdings found - clean start")
                
        except Exception as e:
            logger.error(f"Error loading existing holdings: {e}", exc_info=True)
        
        # Start continuous training in background (DISABLED - blocking bot startup)
        # logger.info("Starting continuous model trainer (retrains every 24h)...")
        # self.continuous_trainer.start()
        
        logger.info("=" * 60)
        logger.info(f"Trading Mode: {'DRY RUN' if self.config.dry_run else 'LIVE'}")
        logger.info(f"Max Positions: {self.max_concurrent_positions}")
        logger.info(f"Position Size: ${self.base_position_size}-${self.max_position_size} (dynamic)")
        logger.info(f"Portfolio Limit: Dynamic (full account balance)")
        logger.info(f"Continuous Training: Enabled (24h interval)")
        logger.info("=" * 60)
        
        self.running = True
        logger.info("🚀 Entering main trading loop...")
        
        # Start Real-time Position Monitor
        if self.rtm:
            await self.rtm.start()
            # Register existing positions with RTM
            for symbol, pos in self.active_positions.items():
                qty = pos.get('quantity', pos['size'] / pos['entry_price'])
                await self.rtm.register_position(symbol, pos['entry_price'], qty)
        
        # Track last model discovery time
        last_model_check = datetime.now()
        model_check_interval = 1800  # Check for new models every 30 minutes
        
        # Track last summary report time
        last_summary_report = datetime.now()
        summary_interval = 1800  # Send summary every 30 minutes (1800 seconds)
        
        # Track last daily report (send at midnight)
        last_daily_report = datetime.now().date()
        daily_report_sent_today = False
        
        # Main trading loop
        while self.running:
            try:
                # Periodically check for new models
                if (datetime.now() - last_model_check).total_seconds() > model_check_interval:
                    logger.info("🔍 Checking for new trained models...")
                    new_models = self.discover_models()
                    
                    # Find models we don't have yet
                    existing_symbols = set(self.strategies.keys())
                    new_symbols = [m for m in new_models if m['symbol'] not in existing_symbols]
                    
                    if new_symbols:
                        logger.info(f"📥 Found {len(new_symbols)} new models! Adding to trading...")
                        for model in new_symbols:
                            logger.info(f"  + {model['symbol']} ({model['timeframe']}): {model['accuracy']*100:.1f}% accuracy")
                            self.initialize_pair(model['symbol'], model['timeframe'])
                        
                        logger.info(f"✅ Now trading {len(self.strategies)} pairs (added {len(new_symbols)} new)")
                    else:
                        logger.debug(f"No new models found. Still trading {len(self.strategies)} pairs.")
                    
                    last_model_check = datetime.now()
                
                # Send periodic summary report (every 30 minutes)
                if (datetime.now() - last_summary_report).total_seconds() > summary_interval:
                    await self.send_performance_summary(interval='30min')
                    last_summary_report = datetime.now()
                
                # Send daily summary at midnight
                current_date = datetime.now().date()
                current_hour = datetime.now().hour
                if current_date > last_daily_report or (current_hour == 0 and not daily_report_sent_today):
                    await self.send_performance_summary(interval='daily')
                    last_daily_report = current_date
                    daily_report_sent_today = True
                elif current_hour != 0:
                    daily_report_sent_today = False  # Reset flag for next day
                
                logger.info("🔄 Starting trading cycle...")
                await self.trading_cycle()
                logger.info("✅ Trading cycle complete")
                
                # Record balance snapshot every 5 minutes for accurate chart
                try:
                    if not hasattr(self, '_last_snapshot_time'):
                        self._last_snapshot_time = datetime.now()
                    
                    time_since_snapshot = (datetime.now() - self._last_snapshot_time).total_seconds()
                    if time_since_snapshot >= 300:  # 5 minutes = 300 seconds
                        # Get actual USDT balance
                        account = self.client.get_account()
                        usdt_balance = float([b for b in account['balances'] if b['asset'] == 'USDT'][0]['free'])
                        
                        # Calculate position value
                        position_value = 0
                        for symbol, position in self.active_positions.items():
                            try:
                                ticker = self.client.get_symbol_ticker(symbol=symbol)
                                current_price = float(ticker['price'])
                                qty = position.get('quantity', position['size'] / position['entry_price'])
                                position_value += qty * current_price
                            except:
                                pass
                        
                        total_value = usdt_balance + position_value
                        
                        # Record snapshot
                        self.performance_tracker.record_balance_snapshot(
                            usdt_balance=usdt_balance,
                            total_value=total_value,
                            open_positions=len(self.active_positions),
                            position_value=position_value
                        )
                        
                        self._last_snapshot_time = datetime.now()
                        logger.debug(f"📊 Balance snapshot: ${total_value:.2f} (${usdt_balance:.2f} USDT + ${position_value:.2f} positions)")
                except Exception as e:
                    logger.debug(f"Could not record balance snapshot: {e}")
                
                # Delay between cycles to prevent duplicate signals
                # For 5m timeframe: scan every 3 seconds for fast signal detection
                # RTM handles position monitoring in parallel at high frequency
                cycle_delay = 3  # 3 seconds between scans
                logger.info(f"💤 Sleeping {cycle_delay}s before next cycle...")
                await asyncio.sleep(cycle_delay)
                logger.info("⏰ Sleep complete, starting next cycle")
            
            except KeyboardInterrupt:
                logger.info("Received stop signal")
                break
            except Exception as e:
                logger.error(f"Error in trading cycle: {e}", exc_info=True)
                await asyncio.sleep(5)
        
        logger.info("Multi-Pair Bot stopped")
    
    async def close_all_positions(self):
        """Close all open positions on shutdown"""
        if not self.active_positions:
            return
        
        logger.info(f"💼 Closing {len(self.active_positions)} open positions...")
        
        for symbol, position in list(self.active_positions.items()):
            try:
                # Get current price
                ticker = self.client.get_symbol_ticker(symbol=symbol)
                current_price = float(ticker['price'])
                entry_price = position['entry_price']
                pnl = ((current_price - entry_price) / entry_price) * 100
                
                logger.info(f"Closing {symbol} at ${current_price:.2f} (P&L: {pnl:+.2f}%)")
                
                # Create SELL signal
                sell_signal = {
                    'action': 'SELL',
                    'price': current_price,
                    'reason': 'Bot shutdown - auto-close',
                    'indicators': {}
                }
                
                # Execute SELL order
                order_manager = self.order_managers[symbol]
                order = await order_manager.execute_order(sell_signal)
                
                if order:
                    position = self.active_positions.pop(symbol)
                    pnl_usd = (current_price - entry_price) * (position['size'] / entry_price)
                    
                    # Record trade
                    self.performance_tracker.record_trade({
                        'symbol': symbol,
                        'action': 'SELL',
                        'entry_price': entry_price,
                        'exit_price': current_price,
                        'size': position['size'],
                        'pnl': pnl_usd,
                        'pnl_pct': pnl,
                        'ml_confidence': position.get('ml_confidence', 0),
                        'entry_time': position['timestamp'],
                        'exit_time': datetime.now().isoformat(),
                        'reason': 'Bot shutdown'
                    })
                    
                    logger.info(f"✅ {symbol} closed (P&L: {pnl:+.2f}%)")
            
            except Exception as e:
                logger.error(f"Error closing {symbol}: {e}")
        
        logger.info("All positions closed.")
    
    async def send_performance_summary(self, interval='30min'):
        """Send periodic performance summary to Telegram
        
        Args:
            interval: '30min' or 'daily'
        """
        try:
            # Get account balance
            account = self.client.get_account()
            usdt_balance = float([b for b in account['balances'] if b['asset'] == 'USDT'][0]['free'])
            
            # Calculate total portfolio value (USDT + positions)
            total_position_value = 0
            for symbol, position in self.active_positions.items():
                try:
                    ticker = self.client.get_symbol_ticker(symbol=symbol)
                    current_price = float(ticker['price'])
                    position_value = (position['size'] / position['entry_price']) * current_price
                    total_position_value += position_value
                except Exception as e:
                    logger.warning(f"Could not get price for {symbol}: {e}")
            
            total_portfolio = usdt_balance + total_position_value
            
            # Get recent performance stats
            hours = 24 if interval == 'daily' else 24  # Both use 24h for consistency
            stats = self.performance_tracker.get_stats(hours=hours)
            
            # Calculate unrealized P&L from open positions
            unrealized_pnl = 0
            position_details = []
            for symbol, position in self.active_positions.items():
                try:
                    ticker = self.client.get_symbol_ticker(symbol=symbol)
                    current_price = float(ticker['price'])
                    entry_price = position['entry_price']
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100
                    pnl_usd = (current_price - entry_price) * (position['size'] / entry_price)
                    unrealized_pnl += pnl_usd
                    
                    emoji = "🟢" if pnl_pct > 0 else "🔴"
                    position_details.append(
                        f"{emoji} {symbol}: {pnl_pct:+.2f}% (${pnl_usd:+.2f})"
                    )
                except Exception as e:
                    logger.warning(f"Could not calculate P&L for {symbol}: {e}")
            
            # Build summary message
            total_trades = stats.get('total_trades', 0)
            winning_trades = stats.get('winning_trades', 0)
            losing_trades = total_trades - winning_trades
            win_rate = stats.get('win_rate', 0) * 100
            total_pnl = stats.get('total_pnl', 0)
            
            summary = {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'win_rate': win_rate / 100,
                'total_pnl': total_pnl,
                'open_positions': len(self.active_positions)
            }
            
            # Enhanced message with portfolio value
            if interval == 'daily':
                title = "📊 <b>Daily Summary</b>"
                emoji = "🌙"
            else:
                title = "📊 <b>30-Minute Update</b>"
                emoji = "⏰"
            
            message = f"{title}\n\n"
            message += f"💰 <b>Portfolio</b>\n"
            message += f"  • Total Value: ${total_portfolio:.2f}\n"
            message += f"  • Free USDT: ${usdt_balance:.2f}\n"
            message += f"  • In Positions: ${total_position_value:.2f}\n\n"
            
            message += f"📈 <b>Trading (Last 24h)</b>\n"
            message += f"  • Trades: {total_trades} ({winning_trades}W / {losing_trades}L)\n"
            message += f"  • Win Rate: {win_rate:.1f}%\n"
            message += f"  • Realized P&L: ${total_pnl:+.2f}\n"
            message += f"  • Unrealized P&L: ${unrealized_pnl:+.2f}\n\n"
            
            message += f"📊 <b>Open Positions: {len(self.active_positions)}</b>\n"
            if position_details:
                for detail in position_details[:8]:  # Limit to 8 positions to avoid long message
                    message += f"  {detail}\n"
                if len(position_details) > 8:
                    message += f"  ... and {len(position_details) - 8} more\n"
            else:
                message += "  None\n"
            
            message += f"\n{emoji} {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            # Send via Telegram
            self.telegram.send_message(message)
            logger.info("📤 Sent performance summary to Telegram")
            
        except Exception as e:
            logger.error(f"Error sending performance summary: {e}", exc_info=True)
    
    async def async_stop(self):
        """Async stop for proper RTM cleanup"""
        logger.info("Stopping Multi-Pair Bot...")
        self.running = False
        
        # Stop Real-time Monitor first
        if self.rtm:
            try:
                await self.rtm.stop()
                logger.info("✅ RTM stopped")
            except Exception as e:
                logger.error(f"Error stopping RTM: {e}")
        
        # Stop continuous trainer
        if hasattr(self, 'continuous_trainer'):
            self.continuous_trainer.stop()
        
        logger.info("Bot stopped. Positions will be left open.")
    
    def stop(self):
        """Stop the bot (sync wrapper)"""
        logger.info("Stopping Multi-Pair Bot...")
        self.running = False
        
        # Note: RTM cleanup will happen on next event loop iteration
        if hasattr(self, 'continuous_trainer'):
            self.continuous_trainer.stop()
        
        logger.info("Bot stopped. Positions will be left open.")


async def main():
    """Main entry point"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/multi_pair_bot.log'),
            logging.StreamHandler()
        ]
    )
    
    # Load config
    config = Config()
    
    # Create and run bot
    bot = MultiPairBot(config)
    await bot.start()


if __name__ == '__main__':
    asyncio.run(main())
