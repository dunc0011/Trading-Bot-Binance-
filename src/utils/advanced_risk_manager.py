"""
Advanced Risk Manager
- ATR-based dynamic stops
- Kelly Criterion position sizing
- Correlation filtering
- Drawdown limits
- Volatility-adjusted risk
"""
import logging
import numpy as np
import pandas as pd
from typing import Dict, Optional


logger = logging.getLogger(__name__)


class AdvancedRiskManager:
    """
    Advanced risk management with dynamic position sizing and stops
    """
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Risk parameters
        self.base_stop_loss_pct = getattr(config, 'stop_loss_percentage', 2.0) / 100
        self.base_take_profit_pct = getattr(config, 'take_profit_percentage', 5.0) / 100
        self.max_portfolio_risk = 0.02  # Max 2% of portfolio at risk
        self.max_drawdown_limit = 0.15  # Stop trading if 15% drawdown
        
        # Kelly Criterion parameters
        self.use_kelly = True
        self.kelly_fraction = 0.35  # Use 35% of Kelly (balanced for scalping)
        self.min_win_rate = 0.55  # Minimum win rate to trade
        
        # Track performance
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0
        self.peak_balance = None
        self.recent_trades = []  # Track last 20 trades for adaptive Kelly
        
    def calculate_atr_multiplier(self, klines: list, period: int = 14) -> float:
        """
        Calculate ATR-based stop loss multiplier
        
        Args:
            klines: Recent price data
            period: ATR period
            
        Returns:
            Multiplier for stop loss (1.0 = normal, >1.0 = wider stops in volatile markets)
        """
        if len(klines) < period + 1:
            return 1.0
        
        try:
            df = pd.DataFrame(klines[-period-1:], columns=[
                'timestamp', 'open', 'high', 'low', 'close', 
                'volume', 'close_time', 'quote_volume', 'trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore'
            ])
            
            df['high'] = pd.to_numeric(df['high'])
            df['low'] = pd.to_numeric(df['low'])
            df['close'] = pd.to_numeric(df['close'])
            
            # Calculate ATR
            high_low = df['high'] - df['low']
            high_close = abs(df['high'] - df['close'].shift(1))
            low_close = abs(df['low'] - df['close'].shift(1))
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = tr.rolling(period).mean().iloc[-1]
            
            # Current price
            current_price = df['close'].iloc[-1]
            
            # ATR as percentage of price
            atr_pct = (atr / current_price) * 100
            
            # Calculate multiplier
            # If ATR > 3%, use wider stops (up to 2x)
            # If ATR < 1%, use tighter stops (down to 0.5x)
            if atr_pct > 3:
                multiplier = min(2.0, 1.0 + (atr_pct - 3) / 3)
            elif atr_pct < 1:
                multiplier = max(0.5, 1.0 - (1 - atr_pct) / 2)
            else:
                multiplier = 1.0
            
            self.logger.debug(f"ATR: {atr_pct:.2f}%, multiplier: {multiplier:.2f}x")
            return multiplier
        
        except Exception as e:
            self.logger.error(f"ATR calculation failed: {e}")
            return 1.0
    
    def update_recent_performance(self, won: bool):
        """Update recent trade results for adaptive Kelly"""
        self.recent_trades.append(1 if won else 0)
        if len(self.recent_trades) > 20:  # Keep last 20 trades
            self.recent_trades.pop(0)
    
    def get_adaptive_kelly_fraction(self) -> float:
        """Calculate adaptive Kelly fraction based on recent performance"""
        if len(self.recent_trades) < 10:
            return self.kelly_fraction  # Default until we have data
        
        recent_win_rate = sum(self.recent_trades[-10:]) / 10
        
        # Adaptive Kelly: scale based on recent performance
        if recent_win_rate >= 0.7:  # Hot streak (70%+ wins)
            adaptive_fraction = min(self.kelly_fraction * 1.5, 0.6)  # More aggressive, cap at 60%
            self.logger.info(f"🔥 Hot streak detected! Win rate: {recent_win_rate*100:.0f}%, Kelly fraction: {adaptive_fraction:.2f}")
        elif recent_win_rate >= 0.6:  # Good performance
            adaptive_fraction = self.kelly_fraction * 1.2
        elif recent_win_rate >= 0.5:  # Normal
            adaptive_fraction = self.kelly_fraction
        elif recent_win_rate >= 0.4:  # Below average
            adaptive_fraction = self.kelly_fraction * 0.7
        else:  # Cold streak (<40% wins)
            adaptive_fraction = self.kelly_fraction * 0.5  # Very conservative
            self.logger.warning(f"❄️  Cold streak detected! Win rate: {recent_win_rate*100:.0f}%, reducing Kelly to {adaptive_fraction:.2f}")
        
        return adaptive_fraction
    
    def calculate_kelly_position_size(self, 
                                     ml_confidence: float,
                                     win_rate: float = None,
                                     avg_win: float = None,
                                     avg_loss: float = None) -> float:
        """
        Calculate optimal position size using Adaptive Kelly Criterion
        
        Kelly Formula: f = (p * b - q) / b
        where:
        f = fraction of capital to bet
        p = probability of winning (win rate)
        q = probability of losing (1 - p)
        b = win/loss ratio
        
        Args:
            ml_confidence: ML model confidence (0-1)
            win_rate: Historical win rate (optional)
            avg_win: Average win amount (optional)
            avg_loss: Average loss amount (optional)
            
        Returns:
            Position size multiplier (0-1)
        """
        if not self.use_kelly:
            return 1.0
        
        # Use ML confidence as win probability if no historical data
        if win_rate is None:
            win_rate = ml_confidence
        
        # Use default win/loss ratio based on TP/SL if not provided
        if avg_win is None or avg_loss is None:
            win_loss_ratio = self.base_take_profit_pct / self.base_stop_loss_pct
        else:
            win_loss_ratio = avg_win / (avg_loss + 1e-10)
        
        # Kelly formula
        p = win_rate
        q = 1 - p
        b = win_loss_ratio
        
        kelly = (p * b - q) / b
        
        # Apply ADAPTIVE Kelly fraction based on recent performance
        adaptive_fraction = self.get_adaptive_kelly_fraction()
        kelly_adjusted = kelly * adaptive_fraction
        
        # Bounds
        kelly_adjusted = np.clip(kelly_adjusted, 0.0, 1.0)
        
        self.logger.debug(
            f"Adaptive Kelly: p={p:.2f}, b={b:.2f}, fraction={adaptive_fraction:.2f}, "
            f"kelly={kelly:.3f}, adjusted={kelly_adjusted:.3f}"
        )
        
        return kelly_adjusted
    
    def check_drawdown_limit(self, current_balance: float) -> bool:
        """
        Check if maximum drawdown limit has been breached
        
        Args:
            current_balance: Current account balance
            
        Returns:
            True if trading should continue, False if should stop
        """
        if self.peak_balance is None:
            self.peak_balance = current_balance
            return True
        
        # Update peak
        if current_balance > self.peak_balance:
            self.peak_balance = current_balance
        
        # Calculate drawdown
        drawdown = (self.peak_balance - current_balance) / self.peak_balance
        
        if drawdown >= self.max_drawdown_limit:
            self.logger.error(
                f"⚠️  DRAWDOWN LIMIT BREACHED: {drawdown*100:.1f}% "
                f"(limit: {self.max_drawdown_limit*100:.1f}%)"
            )
            return False
        
        if drawdown > self.max_drawdown_limit * 0.7:
            self.logger.warning(
                f"⚠️  High drawdown: {drawdown*100:.1f}% "
                f"(approaching limit of {self.max_drawdown_limit*100:.1f}%)"
            )
        
        return True
    
    def validate_signal(self, 
                       signal: Dict,
                       klines: list = None,
                       current_balance: float = None) -> Optional[Dict]:
        """
        Validate and enhance trading signal with advanced risk management
        
        Args:
            signal: Trading signal from strategy
            klines: Recent price data for ATR calculation
            current_balance: Current account balance for drawdown check
            
        Returns:
            Enhanced signal with risk parameters or None if rejected
        """
        if signal is None:
            return None
        
        # Check drawdown limit
        if current_balance is not None:
            if not self.check_drawdown_limit(current_balance):
                self.logger.warning("Signal rejected: drawdown limit breached")
                return None
        
        # For BUY signals, calculate dynamic stops and position size
        if signal['action'] == 'BUY':
            # Get ML confidence
            ml_confidence = signal.get('indicators', {}).get('ml_confidence', 0.55)
            
            # Check minimum confidence
            if ml_confidence < self.min_win_rate:
                self.logger.info(
                    f"Signal rejected: confidence {ml_confidence:.2f} < "
                    f"minimum {self.min_win_rate:.2f}"
                )
                return None
            
            # Calculate ATR-based stop multiplier
            atr_multiplier = 1.0
            if klines:
                atr_multiplier = self.calculate_atr_multiplier(klines)
            
            # Dynamic stops
            stop_loss_pct = self.base_stop_loss_pct * atr_multiplier
            take_profit_pct = self.base_take_profit_pct * atr_multiplier
            
            # Calculate position size with Kelly
            # Use historical win rate if available
            win_rate = None
            if self.total_trades >= 20:  # Need minimum sample size
                win_rate = self.winning_trades / self.total_trades
            
            kelly_multiplier = self.calculate_kelly_position_size(
                ml_confidence=ml_confidence,
                win_rate=win_rate
            )
            
            # Enhanced signal
            enhanced_signal = {
                **signal,
                'stop_loss_pct': stop_loss_pct,
                'take_profit_pct': take_profit_pct,
                'stop_loss_price': signal['price'] * (1 - stop_loss_pct),
                'take_profit_price': signal['price'] * (1 + take_profit_pct),
                'position_size_multiplier': kelly_multiplier,
                'atr_multiplier': atr_multiplier,
                'risk_reward_ratio': take_profit_pct / stop_loss_pct
            }
            
            self.logger.info(
                f"✅ Signal validated: SL={stop_loss_pct*100:.2f}%, "
                f"TP={take_profit_pct*100:.2f}%, "
                f"Size multiplier={kelly_multiplier:.2f}x, "
                f"R:R={take_profit_pct/stop_loss_pct:.1f}:1"
            )
            
            return enhanced_signal
        
        # For SELL signals, just pass through
        return signal
    
    def record_trade(self, trade_result: Dict):
        """
        Record trade result for performance tracking
        
        Args:
            trade_result: Dict with 'pnl', 'win' keys
        """
        self.total_trades += 1
        
        if trade_result.get('win', False):
            self.winning_trades += 1
        
        pnl = trade_result.get('pnl', 0.0)
        self.total_pnl += pnl
        
        # Calculate current win rate
        win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0
        
        self.logger.info(
            f"Trade recorded: Win rate={win_rate*100:.1f}% "
            f"({self.winning_trades}/{self.total_trades}), "
            f"Total P&L=${self.total_pnl:.2f}"
        )
    
    def get_performance_metrics(self) -> Dict:
        """Get current performance metrics"""
        win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0
        
        return {
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'win_rate': win_rate,
            'total_pnl': self.total_pnl,
            'avg_pnl_per_trade': self.total_pnl / self.total_trades if self.total_trades > 0 else 0
        }
