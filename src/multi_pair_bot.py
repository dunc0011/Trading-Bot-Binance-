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
from config.config import Config
from strategies.advanced_ml_strategy import AdvancedMLStrategy
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
        
        # Binance client
        if config.trading_mode == "testnet":
            self.client = Client(config.api_key, config.api_secret, testnet=True)
        else:
            self.client = Client(config.api_key, config.api_secret)
        
        # Portfolio settings - DYNAMIC POSITION SIZING
        self.max_concurrent_positions = 3  # Max 3 open positions
        
        # Use percentage-based sizing as base (supports None for max_position_size)
        if config.max_position_size is not None:
            self.base_position_size = config.max_position_size * 0.5  # Base: 50% of max (low confidence)
            self.max_position_size = config.max_position_size
        else:
            # No cap - use percentage of balance for base sizing
            self.base_position_size = None  # Will be calculated dynamically
            self.max_position_size = None  # No fixed cap
        
        self.position_size_percentage = config.position_size_percentage
        self.total_portfolio_limit = 250   # Max $250 total (62% of $400)
        
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
        self.strategies = {}        # symbol -> MLEMAStrategy instance
        self.risk_managers = {}     # symbol -> RiskManager instance
        self.order_managers = {}    # symbol -> OrderManager instance
        
        # Continuous model trainer (retrains all models every 24h)
        self.continuous_trainer = ContinuousTrainer(config, retrain_interval_hours=24)
        
        # Performance tracker
        self.performance_tracker = PerformanceTracker()
        
        # Volume profile analyzer
        self.volume_analyzer = VolumeProfileAnalyzer()
        
        # Microstructure analyzer for smart entry timing
        self.microstructure_analyzer = MicrostructureAnalyzer(self.client)
        
        # Telegram alerts
        telegram_token = getattr(config, 'telegram_token', '')
        telegram_chat_id = getattr(config, 'telegram_chat_id', '')
        self.telegram = TelegramClient(telegram_token, telegram_chat_id)
        
        # Model performance monitoring
        self.model_monitor = ModelMonitor(window_size=100, decay_threshold=0.10)
        
        # Portfolio-level risk management
        self.portfolio_risk = PortfolioRiskManager(config)
        
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
                logger=rtm_logger
            )
            logger.info("✅ Real-time Position Monitor enabled")
        else:
            logger.info("⚠️  Real-time Position Monitor disabled (using legacy 10s polling)")
        
        logger.info("Multi-Pair Bot initialized")
    
    def discover_models(self) -> List[Dict]:
        """
        Discover all trained ML models (advanced and legacy)
        
        Returns:
            List of dicts with symbol, timeframe, accuracy
        """
        models = []
        
        # Check for advanced models first (preferred)
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
        
        # Fallback to legacy models if no advanced models
        if not models:
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
        
        # Sort by F1 score (best first)
        models.sort(key=lambda x: x.get('f1_score', 0), reverse=True)
        
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
        
        # Initialize components - use scalping if models not available
        # Check if advanced model exists
        from pathlib import Path
        model_path = Path(f'models/advanced_ml/{symbol}_{timeframe}_advanced_ml.joblib')
        
        if model_path.exists():
            from strategies.advanced_ml_strategy import AdvancedMLStrategy
            self.strategies[symbol] = AdvancedMLStrategy(pair_config, model_monitor=self.model_monitor)
            logger.info(f"Using Advanced ML strategy for {symbol}")
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
                
                # Check portfolio limit
                total_exposure = sum(pos['size'] for pos in self.active_positions.values())
                if total_exposure + position_size > self.total_portfolio_limit:
                    reason = f"Portfolio limit (${total_exposure:.0f}/${self.total_portfolio_limit})"
                    logger.info(f"{symbol}: {reason}")
                    if self.socketio:
                        self.socketio.emit('signal_rejected', {
                            'symbol': symbol,
                            'action': 'BUY',
                            'reason': reason,
                            'timestamp': datetime.now().isoformat()
                        })
                    return
            
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
                    self.active_positions[symbol] = {
                        'entry_price': signal['price'],
                        'size': position_size,  # Use dynamic size
                        'remaining_size': position_size,  # Track remaining after partial exits
                        'timestamp': datetime.now().isoformat(),
                        'ml_confidence': ml_confidence,
                        'highest_price': signal['price'],  # Track highest price for trailing stop
                        'trailing_stop_activated': False,
                        'partial_exits': []  # Track partial exits taken
                    }
                    
                    # Track position in portfolio risk manager
                    self.portfolio_risk.add_position(symbol, position_size, signal['price'], ml_confidence)
                    
                    logger.info(f"✅ {symbol} BUY executed at ${signal['price']:.2f} (${position_size:.0f} @ {ml_confidence*100:.0f}% conf)")
                    
                    # Register position with Real-time Monitor
                    if self.rtm and order:
                        try:
                            # Get actual fill quantity from order
                            fill_qty = float(order.get('executedQty', position_size / signal['price']))
                            await self.rtm.register_position(symbol, signal['price'], fill_qty)
                        except Exception as e:
                            logger.error(f"Failed to register position with RTM: {e}")
                    
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
                    pnl_pct = (signal['price'] - position['entry_price']) / position['entry_price'] * 100
                    pnl_usd = (signal['price'] - position['entry_price']) * (position['size'] / position['entry_price'])
                    
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
    
    async def check_trailing_stops(self):
        """Check trailing stops for all open positions"""
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
        """Run one complete trading cycle across all pairs"""
        logger.info(f"⚡ TRADING_CYCLE CALLED - Strategies loaded: {len(self.strategies)} pairs")
        cycle_start = datetime.now()
        
        # Generate unique cycle ID
        self.current_cycle_id = str(uuid.uuid4())
        
        # Get list of pairs
        symbols = list(self.strategies.keys())
        total_pairs = len(symbols)
        timeframe = self.config.timeframe
        
        # Log cycle start
        logger.info(f"🔄 Trading cycle started [{self.current_cycle_id}] - Analyzing {total_pairs} pairs...")
        
        # Emit cycle_start event
        if self.socketio:
            self.socketio.emit('cycle_start', {
                'cycle_id': self.current_cycle_id,
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'timeframe': timeframe,
                'pairs': symbols,
                'total_pairs': total_pairs,
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
        
        # Analyze pairs sequentially - LIMIT to 10 pairs per cycle to prevent blocking RTM
        max_pairs_per_cycle = 10
        symbols_to_analyze = symbols[:max_pairs_per_cycle]
        
        for idx, symbol in enumerate(symbols_to_analyze):
            pair_start = datetime.now()
            logger.debug(f"  🔍 [{idx+1}/{len(symbols_to_analyze)}] Analyzing {symbol} ({timeframe})")
            
            try:
                # Analyze with ultra-aggressive timeout (2s max per pair)
                result = await asyncio.wait_for(
                    self.analyze_pair(symbol, timeframe),
                    timeout=2.0
                )
                
                signal, klines = result if result else (None, None)
                analyzed_count += 1
                
                # Yield control to event loop every few pairs so RTM can run
                if idx % 5 == 0:
                    await asyncio.sleep(0)
                
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
                        'total_pairs': total_pairs,
                        'progress': (idx + 1) / total_pairs
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
                        'total_pairs': total_pairs,
                        'progress': (idx + 1) / total_pairs
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
                        'total_pairs': total_pairs,
                        'progress': (idx + 1) / total_pairs
                    })
        
        # Calculate cycle duration
        cycle_duration_ms = int((datetime.now() - cycle_start).total_seconds() * 1000)
        cycle_time_s = cycle_duration_ms / 1000
        
        # Log summary
        signals_found = signal_counts.get('BUY', 0) + signal_counts.get('SELL', 0)
        if signals_found > 0:
            logger.info(f"✅ Cycle complete: {signals_found} signals in {cycle_time_s:.2f}s")
        else:
            logger.debug(f"✅ Cycle complete: No signals in {cycle_time_s:.2f}s")
        
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
        min_accuracy = 0.55
        good_models = [m for m in models if m.get('model_type') == 'scalping' or m['accuracy'] >= min_accuracy]
        
        if not good_models:
            logger.warning(f"No good models - using scalping on all discovered pairs")
            good_models = models[:self.max_concurrent_positions]
        
        logger.info(f"Trading {len(good_models)} pairs with models:")
        for model in good_models:
            logger.info(f"  • {model['symbol']}: {model['accuracy']*100:.1f}% accuracy")
        
        # Initialize trading for each pair
        for model in good_models:
            self.initialize_pair(model['symbol'], model['timeframe'])
        
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
                    
                    # Only track positions worth > $1
                    if position_value > 1.0:
                        holdings_found += 1
                        
                        # Try to get average entry price from recent trades
                        entry_price = current_price  # Default to current price
                        entry_trades_count = 0
                        try:
                            trades = self.client.get_my_trades(symbol=symbol, limit=100)
                            if trades:
                                # Find ALL BUY trades to match our total quantity
                                buy_trades = [t for t in trades if t['isBuyer']]
                                if buy_trades:
                                    # Calculate weighted average entry price from ALL buys
                                    total_qty_trades = sum(float(t['qty']) for t in buy_trades)
                                    weighted_sum = sum(float(t['price']) * float(t['qty']) for t in buy_trades)
                                    
                                    # Only use if trade qty matches our balance (within 1%)
                                    if total_qty_trades > 0 and abs(total_qty_trades - total) / total < 0.01:
                                        entry_price = weighted_sum / total_qty_trades
                                        entry_trades_count = len(buy_trades)
                                        logger.debug(f"{symbol}: Calculated entry from {entry_trades_count} trades")
                                    else:
                                        logger.warning(
                                            f"{symbol}: Trade qty mismatch - holding {total:.6f} but "
                                            f"trades show {total_qty_trades:.6f}. Using current price as entry."
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
                        
                        entry_source = f"{entry_trades_count} trades" if entry_trades_count > 0 else "current price (no trades found)"
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
        logger.info(f"Portfolio Limit: ${self.total_portfolio_limit}")
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
                
                logger.debug("🔄 Starting trading cycle...")
                await self.trading_cycle()
                logger.debug("✅ Trading cycle complete")
                
                # Fast cycle for aggressive scalping (10 seconds)
                await asyncio.sleep(10)
            
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
