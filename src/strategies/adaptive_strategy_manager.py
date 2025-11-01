"""
Adaptive Strategy Manager
Intelligently selects and switches between multiple strategies
"""
import logging
from typing import Optional, Dict, List
from datetime import datetime, timedelta

from strategies.ml_ema_strategy import MLEMAStrategy
from strategies.rl_strategy import RLStrategy
from strategies.advanced_ml_strategy import AdvancedMLStrategy
from utils.trade_logger import TradeLogger


class AdaptiveStrategyManager:
    """
    Manages multiple trading strategies and adaptively selects the best one
    
    Features:
    - Tracks performance of each strategy
    - Switches to best-performing strategy
    - Supports ML, RL, and hybrid strategies
    - Considers market regime in strategy selection
    """
    
    def __init__(self, config):
        """
        Args:
            config: Bot configuration
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Initialize all available strategies
        self.strategies = {}
        self._init_strategies()
        
        # Active strategy
        self.active_strategy_name = config.strategy or 'advanced_ml'
        
        # Performance tracking
        self.strategy_performance = {}
        self.trade_logger = None
        
        # Regime awareness
        self.current_regime = 'ranging'
        
        # Evaluation window
        self.eval_window_trades = 20  # Evaluate every N trades
        self.min_trades_for_switch = 10  # Min trades before considering switch
        
        try:
            self.trade_logger = TradeLogger()
        except Exception as e:
            self.logger.warning(f"Could not initialize TradeLogger: {e}")
    
    def _init_strategies(self):
        """Initialize all available strategies"""
        try:
            # Advanced ML Strategy
            self.strategies['advanced_ml'] = AdvancedMLStrategy(self.config)
            self.logger.info("✅ Initialized AdvancedMLStrategy")
        except Exception as e:
            self.logger.warning(f"Could not initialize AdvancedMLStrategy: {e}")
        
        try:
            # ML EMA Strategy
            self.strategies['ml_ema'] = MLEMAStrategy(self.config)
            self.logger.info("✅ Initialized MLEMAStrategy")
        except Exception as e:
            self.logger.warning(f"Could not initialize MLEMAStrategy: {e}")
        
        try:
            # RL Strategy
            self.strategies['rl'] = RLStrategy(self.config)
            self.logger.info("✅ Initialized RLStrategy")
        except Exception as e:
            self.logger.warning(f"Could not initialize RLStrategy: {e}")
        
        if not self.strategies:
            raise RuntimeError("No strategies could be initialized!")
        
        self.logger.info(f"Available strategies: {list(self.strategies.keys())}")
    
    def analyze(self, klines: list) -> Optional[Dict]:
        """
        Analyze market using active strategy
        
        Args:
            klines: Market data
            
        Returns:
            Signal dict or None
        """
        # Check if we should switch strategies
        if self.trade_logger:
            self._evaluate_and_switch_if_needed()
        
        # Get active strategy
        strategy = self.strategies.get(self.active_strategy_name)
        
        if not strategy:
            self.logger.error(f"Active strategy '{self.active_strategy_name}' not found!")
            # Fallback to first available
            self.active_strategy_name = list(self.strategies.keys())[0]
            strategy = self.strategies[self.active_strategy_name]
        
        # Get signal from active strategy
        signal = strategy.analyze(klines)
        
        if signal:
            # Add strategy metadata
            signal['strategy'] = self.active_strategy_name
            signal['regime'] = self.current_regime
        
        return signal
    
    def _evaluate_and_switch_if_needed(self):
        """
        Evaluate strategy performance and switch if needed
        """
        try:
            # Get recent trades for each strategy
            recent_trades = self.trade_logger.get_recent_trades(limit=100)
            
            if len(recent_trades) < self.min_trades_for_switch:
                return  # Not enough data yet
            
            # Group trades by strategy
            strategy_stats = {}
            
            for trade in recent_trades:
                strat = trade.get('strategy', 'unknown')
                
                if strat not in strategy_stats:
                    strategy_stats[strat] = {
                        'trades': 0,
                        'wins': 0,
                        'total_profit_pct': 0
                    }
                
                strategy_stats[strat]['trades'] += 1
                if trade['profit_loss_pct'] > 0:
                    strategy_stats[strat]['wins'] += 1
                strategy_stats[strat]['total_profit_pct'] += trade['profit_loss_pct']
            
            # Calculate win rates and avg profits
            for strat, stats in strategy_stats.items():
                if stats['trades'] > 0:
                    stats['win_rate'] = stats['wins'] / stats['trades']
                    stats['avg_profit'] = stats['total_profit_pct'] / stats['trades']
                else:
                    stats['win_rate'] = 0
                    stats['avg_profit'] = 0
            
            # Log performance
            self.logger.info("Strategy Performance:")
            for strat, stats in strategy_stats.items():
                self.logger.info(
                    f"  {strat}: {stats['trades']} trades, "
                    f"{stats['win_rate']*100:.1f}% win rate, "
                    f"{stats['avg_profit']:.2f}% avg profit"
                )
            
            # Find best strategy
            current_stats = strategy_stats.get(self.active_strategy_name)
            
            if not current_stats:
                return  # Current strategy has no trades yet
            
            # Check if any other strategy is significantly better
            for strat, stats in strategy_stats.items():
                if strat == self.active_strategy_name:
                    continue
                
                if stats['trades'] < 5:  # Need min sample
                    continue
                
                # Switch if:
                # 1. Win rate is 10%+ better AND avg profit positive
                # 2. OR avg profit is 2%+ better
                win_rate_better = stats['win_rate'] > current_stats['win_rate'] + 0.10
                profit_better = stats['avg_profit'] > current_stats['avg_profit'] + 2.0
                
                if (win_rate_better and stats['avg_profit'] > 0) or profit_better:
                    self.logger.info(
                        f"🔄 Switching strategy: {self.active_strategy_name} → {strat}\n"
                        f"   Current: {current_stats['win_rate']*100:.1f}% WR, "
                        f"{current_stats['avg_profit']:.2f}% avg\n"
                        f"   New: {stats['win_rate']*100:.1f}% WR, "
                        f"{stats['avg_profit']:.2f}% avg"
                    )
                    
                    self.active_strategy_name = strat
                    break
        
        except Exception as e:
            self.logger.error(f"Error evaluating strategies: {e}", exc_info=True)
    
    def update_position(self, position: Optional[Dict]):
        """
        Update position in all strategies
        
        Args:
            position: Current position or None
        """
        for strategy in self.strategies.values():
            if hasattr(strategy, 'update_position'):
                strategy.update_position(position)
    
    def update_regime(self, regime: str):
        """
        Update current market regime
        
        Args:
            regime: 'trending', 'ranging', or 'volatile'
        """
        self.current_regime = regime
        self.logger.debug(f"Market regime updated: {regime}")
    
    def get_active_strategy(self) -> str:
        """Get name of currently active strategy"""
        return self.active_strategy_name
    
    def force_strategy(self, strategy_name: str):
        """
        Force switch to specific strategy
        
        Args:
            strategy_name: Name of strategy to activate
        """
        if strategy_name in self.strategies:
            self.logger.info(f"Forcing strategy switch to: {strategy_name}")
            self.active_strategy_name = strategy_name
        else:
            self.logger.error(f"Strategy '{strategy_name}' not available")
